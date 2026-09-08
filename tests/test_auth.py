from datetime import datetime, timedelta, timezone

import jwt
from sqlmodel import select

from app.config import settings
from app.models import User


def test_register_returns_id_and_username_only(client):
    response = client.post("/register", json={"username": "vlad", "password": "correct horse battery"})
    assert response.status_code == 201
    assert response.json() == {"id": 1, "username": "vlad"}


def test_register_stores_argon2_hash_not_plaintext(client, session):
    client.post("/register", json={"username": "vlad", "password": "correct horse battery"})
    user = session.exec(select(User)).one()
    assert user.hashed_password.startswith("$argon2id$")
    assert "correct horse battery" not in user.hashed_password


def test_register_seeds_default_categories(client, auth):
    names = [c["name"] for c in client.get("/categories", headers=auth()).json()]
    assert names[0] == "uncategorized"
    assert "Groceries" in names and len(names) == 8


def test_register_rejects_duplicate_username_case_insensitively(client):
    client.post("/register", json={"username": "vlad", "password": "correct horse battery"})
    response = client.post("/register", json={"username": "VLAD", "password": "something else 1"})
    assert response.status_code == 409


def test_register_validates_password_and_username(client):
    assert client.post("/register", json={"username": "vlad", "password": "short"}).status_code == 422
    assert client.post("/register", json={"username": "bob smith", "password": "long enough 1"}).status_code == 422


def test_login_returns_bearer_token(client):
    client.post("/register", json={"username": "vlad", "password": "correct horse battery"})
    response = client.post("/token", data={"username": "vlad", "password": "correct horse battery"})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    claims = jwt.decode(body["access_token"], settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    assert claims["sub"] == "1"


def test_login_uses_one_message_for_wrong_password_and_unknown_user(client):
    client.post("/register", json={"username": "vlad", "password": "correct horse battery"})
    wrong = client.post("/token", data={"username": "vlad", "password": "nope"})
    unknown = client.post("/token", data={"username": "ghost", "password": "nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_protected_route_without_token(client):
    response = client.get("/expenses")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_protected_route_with_garbage_token(client):
    assert client.get("/expenses", headers={"Authorization": "Bearer abc.def.ghi"}).status_code == 401


def test_protected_route_with_expired_token(client, auth):
    auth()
    now = datetime.now(timezone.utc)
    expired = jwt.encode(
        {"sub": "1", "iat": now - timedelta(hours=2), "exp": now - timedelta(hours=1)},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    response = client.get("/expenses", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Token has expired"


def test_protected_route_with_token_signed_by_other_secret(client, auth):
    auth()
    forged = jwt.encode({"sub": "1", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, "x" * 32, algorithm="HS256")
    assert client.get("/expenses", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_health_is_public(client):
    assert client.get("/health").json() == {"status": "ok"}
