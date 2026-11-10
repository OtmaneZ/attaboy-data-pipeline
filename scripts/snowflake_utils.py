"""Attaboy — utilitaires partagés : .env, connexion Snowflake, journal meta.pipeline_runs.

Authentification par paire de clés (service user Snowflake, TYPE=SERVICE).
Aucun secret n'est loggé ni écrit dans meta.pipeline_runs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DEFAULT_ATTABOY_HOME = "/opt/clients/attaboy"
DEFAULT_DATABASE = "ATTABOY_DW"
DEFAULT_WAREHOUSE = "ATTABOY_WH"
DEFAULT_ROLE = "ATTABOY_PIPELINE"


# ---------------------------------------------------------------------------
# Env
# ---------------------------------------------------------------------------


def load_dotenv(path: Path) -> None:
    """Charge KEY=VALUE dans os.environ si la clé n'est pas déjà définie."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_attaboy_env() -> Path:
    """Charge $ATTABOY_HOME/.env et retourne ATTABOY_HOME."""
    home = Path(os.environ.get("ATTABOY_HOME", DEFAULT_ATTABOY_HOME))
    load_dotenv(home / ".env")
    return home


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Variable d'environnement manquante: {name}")
    return value


def optional_env(name: str) -> Optional[str]:
    return os.environ.get(name, "").strip() or None


# ---------------------------------------------------------------------------
# Snowflake
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SnowflakeSettings:
    account: str
    user: str
    role: str
    warehouse: str
    database: str
    private_key_path: Optional[str] = None
    private_key_passphrase: Optional[str] = None
    password: Optional[str] = None

    @classmethod
    def from_env(cls) -> SnowflakeSettings:
        key_path = optional_env("ATTABOY_SF_PRIVATE_KEY_PATH")
        password = optional_env("ATTABOY_SF_PASSWORD")
        if not key_path and not password:
            raise SystemExit(
                "Authentification Snowflake manquante: renseigne "
                "ATTABOY_SF_PRIVATE_KEY_PATH (recommandé) ou ATTABOY_SF_PASSWORD."
            )
        if key_path and not Path(key_path).expanduser().is_file():
            raise SystemExit(f"Clé privée Snowflake introuvable: {key_path}")
        return cls(
            account=require_env("ATTABOY_SF_ACCOUNT"),
            user=require_env("ATTABOY_SF_USER"),
            role=optional_env("ATTABOY_SF_ROLE") or DEFAULT_ROLE,
            warehouse=optional_env("ATTABOY_SF_WAREHOUSE") or DEFAULT_WAREHOUSE,
            database=optional_env("ATTABOY_SF_DATABASE") or DEFAULT_DATABASE,
            private_key_path=str(Path(key_path).expanduser()) if key_path else None,
            private_key_passphrase=optional_env("ATTABOY_SF_PRIVATE_KEY_PASSPHRASE"),
            password=password,
        )

    def secrets(self) -> tuple[str, ...]:
        return tuple(s for s in (self.private_key_passphrase, self.password) if s)

    def connect_kwargs(self, *, query_tag: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "account": self.account,
            "user": self.user,
            "role": self.role,
            "warehouse": self.warehouse,
            "database": self.database,
            "application": "attaboy_pipeline",
            "session_parameters": {
                "TIMEZONE": "UTC",
                "QUERY_TAG": query_tag,
            },
        }
        if self.private_key_path:
            kwargs["authenticator"] = "SNOWFLAKE_JWT"
            kwargs["private_key_file"] = self.private_key_path
            if self.private_key_passphrase:
                kwargs["private_key_file_pwd"] = self.private_key_passphrase
        else:
            kwargs["password"] = self.password
        return kwargs


def connect(settings: SnowflakeSettings, *, query_tag: str) -> Any:
    import snowflake.connector

    return snowflake.connector.connect(**settings.connect_kwargs(query_tag=query_tag))


# ---------------------------------------------------------------------------
# Sanitisation
# ---------------------------------------------------------------------------

_SECRET_MARKERS = ("password=", "private_key")


def sanitize_error(exc: BaseException, *secrets: Optional[str]) -> str:
    msg = f"{type(exc).__name__}: {exc}"
    for secret in secrets:
        if secret and secret in msg:
            msg = msg.replace(secret, "***")
    lower = msg.lower()
    for marker in _SECRET_MARKERS:
        if marker in lower:
            idx = lower.index(marker)
            msg = msg[: idx + len(marker)] + "***"
            break
    return msg[:2000]


# ---------------------------------------------------------------------------
# meta.pipeline_runs
# ---------------------------------------------------------------------------

SQL_LAST_SUCCESS_STARTED_AT = """
SELECT MAX(started_at)
FROM meta.pipeline_runs
WHERE pipeline_name = %s AND status = 'success'
"""

SQL_START_RUN = """
INSERT INTO meta.pipeline_runs (run_id, pipeline_name, started_at, status)
VALUES (%s, %s, %s, 'running')
"""

SQL_FINISH_RUN = """
UPDATE meta.pipeline_runs
SET finished_at = %s,
    status = %s,
    rows_processed = %s,
    error_message = %s
WHERE run_id = %s
"""


class PipelineRunStore:
    """Journal d'exécution. run_id = UUID généré côté client (pas de RETURNING en Snowflake)."""

    def __init__(self, conn: Any, pipeline_name: str) -> None:
        self.conn = conn
        self.pipeline_name = pipeline_name

    def last_success_started_at(self) -> Optional[datetime]:
        with self.conn.cursor() as cur:
            cur.execute(SQL_LAST_SUCCESS_STARTED_AT, (self.pipeline_name,))
            row = cur.fetchone()
        return row[0] if row else None

    def start_run(self, run_id: str, started_at: datetime) -> str:
        with self.conn.cursor() as cur:
            cur.execute(SQL_START_RUN, (run_id, self.pipeline_name, started_at))
        self.conn.commit()
        return run_id

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        rows_processed: Optional[int],
        error_message: Optional[str],
        finished_at: Optional[datetime] = None,
    ) -> None:
        finished_at = finished_at or datetime.now(timezone.utc)
        with self.conn.cursor() as cur:
            cur.execute(
                SQL_FINISH_RUN,
                (finished_at, status, rows_processed, error_message, run_id),
            )
        self.conn.commit()
