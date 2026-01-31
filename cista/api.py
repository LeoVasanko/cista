import asyncio
import typing
from secrets import token_bytes

import msgspec
from sanic import Blueprint, json
from sanic.exceptions import BadRequest

from cista import __version__, auth, config, sso, watching
from cista.fileio import FileServer
from cista.protocol import ControlTypes, FileRange, StatusMsg
from cista.util.apphelpers import asend, websocket_wrapper

bp = Blueprint("api", url_prefix="/api")
fileserver = FileServer()


@bp.before_server_start
async def start_fileserver(app):
    await fileserver.start()


@bp.after_server_stop
async def stop_fileserver(app):
    await fileserver.stop()


@bp.websocket("upload")
@websocket_wrapper
async def upload(req, ws):
    alink = fileserver.alink
    while True:
        req = None
        text = await ws.recv()
        if not isinstance(text, str):
            raise ValueError(
                f"Expected JSON control, got binary len(data) = {len(text)}",
            )
        req = msgspec.json.decode(text, type=FileRange)
        pos = req.start
        while True:
            data = await ws.recv()
            if not isinstance(data, bytes):
                break
            if len(data) > req.end - pos:
                raise ValueError(
                    f"Expected up to {req.end - pos} bytes, got {len(data)} bytes"
                )
            sentsize = await alink(("upload", req.name, pos, data, req.size))
            pos += typing.cast(int, sentsize)
            if pos >= req.end:
                break
        if pos != req.end:
            d = f"{len(data)} bytes" if isinstance(data, bytes) else data
            raise ValueError(f"Expected {req.end - pos} more bytes, got {d}")
        # Report success
        res = StatusMsg(status="ack", req=req)
        await asend(ws, res)


@bp.websocket("download")
@websocket_wrapper
async def download(req, ws):
    alink = fileserver.alink
    while True:
        req = None
        text = await ws.recv()
        if not isinstance(text, str):
            raise ValueError(
                f"Expected JSON control, got binary len(data) = {len(text)}",
            )
        req = msgspec.json.decode(text, type=FileRange)
        pos = req.start
        while pos < req.end:
            end = min(req.end, pos + (1 << 20))
            data = typing.cast(bytes, await alink(("download", req.name, pos, end)))
            await asend(ws, data)
            pos += len(data)
        # Report success
        res = StatusMsg(status="ack", req=req)
        await asend(ws, res)


@bp.websocket("control")
@websocket_wrapper
async def control(req, ws):
    while True:
        cmd = msgspec.json.decode(await ws.recv(), type=ControlTypes)
        await asyncio.to_thread(cmd)
        await asend(ws, StatusMsg(status="ack", req=cmd))


@bp.websocket("watch")
@websocket_wrapper
async def watch(req, ws):
    # Build user info from either built-in auth or SSO
    user_info = None
    if sso.paskia_enabled():
        # SSO auth: call validation to get user info (don't enforce auth in public mode)
        try:
            await sso.validate_sso_request(req)
        except Exception:
            pass  # Ignore auth errors, user_info stays None
        if sso_user := getattr(req.ctx, "sso_user", None):
            ctx = sso_user.get("ctx", {})
            perms = ctx.get("permissions", [])
            user_info = {
                "username": ctx.get("user", {}).get("display_name", ""),
                "privileged": "cista:admin" in perms,
            }
    elif req.ctx.user:
        # Built-in auth: use local user database
        user_info = {
            "username": req.ctx.username,
            "privileged": req.ctx.user.privileged,
        }

    await ws.send(
        msgspec.json.encode(
            {
                "server": {
                    "name": config.config.name or config.config.path.name,
                    "version": __version__,
                    "public": config.config.public,
                    "paskia": sso.paskia_enabled(),
                },
                "user": user_info,
            }
        ).decode()
    )
    uuid = token_bytes(16)
    try:
        q, space, root = await asyncio.get_event_loop().run_in_executor(
            req.app.ctx.threadexec, subscribe, uuid, ws
        )
        await ws.send(space)
        await ws.send(root)
        # Send updates
        while True:
            await ws.send(await q.get())
    except RuntimeError as e:
        if str(e) == "cannot schedule new futures after shutdown":
            return  # Server shutting down, drop the WebSocket
        raise
    finally:
        watching.pubsub.pop(uuid, None)  # Remove whether it got added yet or not


def subscribe(uuid, ws):
    with watching.state.lock:
        q = watching.pubsub[uuid] = asyncio.Queue()
        # Init with disk usage and full tree
        return (
            q,
            watching.format_space(watching.state.space),
            watching.format_root(watching.state.root),
        )


@bp.put("config/public")
async def update_public(request):
    await auth.verify(request, privileged=True)
    try:
        public = request.json["public"]
        if not isinstance(public, bool):
            raise ValueError("public must be a boolean")
    except KeyError:
        raise BadRequest("Missing public field") from None
    except ValueError as e:
        raise BadRequest(str(e)) from None
    config.update_config({"public": public})
    return json({"message": "Public access setting updated", "public": public})
