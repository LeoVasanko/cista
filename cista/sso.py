"""SSO (paskia) authentication proxy and validation module.

When paskia authentication mode is enabled:
- Backend validates requests against PASKIA_BACKEND_URL/auth/api/validate?perm=cista:login
- All /auth/* requests are proxied to the paskia backend

Environment variables:
  PASKIA_BACKEND_URL - URL of the paskia auth server (default: http://localhost:4401)
"""

import os

import httpx
from sanic import Blueprint
from sanic.exceptions import Forbidden, Unauthorized
from sanic.log import logger

from cista import config

# Auth backend URL for SSO validation (from env with default, no trailing slash)
PASKIA_BACKEND_URL = os.environ.get("PASKIA_BACKEND_URL", "http://localhost:4401").rstrip("/")

# Shared httpx client for SSO requests (reused for connection pooling)
_client: httpx.AsyncClient | None = None


async def get_client() -> httpx.AsyncClient:
    """Get or create the shared httpx client."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=10.0)
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
    if config.config.authentication != "paskia":
        return None

    client = await get_client()

    # Forward relevant headers (especially cookies for session validation)
    headers = {}
    if "cookie" in request.headers:
        headers["cookie"] = request.headers["cookie"]
    if "authorization" in request.headers:
        headers["authorization"] = request.headers["authorization"]
    headers["accept"] = "application/json"
    headers["x-forwarded-for"] = request.ip
    if "x-forwarded-for" in request.headers:
        headers["x-forwarded-for"] = request.headers["x-forwarded-for"]

    try:
        response = await client.post(
            f"{PASKIA_BACKEND_URL}/auth/api/validate",
            params={"perm": perm},
            headers=headers,
        )

        if response.status_code == 200:
            # Validation successful
            try:
                return response.json()
            except Exception:
                return {}

        # Handle auth errors - return the JSON response for frontend handling
        try:
            error_data = response.json()
        except Exception:
            error_data = {"detail": response.text or "Authentication error"}

        if response.status_code == 401:
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
            logger.warning(
                f"SSO validation returned unexpected status: {response.status_code}"
            )
            raise Forbidden(
                error_data.get("detail", "Authentication error"),
                context=error_data,
                quiet=True,
            )

    except httpx.RequestError as e:
        logger.error(f"SSO validation request failed: {e}")
        raise Forbidden(
            "Authentication service unavailable",
            quiet=True,
        )


async def proxy_auth_request(request):
    """Proxy a request to the auth backend.

    All requests under /auth/ are proxied when paskia mode is enabled.
    """
    client = await get_client()

    # Build the target URL - strip any prefix and forward to auth backend
    path = request.path
    query_string = request.query_string
    url = f"{PASKIA_BACKEND_URL}{path}"
    if query_string:
        url = f"{url}?{query_string}"

    # Forward headers
    headers = dict(request.headers)
    # Remove hop-by-hop headers
    for hop_header in [
        "host",
        "connection",
        "keep-alive",
        "transfer-encoding",
        "te",
        "trailer",
        "upgrade",
        "proxy-authorization",
        "proxy-authenticate",
    ]:
        headers.pop(hop_header, None)

    # Add forwarded headers
    headers["x-forwarded-for"] = request.ip
    headers["x-forwarded-host"] = request.host
    headers["x-forwarded-proto"] = request.scheme

    try:
        response = await client.request(
            method=request.method,
            url=url,
            headers=headers,
            content=request.body if request.body else None,
        )

        # Build response headers
        resp_headers = dict(response.headers)
        # Remove hop-by-hop headers from response
        for hop_header in [
            "connection",
            "keep-alive",
            "transfer-encoding",
            "te",
            "trailer",
            "upgrade",
            "content-encoding",
            "content-length",
        ]:
            resp_headers.pop(hop_header, None)

        from sanic import raw as raw_response

        return raw_response(
            response.content,
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


# Blueprint for auth proxy routes
bp = Blueprint("sso", url_prefix="/auth")


@bp.on_request
async def check_sso_enabled(request):
    """Only handle requests if paskia mode is enabled."""
    if config.config.authentication != "paskia":
        from sanic.exceptions import NotFound

        raise NotFound("SSO authentication not enabled")


@bp.route(
    "/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]
)
async def auth_proxy(request, path=""):
    """Proxy all auth requests to the auth backend."""
    return await proxy_auth_request(request)


@bp.route("/", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def auth_proxy_root(request):
    """Proxy root auth requests to the auth backend."""
    return await proxy_auth_request(request)
