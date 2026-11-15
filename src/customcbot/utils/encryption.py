"""Keeps saved API keys unreadable in the database file.

The key used to lock them is `CUSTOMCBOT_ENCRYPTION_KEY` if set, otherwise a
random one kept in `secret.key` in the data folder. This protects a copy or
backup of the database on its own. It does not protect against someone who has
the whole data folder, because the lock and its key are then both in hand.
"""

from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .. import config

PREFIX = "enc:v1:"


@lru_cache(maxsize=8)
def _file_key(path: str) -> bytes:
    target = Path(path)
    if not target.exists():
        # Created so that only this user can read it, where the system supports that.
        handle = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(handle, "wb") as out:
            out.write(Fernet.generate_key())
    return target.read_bytes().strip()


def _fernet() -> Fernet:
    phrase = os.environ.get("CUSTOMCBOT_ENCRYPTION_KEY")
    if phrase:
        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(phrase.encode("utf-8")).digest()))
    return Fernet(_file_key(str(config.data_dir() / "secret.key")))


def encrypt(text: str) -> str:
    return PREFIX + _fernet().encrypt(text.encode("utf-8")).decode("ascii")


def decrypt(stored: str | None) -> str | None:
    """The original text, or None if it cannot be unlocked (the key file was lost or changed)."""
    if not stored:
        return None
    if not stored.startswith(PREFIX):
        return stored  # saved before keys were encrypted
    try:
        return _fernet().decrypt(stored[len(PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken:
        return None
