from __future__ import annotations

from pathlib import Path

import pytest

from scripts.snowflake_utils import SnowflakeSettings, sanitize_error

SF_VARS = (
    "ATTABOY_SF_ACCOUNT",
    "ATTABOY_SF_USER",
    "ATTABOY_SF_ROLE",
    "ATTABOY_SF_WAREHOUSE",
    "ATTABOY_SF_DATABASE",
    "ATTABOY_SF_PRIVATE_KEY_PATH",
    "ATTABOY_SF_PRIVATE_KEY_PASSPHRASE",
    "ATTABOY_SF_PASSWORD",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in SF_VARS:
        monkeypatch.delenv(var, raising=False)


def test_from_env_key_pair_with_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    key = tmp_path / "rsa_key.p8"
    key.write_text("dummy")
    monkeypatch.setenv("ATTABOY_SF_ACCOUNT", "myorg-myacct")
    monkeypatch.setenv("ATTABOY_SF_USER", "ATTABOY_PIPELINE_SVC")
    monkeypatch.setenv("ATTABOY_SF_PRIVATE_KEY_PATH", str(key))
    monkeypatch.setenv("ATTABOY_SF_PRIVATE_KEY_PASSPHRASE", "s3cret")

    settings = SnowflakeSettings.from_env()
    assert settings.role == "ATTABOY_PIPELINE"
    assert settings.warehouse == "ATTABOY_WH"
    assert settings.database == "ATTABOY_DW"

    kwargs = settings.connect_kwargs(query_tag="attaboy:test")
    assert kwargs["authenticator"] == "SNOWFLAKE_JWT"
    assert kwargs["private_key_file"] == str(key)
    assert kwargs["private_key_file_pwd"] == "s3cret"
    assert "password" not in kwargs
    assert kwargs["session_parameters"] == {"TIMEZONE": "UTC", "QUERY_TAG": "attaboy:test"}
    assert settings.secrets() == ("s3cret",)


def test_from_env_requires_some_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATTABOY_SF_ACCOUNT", "a")
    monkeypatch.setenv("ATTABOY_SF_USER", "u")
    with pytest.raises(SystemExit, match="ATTABOY_SF_PRIVATE_KEY_PATH"):
        SnowflakeSettings.from_env()


def test_from_env_missing_key_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ATTABOY_SF_ACCOUNT", "a")
    monkeypatch.setenv("ATTABOY_SF_USER", "u")
    monkeypatch.setenv("ATTABOY_SF_PRIVATE_KEY_PATH", str(tmp_path / "absent.p8"))
    with pytest.raises(SystemExit, match="introuvable"):
        SnowflakeSettings.from_env()


def test_password_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATTABOY_SF_ACCOUNT", "a")
    monkeypatch.setenv("ATTABOY_SF_USER", "u")
    monkeypatch.setenv("ATTABOY_SF_PASSWORD", "pw")
    kwargs = SnowflakeSettings.from_env().connect_kwargs(query_tag="t")
    assert kwargs["password"] == "pw"
    assert "authenticator" not in kwargs


def test_sanitize_error_redacts_values_and_markers() -> None:
    msg = sanitize_error(RuntimeError("bad passphrase s3cret for private_key_file=/x"), "s3cret")
    assert "s3cret" not in msg
    assert "/x" not in msg
