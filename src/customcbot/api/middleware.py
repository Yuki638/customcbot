"""Checks that every request passes through before it reaches a route."""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse


async def same_origin_only(request: Request, call_next):
    """Refuse requests that another website makes from the user's browser.

    The app has no login, so without this any page the user visits could read
    or change their collections on this local server.
    """
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.headers.get("host"):
        return JSONResponse({"detail": "Cross-site requests are not allowed."}, status_code=403)
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response
