import asyncio
import time
from functools import wraps

import msgspec
import websockets.exceptions
from sanic import errorpages
from sanic.exceptions import SanicException, Unauthorized
from sanic.log import logger
from sanic.response import raw, redirect

from cista import auth, config, session, sharefs, sso, watching
from cista.protocol import ErrorMsg
from cista.sanic_logging import log_ws_close, log_ws_open


def asend(ws, msg):
    """Send JSON message or bytes to a websocket"""
    return ws.send(msg if isinstance(msg, bytes) else msgspec.json.encode(msg).decode())


def jres(data, **kwargs):
    """JSON Sanic response, using msgspec encoding"""
    return raw(msgspec.json.encode(data), content_type="application/json", **kwargs)


async def handle_sanic_exception(request, e):
    context, code = {}, 500
    headers = None
    message = str(e)
    if isinstance(e, SanicException):
        context = e.context or {}
        code = e.status_code
        headers = getattr(e, "headers", None)
    if not message or (not request.app.debug and code == 500):
        message = "Internal Server Error"
    message = f"⚠️ {message}" if code < 500 else f"🛑 {message}"
    if code == 500:
        logger.exception(e)
    # Non-browsers get JSON errors
    if "text/html" not in request.headers.accept:
        # Include auth context if present (for SSO auth required responses)
        # Auth must be at top level for paskia library to detect it
        response_data = {"code": code, "message": message, "detail": message, **context}
        return jres(
            response_data,
            status=code,
            headers=headers,
        )
    # Redirections flash the error message via cookies
    if "redirect" in context:
        res = redirect(context["redirect"])
        res.cookies.add_cookie("message", message, max_age=5)
        return res
    # Otherwise use Sanic's default error page
    return errorpages.HTMLRenderer(request, e, debug=request.app.debug).render()


def websocket_wrapper(handler):
    """Decorator for websocket handlers that catches exceptions and sends them back to the client"""

    @wraps(handler)
    async def wrapper(request, ws, *args, **kwargs):
        username = getattr(request.ctx, "username", None)
        extra = username or None
        start = time.perf_counter()
        ws_id = log_ws_open(request, extra=extra)
        close_extra = None
        try:
            await auth.verify(request)
            await handler(request, ws, *args, **kwargs)
        except (
            websockets.exceptions.ConnectionClosedOK,
            websockets.exceptions.ConnectionClosedError,
        ):
            # Normal websocket closure - already logged in access log
            pass
        except Exception as e:
            context, code, message = {}, 500, str(e) or "Internal Server Error"
            if isinstance(e, SanicException):
                context = e.context or {}
                code = e.status_code
            message = f"⚠️ {message}" if code < 500 else f"🛑 {message}"
            await asend(ws, ErrorMsg({"code": code, "message": message, **context}))
            if not getattr(e, "quiet", False) or code == 500:
                logger.exception(f"{code} {e!r}")
            close_extra = f"{code} {message}"
            raise
        finally:
            duration = time.perf_counter() - start
            close_code = None
            try:
                p = ws.ws_proto
                if p.close_rcvd is not None:
                    close_code = p.close_rcvd.code
                elif p.close_sent is not None:
                    close_code = p.close_sent.code
                elif getattr(p, "close_code", None) is not None:
                    close_code = p.close_code
            except AttributeError:
                pass
            log_ws_close(ws_id, close_code, duration, extra=close_extra)

    return wrapper


class StopError(Exception):
    """Used internally to end a watch websocket's task group cleanly."""


async def get_watch_user_info(request):
    """Return the current user info for a watch websocket, re-validating auth.

    Handles all three auth modes:
      - Paskia/SSO: re-validates with the auth backend (cache-friendly)
      - Built-in: re-reads the local session cookie from the live store
      - Public: returns None when no session is present

    Raises Unauthorized/Forbidden in non-public mode when the session is gone.
    """
    # Long-lived API/share tokens are validated once at handshake; re-checking
    # them on every message would add unnecessary backend calls.
    if getattr(request.ctx, "auth_token", None) is not None:
        return None

    if sso.paskia_enabled():
        try:
            await sso.validate_sso_request(request, renew=False)
        except SanicException:
            if config.config.public:
                return None
            raise
        sso_user = getattr(request.ctx, "sso_user", None) or {}
        if sso_user:
            ctx = sso_user.get("ctx", {})
            perms = ctx.get("permissions", [])
            return {
                "username": ctx.get("user", {}).get("display_name", ""),
                "privileged": "cista:admin" in perms,
            }
        return None

    s = session.get(request)
    if s:
        user = config.config.users.get(s.get("username"))
        if user:
            return {"username": s["username"], "privileged": user.privileged}

    if config.config.public:
        return None

    raise Unauthorized("Login required", "cookie", quiet=True)


async def _check_watch_auth_or_stop(request, ws) -> None:
    """Re-validate watch auth; on failure send an error and raise StopError."""
    try:
        await get_watch_user_info(request)
    except SanicException as exc:
        # Match the error format used by websocket_wrapper
        message = f"⚠️ {str(exc) or 'Authentication error'}"
        await asend(
            ws,
            ErrorMsg(
                {"code": exc.status_code, "message": message, **(exc.context or {})}
            ),
        )
        raise StopError from None


async def run_auth_checked_watch(request, ws, queue, share_token) -> None:
    """Run the watch websocket loop with per-message and periodic auth checks.

    Messages are forwarded from *queue* to *ws*. Auth is re-checked before each
    message (hitting the SSO cache in the common case) and every 10 seconds when
    idle, so a session invalidated on the backend does not stay open forever.
    """

    async def consume() -> None:
        while True:
            item = await queue.get()
            await _check_watch_auth_or_stop(request, ws)
            if share_token is None or (
                isinstance(item, str) and item.startswith('{"space"')
            ):
                await ws.send(item)
            else:
                await ws.send(
                    watching.format_root(sharefs.build_virtual_root(share_token))
                )

    async def idle_checker() -> None:
        while True:
            await asyncio.sleep(10)
            await _check_watch_auth_or_stop(request, ws)

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(consume())
            tg.create_task(idle_checker())
    except* StopError:
        pass
