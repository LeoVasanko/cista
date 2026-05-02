import asyncio
from secrets import token_bytes

import msgspec
from sanic import Blueprint, json
from sanic.exceptions import BadRequest
from sanic.log import logger

from cista import __version__, auth, config, onlyoffice, sharefs, sso, watching
from cista.auth import (
    create_share_token_handler,
    create_token_handler,
    delete_token_handler,
    list_tokens_handler,
)
from cista.fileio import FileServer
from cista.util.apphelpers import websocket_wrapper

bp = Blueprint("api", url_prefix="/api")
fileserver = FileServer()


@bp.before_server_start
async def start_fileserver(app):
    await fileserver.start()


@bp.after_server_stop
async def stop_fileserver(app):
    await fileserver.stop()


@bp.websocket("watch")
@websocket_wrapper
async def watch(req, ws):
    # Build user info from either built-in auth or SSO
    user_info = None
    if sso.paskia_enabled():
        # SSO auth: call validation to get user info (don't enforce auth in public mode)
        try:
            await sso.validate_sso_request(req)
        except Exception as e:
            logger.debug("watch SSO validation failed: %s", e)
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
                    "office_previews": await onlyoffice.is_available_cached(),
                },
                "user": user_info,
            }
        ).decode()
    )
    uuid = token_bytes(16)
    share_token = auth.request_share_token(req)
    try:
        q, space, root = await asyncio.get_event_loop().run_in_executor(
            req.app.ctx.threadexec, subscribe, uuid, ws
        )
        await ws.send(space)
        if share_token is None:
            await ws.send(root)
        else:
            await ws.send(watching.format_root(sharefs.build_virtual_root(share_token)))
        # Send updates
        while True:
            msg = await q.get()
            if share_token is None or (
                isinstance(msg, str) and msg.startswith('{"space"')
            ):
                await ws.send(msg)
            else:
                await ws.send(
                    watching.format_root(sharefs.build_virtual_root(share_token))
                )
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


# Token management endpoints (available in all modes; primary path in SSO mode)
@bp.get("tokens")
async def list_api_tokens(request):
    return await list_tokens_handler(request)


@bp.post("tokens")
async def create_api_token(request):
    return await create_token_handler(request)


@bp.delete("tokens/<token_id>")
async def delete_api_token(request, token_id):
    return await delete_token_handler(request, token_id)


@bp.post("share-tokens")
async def create_share_token(request):
    return await create_share_token_handler(request)
