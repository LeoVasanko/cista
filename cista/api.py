import asyncio
from pathlib import PurePosixPath
from secrets import token_bytes

import msgspec
from sanic import Blueprint, json
from sanic.exceptions import BadRequest

from cista import __version__, auth, config, sso, watching
from cista.fileio import FileServer
from cista.protocol import ControlTypes, StatusMsg
from cista.util.apphelpers import asend, websocket_wrapper

bp = Blueprint("api", url_prefix="/api")
fileserver = FileServer()


@bp.before_server_start
async def start_fileserver(app):
    await fileserver.start()


@bp.after_server_stop
async def stop_fileserver(app):
    await fileserver.stop()


@bp.websocket("control")
@websocket_wrapper
async def control(req, ws):
    while True:
        cmd = msgspec.json.decode(await ws.recv(), type=ControlTypes)
        await asyncio.to_thread(cmd)
        # Signal the watcher about affected paths
        watching.notify_change(*cmd.affected_paths())
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


@bp.get("config")
async def get_config(request):
    await auth.verify(request, privileged=True)
    return json(
        {
            "name": config.config.name,
            "public": config.config.public,
        }
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


@bp.put("config/name")
async def update_name(request):
    await auth.verify(request, privileged=True)
    try:
        name = request.json["name"]
        if not isinstance(name, str):
            raise ValueError("name must be a string")
    except KeyError:
        raise BadRequest("Missing name field") from None
    except ValueError as e:
        raise BadRequest(str(e)) from None
    config.update_config({"name": name})
    # Return the effective name (fallback to path.name if empty)
    effective_name = name or config.config.path.name
    return json({"message": "Server name updated", "name": effective_name})
