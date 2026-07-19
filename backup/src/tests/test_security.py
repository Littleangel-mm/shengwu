from uuid import uuid4

from app.core.security import (
    create_access_token,
    hash_password,
    parse_access_token,
    verify_password,
)


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
