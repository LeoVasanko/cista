"""SSO (paskia) authentication proxy and validation module.

When paskia mode is enabled (PASKIA_BACKEND_URL is set):
- Backend validates requests against PASKIA_BACKEND_URL/auth/api/validate?perm=cista:login
- All /auth/* requests are proxied to the paskia backend

Environment variables:
  PASKIA_BACKEND_URL - URL of the paskia auth server (e.g., http://localhost:4401)
                       Must include scheme (http/https), no trailing slash
"""

import asyncio
import os
import re

import httpx
import websockets
from sanic import Blueprint
from sanic.exceptions import Forbidden, SanicException, Unauthorized
from sanic.log import logger

# Auth backend URL for SSO validation (from env, no trailing slash)
_raw_url = os.environ.get("PASKIA_BACKEND_URL", "").rstrip("/")

# Validate and set PASKIA_BACKEND_URL
if _raw_url:
    if not re.match(r"^https?://[^\s/]+$", _raw_url):
        raise ValueError(
            f"Invalid PASKIA_BACKEND_URL: {_raw_url!r} - "
            "must be http(s)://host[:port] with no path or trailing slash"
        )
    PASKIA_BACKEND_URL = _raw_url
else:
    PASKIA_BACKEND_URL = ""


def paskia_enabled() -> bool:
    """Check if paskia SSO mode is enabled (PASKIA_BACKEND_URL is set)."""
    return bool(PASKIA_BACKEND_URL)


# Shared httpx client for SSO requests (reused for connection pooling)
_client: httpx.AsyncClient | None = None


async def get_client() -> httpx.AsyncClient:
    """Get or create the shared httpx client."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=1.0)
    return _client


async def close_client():
    """Close the shared httpx client."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None


async def validate_sso_request(request, *, perm: str = "cista:login") -> dict | None:
    """Validate an SSO request against the auth backend.

    Args:
        request: The Sanic request object
        perm: Permission to validate (default: cista:login, privileged also cista:admin)

    Returns:
        User info dict if valid, None if validation fails with auth required response

    Raises:
        Forbidden: If access is denied (403)
        Unauthorized: If authentication is required (401)
    """
    if not paskia_enabled():
        return None

    client = await get_client()

    headers = {}
    if "host" in request.headers:
        headers["host"] = request.headers["host"]
    if "cookie" in request.headers:
        headers["cookie"] = request.headers["cookie"]
    if "authorization" in request.headers:
        headers["authorization"] = request.headers["authorization"]
    headers["accept"] = "application/json"
    headers["x-forwarded-for"] = request.client_ip
    headers["x-forwarded-host"] = request.host
    headers["x-forwarded-proto"] = request.scheme

    url = f"{PASKIA_BACKEND_URL}/auth/api/validate?perm={perm}"

    try:
        response = await client.post(
            url,
            headers=headers,
        )

        if response.status_code == 200:
            try:
                data = response.json()
                request.ctx.sso_user = data
                if "set-cookie" in response.headers:
                    request.ctx.sso_cookies = response.headers.get_list("set-cookie")
                return data
            except Exception:
                request.ctx.sso_user = {}
                return {}

        try:
            error_data = response.json()
        except Exception:
            error_data = {"detail": response.text or "Authentication error"}

        if response.status_code == 401:
            if "auth" in error_data and "iframe" in error_data["auth"]:
                error_data["auth"]["iframe"] += "&theme=light"
            raise Unauthorized(
                error_data.get("detail", "Authentication required"),
                "cookie",
                context=error_data,
                quiet=True,
            )
        elif response.status_code == 403:
            raise Forbidden(
                error_data.get("detail", "Access denied"),
                context=error_data,
                quiet=True,
            )
        else:
            detail = error_data.get("detail", "")
            logger.warning(
                f"SSO validation {url} returned {response.status_code}: {detail}"
            )
            raise Forbidden(
                detail or "Authentication error",
                context=error_data,
                quiet=True,
            )

    except httpx.RequestError as e:
        logger.error(f"SSO validation {url} network error: {e}")
        raise SanicException(
            "Authentication service unavailable",
            status_code=502,
            quiet=True,
        )


async def proxy_auth_request(request):
    """Proxy a request to the auth backend.

    All requests under /auth/ are proxied when paskia mode is enabled.
    """
    client = await get_client()

    path = request.path
    query_string = request.query_string
    url = f"{PASKIA_BACKEND_URL}{path}"
    if query_string:
        url = f"{url}?{query_string}"

    skip_headers = {
        "connection",
        "keep-alive",
        "transfer-encoding",
        "te",
        "trailer",
        "upgrade",
        "proxy-authorization",
        "proxy-authenticate",
        "forwarded",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-proto",
    }

    headers = [
        (key, value)
        for key, value in request.headers.items()
        if key.lower() not in skip_headers
    ]
    headers.append(("x-forwarded-for", request.client_ip))
    headers.append(("x-forwarded-host", request.host))
    headers.append(("x-forwarded-proto", request.scheme))

    try:
        async with client.stream(
            method=request.method,
            url=url,
            headers=headers,
            content=request.body if request.body else None,
        ) as response:
            raw_content = b"".join([chunk async for chunk in response.aiter_raw()])

            resp_hop_by_hop = {
                "connection",
                "keep-alive",
                "transfer-encoding",
                "te",
                "trailer",
                "upgrade",
            }

            resp_headers = [
                (key, value)
                for key, value in response.headers.multi_items()
                if key.lower() not in resp_hop_by_hop
            ]

            from sanic import raw as raw_response

            return raw_response(
                raw_content,
                status=response.status_code,
                headers=resp_headers,
                content_type=response.headers.get("content-type", "application/json"),
            )

    except httpx.RequestError as e:
        logger.error(f"Auth proxy request failed: {e}")
        from sanic import json

        return json(
            {"detail": "Authentication service unavailable", "error": str(e)},
            status=503,
        )


async def proxy_auth_websocket(request, ws):
    """Proxy a WebSocket connection to the auth backend."""
    path = request.path
    query_string = request.query_string
    ws_backend = PASKIA_BACKEND_URL.replace("http://", "ws://").replace(
        "https://", "wss://"
    )
    url = f"{ws_backend}{path}"
    if query_string:
        url = f"{url}?{query_string}"

    additional_headers = {}
    if "cookie" in request.headers:
        additional_headers["cookie"] = request.headers["cookie"]
    if "authorization" in request.headers:
        additional_headers["authorization"] = request.headers["authorization"]
    if "origin" in request.headers:
        additional_headers["origin"] = request.headers["origin"]
    if "user-agent" in request.headers:
        additional_headers["user-agent"] = request.headers["user-agent"]
    additional_headers["x-forwarded-for"] = request.ip
    additional_headers["x-forwarded-host"] = request.host
    additional_headers["x-forwarded-proto"] = request.scheme

    try:
        async with websockets.connect(
            url, additional_headers=additional_headers
        ) as backend_ws:

            async def forward_to_backend():
                try:
                    async for message in ws:
                        await backend_ws.send(message)
                except Exception:
                    pass

            async def forward_to_client():
                try:
                    async for message in backend_ws:
                        await ws.send(message)
                except Exception:
                    pass

            await asyncio.gather(
                forward_to_backend(),
                forward_to_client(),
                return_exceptions=True,
            )
    except Exception as e:
        logger.error(f"WebSocket proxy to {url} failed: {e}")


def _is_websocket_request(request) -> bool:
    """Check if the request is a WebSocket upgrade request."""
    connection = request.headers.get("connection", "").lower()
    upgrade = request.headers.get("upgrade", "").lower()
    connection_tokens = [t.strip() for t in connection.split(",")]
    return "upgrade" in connection_tokens and upgrade == "websocket"


async def _handle_websocket_upgrade(request):
    """Handle WebSocket upgrade and proxy the connection."""
    protocol = request.transport.get_protocol()
    ws = await protocol.websocket_handshake(request, subprotocols=None)
    await proxy_auth_websocket(request, ws)


# Blueprint for auth proxy routes (only registered when paskia_enabled())
bp = Blueprint("sso", url_prefix="/auth")


@bp.route(
    "/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]
)
async def auth_proxy(request, path=""):
    """Proxy all auth requests to the auth backend."""
    if _is_websocket_request(request):
        await _handle_websocket_upgrade(request)
        from sanic import empty

        return empty()
    return await proxy_auth_request(request)


@bp.route("/", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def auth_proxy_root(request):
    """Proxy root auth requests to the auth backend."""
    if _is_websocket_request(request):
        await _handle_websocket_upgrade(request)
        from sanic import empty

        return empty()
    return await proxy_auth_request(request)
