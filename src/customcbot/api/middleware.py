"""Checks that every request passes through before it reaches a route."""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse

from . import auth


async def password_required(request: Request, call_next):
    """With a password set, the data routes answer only to a signed-in browser.

    The pages themselves stay reachable, so the sign-in form can load.
    """
    path = request.url.path
    if path.startswith("/api/") and not path.startswith("/api/auth/"):
        if not auth.signed_in(request.cookies.get(auth.COOKIE)):
            return JSONResponse({"detail": "Sign in first."}, status_code=401)
    return await call_next(request)


async def same_origin_only(request: Request, call_next):
    """Refuse requests that another website makes from the user's browser.

    Without this, any page the user visits could read or change their
    collections on this local server.
    """
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.headers.get("host"):
        return JSONResponse({"detail": "Cross-site requests are not allowed."}, status_code=403)
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response
