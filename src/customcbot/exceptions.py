"""Errors the app raises on purpose. Their message is shown to the user as written.

Routes and domain models raise these; `api/main.py` turns each into a reply
with the matching status code, so no route builds error replies by hand.
"""

from __future__ import annotations


class CustomcbotError(Exception):
    status_code = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(CustomcbotError):
    """The thing asked for does not exist (any more)."""

    status_code = 404


class InvalidInputError(CustomcbotError):
    """The request cannot be carried out as given."""

    status_code = 400


class ConflictError(CustomcbotError):
    """The request clashes with something that is already running."""

    status_code = 409


class ConfigurationError(CustomcbotError):
    """Something has to be set up first, such as a model."""

    status_code = 422
