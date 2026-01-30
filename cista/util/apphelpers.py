from functools import wraps

import msgspec
from sanic import errorpages
from sanic.exceptions import SanicException
from sanic.log import logger
from sanic.response import raw, redirect

from cista import auth
from cista.protocol import ErrorMsg


def asend(ws, msg):
    """Send JSON message or bytes to a websocket"""
    return ws.send(msg if isinstance(msg, bytes) else msgspec.json.encode(msg).decode())


def jres(data, **kwargs):
    """JSON Sanic response, using msgspec encoding"""
    return raw(msgspec.json.encode(data), content_type="application/json", **kwargs)


async def handle_sanic_exception(request, e):
    context, code = {}, 500
    message = str(e)
    if isinstance(e, SanicException):
        context = e.context or {}
        code = e.status_code
    if not message or not request.app.debug and code == 500:
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
        try:
            await auth.verify(request)
            await handler(request, ws, *args, **kwargs)
        except Exception as e:
            context, code, message = {}, 500, str(e) or "Internal Server Error"
            if isinstance(e, SanicException):
                context = e.context or {}
                code = e.status_code
            message = f"⚠️ {message}" if code < 500 else f"🛑 {message}"
            await asend(ws, ErrorMsg({"code": code, "message": message, **context}))
            if not getattr(e, "quiet", False) or code == 500:
                logger.exception(f"{code} {e!r}")
            raise

    return wrapper
