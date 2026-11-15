"""The list of background commands, filled by the `@command` decorator.

A command is slow work that runs on the worker instead of inside a web request:
reading a source, writing a quiz. A route submits it by name and returns at once;
the browser then asks for the job's progress.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..services import Services
    from .worker import JobContext

Handler = Callable[[dict, dict, "Services", "JobContext"], "dict | None"]


@dataclass(frozen=True)
class Command:
    name: str
    run: Handler
    max_attempts: int = 1  # 1 means no retry
    wait_seconds: float = 0.0  # pause between attempts
    stop_on: tuple[type[BaseException], ...] = ()  # errors that a retry cannot fix


_commands: dict[str, Command] = {}


def command(
    name: str,
    *,
    max_attempts: int = 1,
    wait_seconds: float = 0.0,
    stop_on: tuple[type[BaseException], ...] = (),
) -> Callable[[Handler], Handler]:
    """Register a function as the background command `name`."""

    def register(handler: Handler) -> Handler:
        _commands[name] = Command(name, handler, max_attempts, wait_seconds, stop_on)
        return handler

    return register


def get_command(name: str) -> Command | None:
    return _commands.get(name)


def command_names() -> list[str]:
    return sorted(_commands)
