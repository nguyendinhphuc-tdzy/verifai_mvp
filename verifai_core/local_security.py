"""Deny remote use while VerifAI has no authentication or authorization.

This is a LOCAL-ONLY safety gate, not a replacement for real production
authentication. Do not deploy or expose the app publicly before that work.
"""
from __future__ import annotations
import base64
import hmac
import ipaddress
import os
from urllib.parse import urlsplit
from fastapi import Request
from fastapi.responses import JSONResponse


_MUTATING = {'POST', 'PUT', 'PATCH', 'DELETE'}


def _loopback(value: str) -> bool:
    if value == 'localhost':
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except (ValueError, TypeError):
        return False


def _same_origin(request: Request, origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
        destination = request.url
        return (
            parsed.scheme == destination.scheme and
            parsed.hostname == destination.hostname and
            parsed.port == destination.port and
            parsed.username is None and parsed.password is None and
            parsed.path in ('', '/') and
            not parsed.query and not parsed.fragment
        )
    except ValueError:
        return False


def public_access_code() -> str | None:
    """Shared access code for the opt-in public demo mode (None = local only).

    VERIFAI_PUBLIC_MODE=1 without a code of >= 8 characters stays local-only
    (fail closed). This is a single shared secret for a capstone demo, not
    per-user authentication.
    """
    if os.environ.get('VERIFAI_PUBLIC_MODE') != '1':
        return None
    code = os.environ.get('VERIFAI_ACCESS_CODE', '')
    return code if len(code) >= 8 else None


def _authorized(request: Request, code: str) -> bool:
    header = request.headers.get('authorization', '')
    if not header.lower().startswith('basic '):
        return False
    try:
        _, _, password = base64.b64decode(header[6:]).decode('utf-8').partition(':')
    except (ValueError, UnicodeDecodeError):
        return False
    return hmac.compare_digest(password.encode('utf-8'), code.encode('utf-8'))


def validate_request(request: Request) -> str | None:
    """Return a denial reason; None means the request is permitted."""
    peer = request.client.host if request.client else ''
    host = request.url.hostname or ''
    # Starlette's TestClient uses an in-process synthetic client/host.
    internal_test = peer == 'testclient' and host == 'testserver'
    local = internal_test or (_loopback(peer) and _loopback(host))
    if not local:
        code = public_access_code()
        if code is None:
            return 'VerifAI requires localhost; network access is disabled until authentication is implemented'
        if request.url.path != '/healthz' and not _authorized(request, code):
            return 'AUTH'
    if request.method in _MUTATING:
        origin = request.headers.get('origin')
        if origin is not None and not _same_origin(request, origin):
            return 'Cross-origin data modification is forbidden'
        if request.headers.get('sec-fetch-site', '').lower() in ('cross-site', 'same-site'):
            return 'Cross-site data modification is forbidden'
    return None


async def local_only_middleware(request: Request, call_next):
    denial = validate_request(request)
    if denial == 'AUTH':
        response = JSONResponse({'detail': 'Cần mã truy cập'}, status_code=401,
                                headers={'WWW-Authenticate': 'Basic realm="VerifAI", charset="UTF-8"'})
    elif denial:
        response = JSONResponse({'detail': denial}, status_code=403)
    else:
        response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response
