import base64
import binascii
import hashlib
import hmac
import secrets
import struct
from pathlib import PurePosixPath
from time import time

import msgspec
from Crypto.Hash import MD4
from html5tagger import Document
from sanic import Blueprint, html, json, redirect
from sanic.exceptions import BadRequest, Forbidden, Unauthorized
from sanic.log import logger

from cista import config, session, sharefs
from cista import sso as _sso_module
from cista.util import pwgen, pwhash
from cista.util.filename import sanitize

_LOGIN_PAGE_CSS = """\
/* ===========================================
   LOGIN PAGE STYLES
   Must match ModalDialog.vue global styles.
   =========================================== */
* { box-sizing: border-box; }
body {
    font-family: 'Roboto', system-ui, -apple-system, sans-serif;
    font-size: 1rem;
    margin: 0;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    background: transparent;
}
.login-card {
    background: #ddd;
    color: #000;
    border-radius: 0.5rem;
    box-shadow: 0 0 1rem #0008;
    width: 100%;
    max-width: 320px;
}
h1 {
    background: #146;
    color: #fff;
    margin: 0;
    padding: 0.5rem 1rem;
    font-size: 1.2rem;
    font-weight: normal;
    border-radius: 0.5rem 0.5rem 0 0;
}
.content {
    padding: 1rem;
}
.message {
    color: #444;
    margin: 0 0 0.5rem 0;
    font-size: 0.875rem;
}
form {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.5rem 1rem;
    align-items: center;
}
label {
    font-size: 1rem;
}
input[type="text"],
input[type="password"] {
    font: inherit;
    font-size: 1rem;
    padding: 0.5rem;
    border: 2px solid #888;
    border-radius: 0.25rem;
    background: #fff;
    color: #000;
    min-width: 0;
}
input:focus {
    outline: none;
    border-color: #f80;
}
.button-row {
    grid-column: 1 / -1;
    display: flex;
    justify-content: flex-end;
    margin-top: 0.5rem;
}
button {
    font: inherit;
    font-size: 1rem;
    padding: 0.5rem 1rem;
    background: #146;
    color: #fff;
    border: none;
    border-radius: 0.25rem;
    cursor: pointer;
}
button:hover { background: #f80; }
button:disabled {
    background: #888;
    cursor: not-allowed;
}
.error {
    grid-column: 1 / -1;
    color: #c00;
    font-size: 0.875rem;
    min-height: 1.2em;
    margin: 0;
}
"""

_LOGIN_PAGE_JS = """\
const form = document.getElementById('loginForm');
const error = document.getElementById('error');
const submitBtn = document.getElementById('submitBtn');
const usernameField = document.getElementById('username');
const passwordField = document.getElementById('password');
const isInIframe = window.parent !== window;

// Focus username field on load
usernameField.focus();

const showError = (msg) => {
    error.textContent = msg;
    submitBtn.disabled = false;
    submitBtn.textContent = 'Log in';
    // Focus and select the relevant field
    if (msg.toLowerCase().includes('password')) {
        passwordField.focus();
        passwordField.select();
    } else {
        usernameField.focus();
        usernameField.select();
    }
};

form.onsubmit = async (e) => {
    e.preventDefault();
    error.textContent = '';
    submitBtn.disabled = true;
    submitBtn.textContent = 'Logging in...';

    try {
        const res = await fetch('/auth/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify({
                username: usernameField.value,
                password: passwordField.value
            })
        });

        if (res.ok) {
            if (isInIframe) {
                window.parent.postMessage({type: 'auth-success'}, '*');
            } else {
                window.location.href = '/';
            }
        } else {
            const data = await res.json();
            showError(data.message || data.detail || 'Login failed');
        }
    } catch (err) {
        showError('Connection error. Please try again.');
    }
};
"""


def _get_sso():
    return _sso_module


def _set_auth_failure_log(request, auth_flow: list[str]) -> None:
    parts = list(auth_flow)
    # Only add request headers that are present and useful for debugging
    for header, label in (
        ("accept", "accept"),
        ("origin", "origin"),
        ("referer", "referer"),
        ("sec-fetch-site", "site"),
        ("sec-fetch-mode", "mode"),
        ("sec-fetch-dest", "dest"),
    ):
        value = request.headers.get(header)
        if value:
            parts.append(f"{label}={value}")
    request.ctx._log_extra = " | ".join(parts)


def hydrate_request_auth_context(request, *, source: str) -> None:
    auth_flow = getattr(request.ctx, "_auth_flow", None)
    if auth_flow is None:
        auth_flow = request.ctx._auth_flow = []

    if hasattr(request.ctx, "session"):
        # Already hydrated by an earlier caller (e.g., use_session middleware)
        return

    request.ctx.session = session.get(request)
    if request.ctx.session is None:
        request.ctx.username = None
        request.ctx.user = None
        auth_flow.append(f"session:{source}(none)")
    elif request.ctx.session is False:
        request.ctx.username = None
        request.ctx.user = None
        auth_flow.append(f"session:{source}(invalid)")
    else:
        try:
            request.ctx.username = request.ctx.session["username"]  # type: ignore[index]
            request.ctx.user = config.config.users[request.ctx.username]
            auth_flow.append(f"session:{source}({request.ctx.username})")
        except (AttributeError, KeyError, TypeError):
            request.ctx.username = None
            request.ctx.user = None
            auth_flow.append(f"session:{source}(bad-jwt)")


_AUTH_REALM = "cista"
_AUTH_CACHE_TTL = 10
_auth_cache: dict[str, tuple[float, config.User]] = {}
_WINDOWS_UA_HINTS = (
    "windows",
    "microsoft-webdav-miniredir",
    "davclnt",
)
_WEBDAV_METHODS = {
    "OPTIONS",
    "PROPFIND",
    "MKCOL",
    "COPY",
    "MOVE",
    "LOCK",
    "UNLOCK",
}
_seen_webdav_uas: set[str] = set()

# NTLM challenge storage: global rolling window of random challenges.
# Challenges are always generated with secrets.token_bytes; no client-IP or
# request-order keying is used so parallel requests do not overwrite state.
_ntlm_challenges: list[tuple[float, bytes]] = []
_NTLM_CHALLENGE_TTL = 30
_NTLM_CHALLENGE_MAX = 64


def _is_windows_auth_client(user_agent: str) -> bool:
    ua = user_agent.casefold()
    return any(marker in ua for marker in _WINDOWS_UA_HINTS)


def _log_webdav_user_agent_once(request, user_agent: str):
    if request.method not in _WEBDAV_METHODS:
        return
    key = (user_agent or "<empty>").strip() or "<empty>"
    if key in _seen_webdav_uas:
        return
    _seen_webdav_uas.add(key)
    # Temporary stdout print so operators can quickly capture real client UAs.


def _build_ua_auth_headers(request, *, include_hint=False) -> dict[str, str]:
    user_agent = request.headers.get("user-agent", "")
    _log_webdav_user_agent_once(request, user_agent)
    if _is_windows_auth_client(user_agent):
        challenge = f'Basic realm="{_AUTH_REALM}", Negotiate'
    else:
        challenge = f'Basic realm="{_AUTH_REALM}"'
    return {"WWW-Authenticate": challenge}


def _cleanup_ntlm_challenges():
    now = time()
    _ntlm_challenges[:] = [
        (ts, challenge)
        for ts, challenge in _ntlm_challenges
        if now - ts <= _NTLM_CHALLENGE_TTL
    ]


def _set_ntlm_challenge(challenge: bytes):
    _cleanup_ntlm_challenges()
    _ntlm_challenges.append((time(), challenge))
    if len(_ntlm_challenges) > _NTLM_CHALLENGE_MAX:
        del _ntlm_challenges[:-_NTLM_CHALLENGE_MAX]


def _get_ntlm_challenges() -> list[bytes]:
    _cleanup_ntlm_challenges()
    # Try newest challenge first; older ones are fallback for request races.
    return [challenge for _, challenge in reversed(_ntlm_challenges)]


def _ntlm_parse_type1(data: bytes) -> dict:
    if len(data) < 16 or data[:7] != b"NTLMSSP" or data[7] != 0:
        return {}
    msg_type = struct.unpack("<I", data[8:12])[0]
    if msg_type != 1:
        return {}
    flags = struct.unpack("<I", data[12:16])[0]
    return {"flags": flags}


def _ntlm_build_type2(
    challenge: bytes, type1_flags: int = 0, target_name: str = "cista"
) -> bytes:
    target = target_name.encode("utf-16le")

    # AV pairs for TargetInfo: NetBIOS + DNS names, terminated by EOL.
    av_pairs = bytearray()
    av_pairs.extend(struct.pack("<HH", 1, len(target)))
    av_pairs.extend(target)
    av_pairs.extend(struct.pack("<HH", 2, len(target)))
    av_pairs.extend(target)
    av_pairs.extend(struct.pack("<HH", 3, len(target)))
    av_pairs.extend(target)
    av_pairs.extend(struct.pack("<HH", 4, len(target)))
    av_pairs.extend(target)
    av_pairs.extend(struct.pack("<HH", 0, 0))
    target_info = bytes(av_pairs)

    # Type 2 fixed header is 48 bytes before payload.
    target_offset = 48
    target_info_offset = target_offset + len(target)

    msg = bytearray()
    msg.extend(b"NTLMSSP\x00")
    msg.extend(struct.pack("<I", 2))  # MESSAGE_TYPE
    # TargetName security buffer
    msg.extend(struct.pack("<HH", len(target), len(target)))
    msg.extend(struct.pack("<I", target_offset))

    # Conservative flag set compatible with Windows NTLMv2 clients.
    flags = (
        0x00000001  # NEGOTIATE_UNICODE
        | 0x00000004  # REQUEST_TARGET
        | 0x00000200  # NEGOTIATE_NTLM
        | 0x00008000  # NEGOTIATE_ALWAYS_SIGN
        | 0x00020000  # TARGET_TYPE_SERVER
        | 0x00080000  # NEGOTIATE_EXTENDED_SESSIONSECURITY
        | 0x00800000  # NEGOTIATE_TARGET_INFO
    )
    # Only advertise 128-bit support when requested by client.
    if type1_flags & 0x20000000:
        flags |= 0x20000000
    msg.extend(struct.pack("<I", flags))

    # Server challenge + reserved
    msg.extend(challenge)
    msg.extend(b"\x00" * 8)

    # TargetInfo security buffer
    msg.extend(struct.pack("<HH", len(target_info), len(target_info)))
    msg.extend(struct.pack("<I", target_info_offset))

    # Payload: TargetName then TargetInfo
    msg.extend(target)
    msg.extend(target_info)
    return bytes(msg)


def _der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _der_tlv(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + _der_len(len(value)) + value


def _spnego_wrap_ntlm_challenge(ntlm_type2: bytes) -> bytes:
    """Wrap an NTLM Type 2 token in SPNEGO NegTokenResp.

    Some Windows clients send SPNEGO-wrapped Negotiate tokens and require
    a SPNEGO-wrapped response token rather than raw NTLMSSP.
    """
    # OID 1.3.6.1.4.1.311.2.2.10 (NTLMSSP)
    ntlm_oid = bytes.fromhex("060a2b06010401823702020a")
    neg_state_accept_incomplete = _der_tlv(0xA0, _der_tlv(0x0A, b"\x01"))
    supported_mech = _der_tlv(0xA1, ntlm_oid)
    response_token = _der_tlv(0xA2, _der_tlv(0x04, ntlm_type2))
    return _der_tlv(
        0xA1,
        _der_tlv(
            0x30,
            neg_state_accept_incomplete + supported_mech + response_token,
        ),
    )


def _ntlm_parse_type3(data: bytes) -> dict | None:
    if len(data) < 64 or data[:7] != b"NTLMSSP" or data[7] != 0:
        return None
    msg_type = struct.unpack("<I", data[8:12])[0]
    if msg_type != 3:
        return None

    def read_buf(offset: int) -> bytes:
        length, _max_len, buf_offset = struct.unpack("<HHI", data[offset : offset + 8])
        if length == 0:
            return b""
        if buf_offset + length > len(data):
            return b""
        return data[buf_offset : buf_offset + length]

    lm_response = read_buf(12)
    nt_response = read_buf(20)
    domain = read_buf(28)
    username = read_buf(36)
    workstation = read_buf(44)

    return {
        "lm_response": lm_response,
        "nt_response": nt_response,
        "domain": domain.decode("utf-16le", errors="ignore"),
        "username": username.decode("utf-16le", errors="ignore"),
        "workstation": workstation.decode("utf-16le", errors="ignore"),
    }


def _ntlmv2_verify(
    token_secret: str,
    username: str,
    domain: str,
    challenge: bytes,
    nt_response: bytes,
) -> bool:
    """Verify an NTLMv2 response using the plaintext token secret as the password."""
    if len(nt_response) < 16:
        return False

    client_proof = nt_response[:16]
    blob = nt_response[16:]

    # NT hash = MD4(UTF-16LE(password))
    nt_hash = MD4.new(token_secret.encode("utf-16le")).digest()  # noqa: S303

    raw_username = username or ""
    raw_domain = domain or ""

    # Windows clients vary in how they populate Username/Domain fields.
    user_candidates: list[str] = []
    domain_candidates: list[str] = []

    def _add_user(value: str):
        if value and value not in user_candidates:
            user_candidates.append(value)

    def _add_domain(value: str):
        if value not in domain_candidates:
            domain_candidates.append(value)

    _add_user(raw_username)
    _add_user(raw_username.upper())
    _add_domain(raw_domain)
    _add_domain(raw_domain.upper())
    _add_domain("")

    if "\\" in raw_username:
        dom_part, user_part = raw_username.split("\\", 1)
        _add_user(user_part)
        _add_user(user_part.upper())
        _add_domain(dom_part)
        _add_domain(dom_part.upper())

    if "@" in raw_username:
        user_part, dom_part = raw_username.split("@", 1)
        _add_user(user_part)
        _add_user(user_part.upper())
        _add_domain(dom_part)
        _add_domain(dom_part.upper())

    for user_candidate in user_candidates:
        for domain_candidate in domain_candidates:
            # NTLMv2 hash = HMAC_MD5(NT_hash, UTF-16LE(username.upper() + domain))
            ntlmv2_hash = hmac.new(
                nt_hash,
                (user_candidate.upper() + domain_candidate).encode("utf-16le"),
                hashlib.md5,
            ).digest()

            # Expected proof = HMAC_MD5(NTLMv2_hash, challenge + blob)
            expected_proof = hmac.new(
                ntlmv2_hash, challenge + blob, hashlib.md5
            ).digest()
            if hmac.compare_digest(client_proof, expected_proof):
                return True

    return False


def _cache_key(username: str, password: str) -> str:
    return hashlib.sha256(f"{username}\x00{password}".encode()).hexdigest()


def login(username: str, password: str):
    normalized_username = pwhash.normalize_secret(username).decode()
    cache_key = _cache_key(username, password)
    cached = _auth_cache.get(cache_key)
    if cached:
        ts, user = cached
        if time() - ts < _AUTH_CACHE_TTL:
            current = config.config.users.get(normalized_username)
            if current and current.hash == user.hash:
                return current
        del _auth_cache[cache_key]

    try:
        u = config.config.users[normalized_username]
    except KeyError:
        raise ValueError("Invalid username") from None
    # Verify password
    need_rehash = pwhash.verify_hash(
        u.hash, username=normalized_username, password=password
    )
    # Login successful
    if need_rehash:
        set_password(u, password)
    now = int(time())
    u.lastSeen = now
    _auth_cache[cache_key] = (now, u)
    return u


def set_password(user: config.User, password: str):
    pwhash.set_password(user, password)
    _auth_cache.clear()


class LoginResponse(msgspec.Struct):
    user: str = ""
    privileged: bool = False
    error: str = ""


def _basic_auth_login(request):
    """Authenticate built-in users from an Authorization: Basic header.

    Supports two credential formats:
      - Basic <username>:<password>   (normal password login)
      - Basic token:<token_secret>    (token-based login)
    """
    auth_header = request.headers.get("authorization")
    if not auth_header:
        return None

    scheme, _, encoded = auth_header.partition(" ")
    if scheme.lower() != "basic":
        return None  # e.g. Negotiate/NTLM — ignore for this auth path
    if not encoded:
        raise Unauthorized("Invalid Authorization header", quiet=True)

    try:
        raw = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as e:
        raise Unauthorized("Invalid Authorization header", quiet=True) from e

    username, sep, password = raw.partition(":")
    if not sep:
        raise Unauthorized("Invalid Authorization header", quiet=True)

    # Token auth: Basic token:<secret>
    if username == "token":
        token = config.config.tokens.get(password)
        if token:
            user = config.config.users.get(token.username)
            if user:
                request.ctx.session = None
                request.ctx.username = token.username
                request.ctx.user = user
                request.ctx.auth_token_id = password
                request.ctx.auth_token = token
                user.lastSeen = int(time())
                return user
        raise Unauthorized("Invalid token", quiet=True)

    # Password auth
    try:
        user = login(username, password)
    except ValueError as e:
        raise Unauthorized(str(e), quiet=True) from e

    request.ctx.session = None
    request.ctx.username = username
    request.ctx.user = user
    return user


async def _token_auth_login(request, *, privileged=False):
    """Authenticate via Basic token:<secret> in SSO mode.

    Returns True if authenticated, False if no token matched.
    Raises Unauthorized/Forbidden on invalid token or insufficient permissions.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header:
        return False

    scheme, _, value = auth_header.partition(" ")
    if scheme.lower() != "basic":
        return False

    try:
        raw = base64.b64decode(value, validate=True).decode("utf-8")
        username, _, password = raw.partition(":")
    except Exception:
        return False

    if username != "token" or not password:
        return False

    token = config.config.tokens.get(password)
    if not token:
        return False

    request.ctx.auth_token_id = password
    request.ctx.auth_token = token

    sso = _get_sso()
    if sso.paskia_enabled() and token.sso_user_id:
        perm = "cista:admin" if privileged else "cista:login"
        try:
            data = await sso.check_permissions(token.sso_user_id, perm)
            request.ctx.sso_user = data
            ctx = data.get("ctx", {}) if isinstance(data, dict) else {}
            user_info = ctx.get("user", {}) if isinstance(ctx, dict) else {}
            request.ctx.username = user_info.get("display_name", "")
        except Forbidden:
            raise
        except Exception:
            return False
        else:
            return True

    if token.username:
        user = config.config.users.get(token.username)
        if not user:
            return False
        if privileged and not user.privileged:
            return False
        request.ctx.session = None
        request.ctx.username = token.username
        request.ctx.user = user
        user.lastSeen = int(time())
        return True

    return False


async def _ntlm_auth_login(request, *, privileged=False):
    """Handle NTLM authentication for token-based login.

    Supports NTLMv2 responses where the token secret is used as the password.
    State is kept in-memory keyed by client IP.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header:
        return None

    scheme, _, encoded = auth_header.partition(" ")
    if scheme.lower() not in ("ntlm", "negotiate"):
        return None

    www_auth_scheme = "Negotiate" if scheme.lower() == "negotiate" else "NTLM"
    client_key = request.client_ip or "unknown"
    spnego_wrapped = False

    try:
        data = base64.b64decode(encoded)
    except Exception as e:
        logger.warning("NTLM decode failed: client=%s", client_key)
        raise Unauthorized("Invalid NTLM message", www_auth_scheme, quiet=True) from e

    # Windows commonly sends SPNEGO-wrapped Negotiate tokens that embed NTLMSSP.
    # Extract the NTLMSSP blob when present so downstream parsing sees raw Type 1/3.
    marker = b"NTLMSSP\x00"
    marker_pos = data.find(marker)
    if marker_pos == 0:
        pass
    elif marker_pos > 0:
        spnego_wrapped = True
        data = data[marker_pos:]
    else:
        logger.warning("NTLM token missing NTLMSSP marker: client=%s", client_key)

    if len(data) < 12:
        logger.warning(
            "NTLM message too short: client=%s bytes=%d", client_key, len(data)
        )
        raise Unauthorized("Invalid NTLM message", www_auth_scheme, quiet=True)

    msg_type = struct.unpack("<I", data[8:12])[0]

    if msg_type == 1:
        type1 = _ntlm_parse_type1(data)
        if not type1:
            raise Unauthorized("Invalid NTLM Type 1", www_auth_scheme, quiet=True)
        challenge = secrets.token_bytes(8)
        _set_ntlm_challenge(challenge)
        type2_msg = _ntlm_build_type2(challenge, type1.get("flags", 0))
        response_token = type2_msg
        response_format = "raw-ntlm"
        if scheme.lower() == "negotiate" and spnego_wrapped:
            response_token = _spnego_wrap_ntlm_challenge(type2_msg)
            response_format = "spnego-negTokenResp"
        type2_header = f"{www_auth_scheme} {base64.b64encode(response_token).decode()}"
        logger.debug(
            "NTLM Type 1 from %s (flags=0x%08x), sending challenge format=%s",
            client_key,
            type1.get("flags", 0),
            response_format,
        )
        www_auth_scheme = "Negotiate" if scheme.lower() == "negotiate" else "NTLM"
        raise Unauthorized(
            "NTLM authentication required",
            headers={"WWW-Authenticate": type2_header},
            quiet=True,
        )

    if msg_type == 3:
        challenges = _get_ntlm_challenges()
        if not challenges:
            logger.warning("NTLM Type 3 from %s with no matching challenge", client_key)
            www_auth_scheme = "Negotiate" if scheme.lower() == "negotiate" else "NTLM"
            raise Unauthorized("NTLM challenge expired", www_auth_scheme, quiet=True)

        type3 = _ntlm_parse_type3(data)
        if not type3:
            logger.warning("NTLM Type 3 parse failed from %s", client_key)
            www_auth_scheme = "Negotiate" if scheme.lower() == "negotiate" else "NTLM"
            raise Unauthorized("Invalid NTLM Type 3", www_auth_scheme, quiet=True)

        username = type3["username"]
        domain = type3["domain"]
        nt_response = type3["nt_response"]

        logger.debug(
            "NTLM Type 3 from %s, user=%s, domain=%s, nt_len=%d",
            client_key,
            username,
            domain,
            len(nt_response),
        )
        if username.casefold() != "token":
            logger.warning(
                "NTLM username '%s' from %s is not 'token'; this is likely Windows account auth and will fail in Cista token mode",
                username,
                client_key,
            )

        tokens = config.config.tokens
        if not tokens:
            logger.warning("NTLM verification has no configured tokens")

        for tid, token in tokens.items():
            secret_candidates: list[tuple[str, str]] = []
            if tid:
                secret_candidates.append(("token-id", tid))
            if token.key and token.key != tid:
                secret_candidates.append(("token-key", token.key))

            matched_by = None
            for secret_kind, secret_value in secret_candidates:
                for challenge in challenges:
                    if _ntlmv2_verify(
                        secret_value,
                        username,
                        domain,
                        challenge,
                        nt_response,
                    ):
                        matched_by = secret_kind
                        break
                if matched_by:
                    break

            if matched_by:
                logger.debug(
                    "NTLM proof matched token=%s via %s",
                    tid[:8],
                    matched_by,
                )
                sso = _get_sso()
                if sso.paskia_enabled() and token.sso_user_id:
                    perm = "cista:admin" if privileged else "cista:login"
                    try:
                        data = await sso.check_permissions(token.sso_user_id, perm)
                        request.ctx.sso_user = data
                        request.ctx.auth_token_id = tid
                        request.ctx.auth_token = token
                        ctx = data.get("ctx", {}) if isinstance(data, dict) else {}
                        user_info = ctx.get("user", {}) if isinstance(ctx, dict) else {}
                        request.ctx.username = user_info.get("display_name", "")
                        logger.debug(
                            "NTLM auth success for SSO user %s (token=%s...)",
                            token.sso_user_id,
                            tid[:8],
                        )
                    except Forbidden:
                        raise
                    except Exception as e:
                        logger.warning("NTLM SSO check failed: %s", e)
                        continue
                    else:
                        return True

                if token.username:
                    user = config.config.users.get(token.username)
                    if user:
                        if privileged and not user.privileged:
                            logger.warning(
                                "NTLM auth denied: token user %s is not privileged",
                                token.username,
                            )
                            raise Forbidden(
                                "Access Forbidden: Only for privileged users",
                                quiet=True,
                            )
                        user.lastSeen = int(time())
                        request.ctx.session = None
                        request.ctx.username = token.username
                        request.ctx.user = user
                        request.ctx.auth_token_id = tid
                        request.ctx.auth_token = token
                        request.ctx._create_session_username = token.username
                        logger.debug(
                            "NTLM auth success for local user %s (token=%s...)",
                            token.username,
                            tid[:8],
                        )
                        return user

        logger.warning("NTLM auth failed from %s, user=%s", client_key, username)
        raise Unauthorized("Invalid NTLM credentials", www_auth_scheme, quiet=True)

    logger.warning(
        "NTLM invalid message type from %s: msg_type=%s",
        client_key,
        msg_type,
    )
    raise Unauthorized("Invalid NTLM message type", www_auth_scheme, quiet=True)


async def verify(request, *, privileged=False):
    """Verify that the request is authorized.

    For paskia mode (PASKIA_BACKEND_URL set), validates against the SSO backend.
    For built-in mode, checks session-based authentication.
    For public mode (config.public=True), skips auth unless privileged is required.

    If an Authorization header is present, Authorization-based auth is used.
    For NTLM/Negotiate specifically, an already valid session is accepted to
    avoid re-running a full handshake on every request.

    Args:
        request: The Sanic request object
        privileged: If True, requires admin privileges (always enforced even in public mode)

    Raises:
        Unauthorized: If authentication is required
        Forbidden: If access is denied
    """
    hydrate_request_auth_context(request, source="auth.verify")

    # Public mode: skip auth unless privileged access is required
    if config.config.public and not privileged:
        return

    auth_header = request.headers.get("authorization", "")
    has_auth_header = bool(auth_header)
    scheme = auth_header.split()[0].lower() if has_auth_header else None

    # Concise auth flow for diagnostics (populated by use_session + verify)
    auth_flow = list(getattr(request.ctx, "_auth_flow", ["session:skipped"]))
    tried: list[str] = []

    sso = _get_sso()
    if sso.paskia_enabled():
        tried.append("token")
        if await _token_auth_login(request, privileged=privileged):
            return
        if has_auth_header:
            tried.append("sso")
            try:
                perm = "cista:admin" if privileged else "cista:login"
                await sso.validate_sso_request(request, perm=perm)
            except Unauthorized as e:
                auth_flow.append(f"tried={','.join(tried)} result=failed")
                _set_auth_failure_log(request, auth_flow)
                raise Unauthorized(
                    "Invalid credentials",
                    headers=_build_ua_auth_headers(request),
                    quiet=True,
                ) from e
            else:
                return
        tried.append("sso")
        perm = "cista:admin" if privileged else "cista:login"
        await sso.validate_sso_request(request, perm=perm)
        return

    # Built-in mode
    if has_auth_header:
        ntlm_failed = False
        if scheme in ("ntlm", "negotiate"):
            # Reuse established session to avoid NTLM 401 handshake on every request.
            user = getattr(request.ctx, "user", None)
            if user is not None:
                if privileged and not user.privileged:
                    auth_flow.append("tried=session result=priv")
                    _set_auth_failure_log(request, auth_flow)
                    raise Forbidden(
                        "Access Forbidden: Only for privileged users",
                        quiet=True,
                    )
                return
        if scheme == "basic":
            tried.append("basic")
            try:
                user = _basic_auth_login(request)
            except Unauthorized:
                user = None
            else:
                if user is not None:
                    if privileged and not user.privileged:
                        auth_flow.append(f"tried={','.join(tried)} result=priv")
                        _set_auth_failure_log(request, auth_flow)
                        raise Forbidden(
                            "Access Forbidden: Only for privileged users",
                            quiet=True,
                        )
                    return
        elif scheme in ("ntlm", "negotiate"):
            tried.append("ntlm")
            try:
                user = await _ntlm_auth_login(request, privileged=privileged)
            except Unauthorized as e:
                auth_hdr = (e.headers or {}).get("WWW-Authenticate", "")
                if (
                    auth_hdr.startswith(("NTLM ", "Negotiate "))
                ) and "realm=" not in auth_hdr:
                    raise
                ntlm_failed = True
                user = None
            else:
                if user is not None:
                    if getattr(request.ctx, "_create_session_username", None) is None:
                        username = getattr(request.ctx, "username", None)
                        if username:
                            request.ctx._create_session_username = username
                    return
        # Auth header present but invalid → try session fallback
        tried.append("session")
        user = getattr(request.ctx, "user", None)
        if user:
            if privileged and not user.privileged:
                auth_flow.append(f"tried={','.join(tried)} result=priv")
                _set_auth_failure_log(request, auth_flow)
                raise Forbidden(
                    "Access Forbidden: Only for privileged users",
                    quiet=True,
                )
            return
        auth_flow.append(f"tried={','.join(tried)} result=failed")
        _set_auth_failure_log(request, auth_flow)
        if scheme in ("ntlm", "negotiate") and ntlm_failed:
            challenge_scheme = "Negotiate" if scheme == "negotiate" else "NTLM"
            logger.warning(
                "NTLM login rejected for client=%s; advertising %s fallback",
                request.client_ip or "unknown",
                challenge_scheme,
            )
            raise Unauthorized(
                "Invalid NTLM credentials. Use username 'token' and token secret as password.",
                headers=_build_ua_auth_headers(request, include_hint=True),
                quiet=True,
            )
        raise Unauthorized(
            "Invalid credentials",
            headers=_build_ua_auth_headers(request),
            quiet=True,
        )

    # No auth header: try session cookie
    tried.append("session")
    user = getattr(request.ctx, "user", None)

    if privileged:
        if user and user.privileged:
            return
        auth_flow.append(f"tried={','.join(tried)} result=priv")
        _set_auth_failure_log(request, auth_flow)
        raise Forbidden(
            "Access Forbidden: Only for privileged users",
            quiet=True,
        )
    if user or request.method == "OPTIONS":
        return
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        auth_flow.append(f"tried={','.join(tried)} result=none(browser)")
        _set_auth_failure_log(request, auth_flow)
        raise Unauthorized(
            f"Login required for {request.path}",
            "cookie",
            context={"auth": {"iframe": "/auth/restricted/"}},
            quiet=True,
        )
    auth_flow.append(f"tried={','.join(tried)} result=none")
    _set_auth_failure_log(request, auth_flow)
    headers = _build_ua_auth_headers(request, include_hint=True)
    raise Unauthorized(
        f"Login required for {request.path}",
        headers=headers,
        quiet=True,
        context={"auth": {"iframe": "/auth/restricted/"}},
    )


# Blueprint for built-in auth (only registered when paskia is NOT enabled)
bp = Blueprint("auth", url_prefix="/auth")


@bp.get("/restricted/")
async def login_page(request):
    """Login page that works both standalone and in paskia iframe."""
    s = session.get(request)

    # Check if already logged in
    if s:
        # Already authenticated - signal success if in iframe
        return html(_login_success_page(s["username"]))

    doc = Document("Cista - Login")
    # Add paskia-compatible styling and scripts
    doc.style(_LOGIN_PAGE_CSS)
    with doc.div(class_="login-card"):
        doc.h1("Authentication Required")
        with (
            doc.div(class_="content"),
            doc.form(method="POST", id="loginForm", autocomplete="on"),
        ):
            doc.label("Username:", for_="username")
            doc.input(
                type="text",
                id="username",
                name="username",
                autocomplete="username webauthn",
                required=True,
            )
            doc.label("Password:", for_="password")
            doc.input(
                type="password",
                id="password",
                name="password",
                autocomplete="current-password webauthn",
                required=True,
            )
            with doc.div(class_="button-row"):
                doc.button("Log in", type="submit", id="submitBtn")
            doc.p("", class_="error", id="error")

    # JavaScript for AJAX login and postMessage communication
    doc.script_(_LOGIN_PAGE_JS)

    res = html(doc)
    if s is False:
        session.delete(request, res)
    return res


def _login_success_page(username: str) -> str:
    """Minimal page that signals auth-success to parent iframe."""
    return str(
        Document().script_("window.parent.postMessage({type:'auth-success'},'*')")
    )


@bp.post("/login")
async def login_post(request):
    try:
        if request.headers.content_type == "application/json":
            username = request.json["username"]
            password = request.json["password"]
        else:
            username = request.form["username"][0]
            password = request.form["password"][0]
        if not username or not password:
            raise KeyError
    except KeyError:
        raise BadRequest(
            "Missing username or password",
            context={"redirect": "/login"},
        ) from None
    try:
        user = login(username, password)
    except ValueError as e:
        raise Forbidden(str(e), context={"redirect": "/login"}) from e

    if "text/html" in request.headers.accept:
        res = redirect("/")
        session.flash(res, "Logged in")
    else:
        res = json({"data": {"username": username, "privileged": user.privileged}})
    session.create(request, res, username)
    return res


@bp.post("/api/logout")
async def logout_post(request):
    s = request.ctx.session
    msg = "Logged out" if s else "Not logged in"
    if "text/html" in request.headers.accept:
        res = redirect("/login")
        res.cookies.add_cookie("flash", msg, max_age=5)
    else:
        res = json({"message": msg})
    session.delete(request, res)
    return res


@bp.post("/password-change")
async def change_password(request):
    try:
        if request.headers.content_type == "application/json":
            username = request.json["username"]
            pwchange = request.json["passwordChange"]
            password = request.json["password"]
        else:
            username = request.form["username"][0]
            pwchange = request.form["passwordChange"][0]
            password = request.form["password"][0]
        if not username or not password:
            raise KeyError
    except KeyError:
        raise BadRequest(
            "Missing username, passwordChange or password",
        ) from None
    try:
        user = login(username, password)
        set_password(user, pwchange)
    except ValueError as e:
        raise Forbidden(str(e), context={"redirect": "/login"}) from e

    if "text/html" in request.headers.accept:
        res = redirect("/")
        session.flash(res, "Password updated")
    else:
        res = json({"message": "Password updated"})
    session.create(request, res, username)
    return res


@bp.get("/users")
async def list_users(request):
    await verify(request, privileged=True)
    users = []
    for name, user in config.config.users.items():
        users.append(
            {
                "username": name,
                "privileged": user.privileged,
                "lastSeen": user.lastSeen,
            }
        )
    return json({"users": users})


@bp.post("/users")
async def create_user(request):
    await verify(request, privileged=True)
    try:
        if request.headers.content_type == "application/json":
            username = request.json["username"]
            password = request.json.get("password")
            privileged = request.json.get("privileged", False)
        else:
            username = request.form["username"][0]
            password = request.form.get("password", [None])[0]
            privileged = request.form.get("privileged", ["false"])[0].lower() == "true"
        if not username or not username.isidentifier():
            raise ValueError("Invalid username")
    except (KeyError, ValueError) as e:
        raise BadRequest(str(e)) from e
    if username in config.config.users:
        raise BadRequest("User already exists")
    if not password:
        password = pwgen.generate()
    changes = {"privileged": privileged, "password": password}
    try:
        config.update_user(username, changes)
    except Exception as e:
        raise BadRequest(str(e)) from e
    return json({"message": f"User {username} created", "password": password})


@bp.put("/users/<username>")
async def update_user(request, username):
    await verify(request, privileged=True)
    try:
        if request.headers.content_type == "application/json":
            changes = request.json
        else:
            changes = {}
            if "password" in request.form:
                changes["password"] = request.form["password"][0]
            if "privileged" in request.form:
                changes["privileged"] = request.form["privileged"][0].lower() == "true"
    except KeyError as e:
        raise BadRequest("Missing fields") from e
    password_response = None
    if "password" in changes:
        if changes["password"] == "":
            changes["password"] = pwgen.generate()
        password_response = changes["password"]
    if not changes:
        return json({"message": "No changes"})
    try:
        config.update_user(username, changes)
    except Exception as e:
        raise BadRequest(str(e)) from e
    response = {"message": f"User {username} updated"}
    if password_response:
        response["password"] = password_response
    return json(response)


@bp.delete("/users/<username>")
async def delete_user(request, username):
    await verify(request, privileged=True)
    if username not in config.config.users:
        raise BadRequest("User does not exist")
    try:
        config.del_user(username)
    except Exception as e:
        raise BadRequest(str(e)) from e
    return json({"message": f"User {username} deleted"})


def _current_user_id(request):
    """Return (username, sso_user_id) for the currently authenticated user."""
    user = getattr(request.ctx, "user", None)
    if user is not None:
        return (getattr(request.ctx, "username", None), None)
    sso_user = getattr(request.ctx, "sso_user", None)
    if isinstance(sso_user, dict):
        ctx = sso_user.get("ctx", {}) if isinstance(sso_user, dict) else {}
        user_info = ctx.get("user", {}) if isinstance(ctx, dict) else {}
        sso_user_id = (
            user_info.get("id") or user_info.get("uuid") or user_info.get("sub")
        )
        return (None, sso_user_id)
    return (None, None)


def _token_belongs_to_user(token, username, sso_user_id):
    """Check if a token belongs to the given user."""
    if username is not None and token.username == username:
        return True
    return bool(sso_user_id is not None and token.sso_user_id == sso_user_id)


def request_token(request) -> config.Token | None:
    token = getattr(request.ctx, "auth_token", None)
    return token if isinstance(token, config.Token) else None


def request_share_token(request) -> config.Token | None:
    token = request_token(request)
    if token is None:
        return None
    return token if sharefs.is_share_token(token) else None


def ensure_write_allowed(request) -> None:
    token = request_share_token(request)
    if token is None:
        return
    if token.mode != "rw":
        raise Forbidden("Share token is read-only", quiet=True)


# Token management handlers (shared between /auth and /api blueprints)


async def list_tokens_handler(request):
    await verify(request)
    username, sso_user_id = _current_user_id(request)
    tokens = []
    for tid, t in config.config.tokens.items():
        if _token_belongs_to_user(t, username, sso_user_id):
            tokens.append(
                {
                    "id": tid,
                    "username": t.username,
                    "sso_user_id": t.sso_user_id,
                    "name": t.name,
                    "created": t.created,
                    "kind": t.kind,
                    "mode": t.mode,
                }
            )
    return json({"tokens": tokens})


async def create_token_handler(request):
    await verify(request)
    current_username, current_sso_user_id = _current_user_id(request)
    try:
        if request.headers.content_type == "application/json":
            username = request.json.get("username")
            sso_user_id = request.json.get("sso_user_id")
            name = request.json.get("name", "")
        else:
            username = request.form.get("username", [None])[0]
            sso_user_id = request.form.get("sso_user_id", [None])[0]
            name = request.form.get("name", [""])[0]
    except (KeyError, IndexError):
        raise BadRequest("Missing fields") from None

    sso = _get_sso()
    if sso.paskia_enabled():
        if sso_user_id:
            # Non-admin cannot create tokens for other users
            if sso_user_id != current_sso_user_id:
                raise Forbidden("Cannot create tokens for other users", quiet=True)
        else:
            sso_user_id = current_sso_user_id
        if not sso_user_id:
            raise BadRequest("Could not determine SSO user")
    else:
        if username:
            if username != current_username:
                raise Forbidden("Cannot create tokens for other users", quiet=True)
        else:
            username = current_username
        if not username:
            raise BadRequest("Could not determine user")
        if username not in config.config.users:
            raise BadRequest("User does not exist")

    token = secrets.token_urlsafe(8)
    changes = {
        "key": token,
        "username": username or "",
        "sso_user_id": sso_user_id or "",
        "name": name,
        "created": int(time()),
        "kind": "api",
        "mode": "rw",
        "share_paths": [],
    }
    config.update_token(token, changes)
    scheme = request.scheme
    host = request.host or "localhost"
    token_url = f"{scheme}://token:{token}@{host}/"
    return json(
        {
            "id": token,
            "key": token,
            "url": token_url,
            "username": username or "",
            "sso_user_id": sso_user_id or "",
            "name": name,
            "kind": "api",
            "mode": "rw",
        }
    )


async def create_share_token_handler(request):
    await verify(request)
    current_username, current_sso_user_id = _current_user_id(request)
    try:
        if request.headers.content_type == "application/json":
            paths = request.json.get("paths")
            mode = request.json.get("mode", "ro")
            name = request.json.get("name", "")
        else:
            paths = request.form.get("paths", [])
            mode = request.form.get("mode", ["ro"])[0]
            name = request.form.get("name", [""])[0]
    except (KeyError, IndexError):
        raise BadRequest("Missing fields") from None

    if not isinstance(paths, list) or not paths:
        raise BadRequest("paths must be a non-empty array")
    if mode not in ("ro", "rw"):
        raise BadRequest("mode must be ro or rw")

    clean_paths: list[str] = []
    seen: set[str] = set()
    base = config.config.path.resolve()
    for raw_path in paths:
        if not isinstance(raw_path, str):
            raise BadRequest("paths must contain strings")
        try:
            clean = sanitize(raw_path)
        except ValueError as e:
            raise BadRequest(f"Invalid path: {e}") from e
        if not clean:
            continue
        rel = PurePosixPath(clean)
        resolved = (base / rel).resolve()
        if not resolved.is_relative_to(base):
            raise BadRequest("Invalid path")
        if not resolved.exists():
            raise BadRequest(f"Path does not exist: {clean}")
        key = rel.as_posix()
        if key in seen:
            continue
        seen.add(key)
        clean_paths.append(key)

    if not clean_paths:
        raise BadRequest("No valid paths selected")

    sso = _get_sso()
    username = ""
    sso_user_id = ""
    if sso.paskia_enabled():
        sso_user_id = current_sso_user_id or ""
        if not sso_user_id:
            raise BadRequest("Could not determine SSO user")
    else:
        username = current_username or ""
        if not username:
            raise BadRequest("Could not determine user")
        if username not in config.config.users:
            raise BadRequest("User does not exist")

    token = secrets.token_urlsafe(12)
    changes = {
        "key": token,
        "username": username,
        "sso_user_id": sso_user_id,
        "name": name,
        "created": int(time()),
        "kind": "share",
        "mode": mode,
        "share_paths": clean_paths,
    }
    config.update_token(token, changes)

    scheme = request.scheme
    host = request.host or "localhost"
    share_url = f"{scheme}://token:{token}@{host}/#/"
    return json(
        {
            "id": token,
            "key": token,
            "url": share_url,
            "username": username,
            "sso_user_id": sso_user_id,
            "name": name,
            "kind": "share",
            "mode": mode,
            "paths": clean_paths,
        }
    )


async def delete_token_handler(request, token_id):
    await verify(request)
    if token_id not in config.config.tokens:
        raise BadRequest("Token does not exist")
    token = config.config.tokens[token_id]
    username, sso_user_id = _current_user_id(request)
    if not _token_belongs_to_user(token, username, sso_user_id):
        raise Forbidden("Cannot delete tokens belonging to other users", quiet=True)
    config.del_token(token_id)
    return json({"message": f"Token {token_id} deleted"})


# Register on auth blueprint (built-in mode)
@bp.get("/tokens")
async def list_tokens(request):
    return await list_tokens_handler(request)


@bp.post("/tokens")
async def create_token(request):
    return await create_token_handler(request)


@bp.delete("/tokens/<token_id>")
async def delete_token(request, token_id):
    return await delete_token_handler(request, token_id)
