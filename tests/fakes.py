"""Fausse connexion Snowflake pour les tests (aucun appel réseau)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional


class FakeCursor:
    def __init__(self, store: "FakeConn") -> None:
        self.store = store
        self._result: Optional[tuple[Any, ...]] = None

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        sql_norm = " ".join(sql.split())
        self.store.executed.append((sql_norm, params))
        if sql_norm.startswith("SELECT MAX(started_at)"):
            self._result = (self.store.last_success,)
        elif sql_norm.startswith("INSERT INTO meta.pipeline_runs"):
            self.store.started.append(params)
            self._result = None
        elif sql_norm.startswith("UPDATE meta.pipeline_runs"):
            self.store.finished.append(params)
            self._result = None
        elif sql_norm.startswith("MERGE INTO"):
            if self.store.fail_on_merge:
                raise RuntimeError("merge exploded")
            self.store.merges.append(sql_norm)
            self._result = None
        else:
            self._result = None

    def executemany(self, sql: str, seq: Any) -> None:
        self.store.staged.append((" ".join(sql.split()), list(seq)))

    def fetchone(self) -> Optional[tuple[Any, ...]]:
        return self._result


class FakeConn:
    def __init__(self, last_success: Optional[datetime] = None, *, fail_on_merge: bool = False) -> None:
        self.last_success = last_success
        self.fail_on_merge = fail_on_merge
        self.executed: list[tuple[str, Any]] = []
        self.started: list[Any] = []
        self.staged: list[tuple[str, list[dict[str, Any]]]] = []
        self.merges: list[str] = []
        self.finished: list[Any] = []
        self.commits = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        return None

    def statements(self) -> list[str]:
        return [sql for sql, _ in self.executed]
