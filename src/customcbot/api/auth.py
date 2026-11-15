"""Optional password protection.

Off by default: the app listens on this computer only. A password matters
when it is opened to other devices (`--host 0.0.0.0`). It can be set in
Settings, or with `CUSTOMCBOT_PASSWORD`, which then cannot be changed in the app.

Signing in sets a cookie. Its value is derived from the password, so changing
the password signs every device out.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from .. import config
from ..exceptions import InvalidInputError

COOKIE = "customcbot_session"
MIN_LENGTH = 6
_ROUNDS = 200_000


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), _ROUNDS).hex()


def from_environment() -> str | None:
    return os.environ.get("CUSTOMCBOT_PASSWORD") or None


def required() -> bool:
    return bool(from_environment() or config.get("password_hash"))


def matches(password: str) -> bool:
    fixed = from_environment()
    if fixed:
        return hmac.compare_digest(password.encode("utf-8"), fixed.encode("utf-8"))
    stored = config.get("password_hash")
    if not stored:
        return True
    salt, digest = stored.split(":", 1)
    return hmac.compare_digest(_hash(password, salt), digest)


def session_token() -> str:
    """What the sign-in cookie must hold right now."""
    secret = from_environment() or config.get("password_hash") or ""
    return hmac.new(config.session_secret(), secret.encode("utf-8"), hashlib.sha256).hexdigest()


def signed_in(cookie: str | None) -> bool:
    return not required() or bool(cookie and hmac.compare_digest(cookie, session_token()))


def set_password(new: str) -> None:
    """Set, change or (with an empty value) remove the password saved in Settings."""
    if from_environment():
        raise InvalidInputError("The password is set where the app is started and cannot be changed here.")
    if not new:
        config.set_many({"password_hash": None})
        return
    if len(new) < MIN_LENGTH:
        raise InvalidInputError(f"Use at least {MIN_LENGTH} characters.")
    salt = secrets.token_hex(16)
    config.set_many({"password_hash": f"{salt}:{_hash(new, salt)}"})
