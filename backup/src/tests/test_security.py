import hashlib
from uuid import uuid4

import pytest
from fastapi import Request
from pydantic import ValidationError

from app.api import deps
from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import (
    create_access_token,
    hash_password,
    parse_access_token,
    verify_password,
)
from app.services.auth import AuthService
from app.services.system import SystemService


def test_password_hash_is_salted_and_verifiable() -> None:
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")
    assert first != second
    assert verify_password("correct horse battery staple", first)
    assert not verify_password("wrong password", first)


def test_access_token_round_trip() -> None:
    user_id = uuid4()
    token, _ = create_access_token(user_id)
    assert parse_access_token(token) == user_id


@pytest.mark.parametrize("environment", ["production", "prod"])
def test_production_rejects_actor_header(environment: str) -> None:
    with pytest.raises(ValidationError, match="ALLOW_ACTOR_HEADER"):
        Settings(
            app_env=environment,
            app_secret="a-production-secret-that-is-not-a-placeholder",
            allow_actor_header=True,
            _env_file=None,
        )


def test_login_attempt_key_does_not_expose_credentials() -> None:
    key = AuthService._login_attempt_key("User@Example.com", "127.0.0.1")
    assert key == AuthService._login_attempt_key("user@example.com", "127.0.0.1")
    assert key != AuthService._login_attempt_key("user@example.com", "127.0.0.2")
    assert key == hashlib.sha256(b"user@example.com\x00127.0.0.1").hexdigest()


def test_viewer_can_read_but_cannot_write_project(monkeypatch) -> None:
    actor_id = uuid4()
    project_id = uuid4()
    monkeypatch.setattr(deps, "_project_role", lambda *_: ("viewer", None))

    read_request = Request({"type": "http", "method": "GET", "headers": []})
    assert deps.require_project_access(read_request, project_id, object(), actor_id) == actor_id

    write_request = Request({"type": "http", "method": "POST", "headers": []})
    with pytest.raises(AppError) as error:
        deps.require_project_access(write_request, project_id, object(), actor_id)
    assert error.value.code == "project_write_forbidden"


def test_actor_header_is_defensively_disabled_in_production(monkeypatch) -> None:
    settings = Settings(
        app_env="development",
        allow_actor_header=True,
        _env_file=None,
    )
    settings.app_env = "production"
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    with pytest.raises(AppError) as error:
        deps.get_actor_id(x_actor_id=str(uuid4()))
    assert error.value.code == "actor_header_disabled"


def test_external_service_configuration_is_recursively_redacted() -> None:
    configuration = {
        "timeout": 30,
        "api_key": "sensitive",
        "nested": {"access_token": "sensitive", "model": "chat"},
    }
    assert SystemService._redact_sensitive_configuration(configuration) == {
        "timeout": 30,
        "api_key": "***",
        "nested": {"access_token": "***", "model": "chat"},
    }
