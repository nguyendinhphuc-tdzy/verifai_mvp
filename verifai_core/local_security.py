"""Deny remote use while VerifAI has no authentication or authorization.

This is a LOCAL-ONLY safety gate, not a replacement for real production
authentication. Do not deploy or expose the app publicly before that work.
"""
from __future__ import annotations
import ipaddress
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


def validate_request(request: Request) -> str | None:
    """Return a denial reason; None means the local request is permitted."""
    peer = request.client.host if request.client else ''
    host = request.url.hostname or ''
    # Starlette's TestClient uses an in-process synthetic client/host.
    internal_test = peer == 'testclient' and host == 'testserver'
    if not internal_test and not (_loopback(peer) and _loopback(host)):
        return 'VerifAI requires localhost; network access is disabled until authentication is implemented'
    if request.method in _MUTATING:
        origin = request.headers.get('origin')
        if origin is not None and not _same_origin(request, origin):
            return 'Cross-origin data modification is forbidden'
        if request.headers.get('sec-fetch-site', '').lower() in ('cross-site', 'same-site'):
            return 'Cross-site data modification is forbidden'
    return None


async def local_only_middleware(request: Request, call_next):
    denial = validate_request(request)
    if denial:
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
