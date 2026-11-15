"""What every stored object has in common: load, save, update, delete.

`ObjectModel` is one row in a table. `RecordModel` is a single record of
settings that exists once, such as the default models.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel, ConfigDict

from ..database.repository import repo_execute, repo_one, repo_query
from ..exceptions import NotFoundError

T = TypeVar("T", bound="ObjectModel")
R = TypeVar("R", bound="RecordModel")


class ObjectModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    table_name: ClassVar[str] = ""
    missing_message: ClassVar[str] = "That item no longer exists."

    id: int | None = None
    created_at: str | None = None

    @classmethod
    def get(cls: type[T], record_id: int) -> T:
        row = repo_one(f"SELECT * FROM {cls.table_name} WHERE id = ?", (record_id,))
        if row is None:
            raise NotFoundError(cls.missing_message)
        return cls(**row)

    @classmethod
    def find(cls: type[T], record_id: int) -> T | None:
        row = repo_one(f"SELECT * FROM {cls.table_name} WHERE id = ?", (record_id,))
        return cls(**row) if row is not None else None

    @classmethod
    def where(cls: type[T], clause: str = "1 = 1", params: tuple = (), order_by: str = "id") -> list[T]:
        rows = repo_query(f"SELECT * FROM {cls.table_name} WHERE {clause} ORDER BY {order_by}", params)
        return [cls(**row) for row in rows]

    def _columns(self) -> dict[str, Any]:
        return self.model_dump(exclude={"id", "created_at"})

    def save(self: T) -> T:
        """Insert the object, or write all its fields if it is already stored."""
        data = self._columns()
        if self.id is None:
            names = ", ".join(data)
            marks = ", ".join("?" for _ in data)
            self.id = repo_execute(
                f"INSERT INTO {self.table_name} ({names}) VALUES ({marks})", tuple(data.values())
            )
            stored = repo_one(f"SELECT created_at FROM {self.table_name} WHERE id = ?", (self.id,))
            self.created_at = stored["created_at"] if stored and "created_at" in stored else None
        else:
            self.update(**data)
        return self

    def update(self: T, **fields: Any) -> T:
        """Write only the named fields. Use this when the worker may be writing others."""
        if fields:
            assignments = ", ".join(f"{name} = ?" for name in fields)
            repo_execute(
                f"UPDATE {self.table_name} SET {assignments} WHERE id = ?", (*fields.values(), self.id)
            )
            for name, value in fields.items():
                setattr(self, name, value)
        return self

    def delete(self) -> None:
        repo_execute(f"DELETE FROM {self.table_name} WHERE id = ?", (self.id,))


class RecordModel(BaseModel):
    """One record of settings, stored as JSON under `record_id` in the settings table."""

    model_config = ConfigDict(extra="ignore")

    record_id: ClassVar[str] = ""

    @classmethod
    def load(cls: type[R]) -> R:
        row = repo_one("SELECT value FROM settings WHERE key = ?", (cls.record_id,))
        return cls(**json.loads(row["value"])) if row else cls()

    def save(self: R) -> R:
        repo_execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (self.record_id, json.dumps(self.model_dump())),
        )
        return self
