"""Optional password protection."""

from __future__ import annotations

from fastapi.testclient import TestClient

from customcbot import config
from customcbot.api import auth
from customcbot.api.main import create_app


def set_password(client, new, current=""):
    return client.put("/api/auth/password", json={"new_password": new, "current_password": current})


def test_without_a_password_everything_is_open(client):
    assert client.get("/api/auth/status").json() == {"required": False, "signed_in": True, "fixed": False}
    assert client.get("/api/collections").status_code == 200


def test_a_password_locks_the_data_but_not_the_sign_in_page(client, services):
    assert set_password(client, "tr0ub4dor").status_code == 200
    assert client.get("/api/collections").status_code == 200  # this browser stays signed in

    with TestClient(create_app(services)) as stranger:
        assert stranger.get("/").status_code == 200  # the page with the sign-in form loads
        assert stranger.get("/api/auth/status").json() == {"required": True, "signed_in": False, "fixed": False}
        for path in ("/api/collections", "/api/setup", "/api/settings", "/api/credentials"):
            reply = stranger.get(path)
            assert (reply.status_code, reply.json()["detail"]) == (401, "Sign in first."), path
        assert stranger.post("/api/collections", json={"name": "X"}).status_code == 401

        wrong = stranger.post("/api/auth/login", json={"password": "guess"})
        assert wrong.status_code == 400 and wrong.json()["detail"] == "That is not the right password."
        assert stranger.get("/api/collections").status_code == 401
        assert stranger.post("/api/auth/login", json={"password": "tr0ub4dor"}).json()["signed_in"] is True
        assert stranger.get("/api/collections").status_code == 200
        stranger.post("/api/auth/logout")
        assert stranger.get("/api/collections").status_code == 401


def test_the_password_is_stored_hashed_and_never_sent(client):
    set_password(client, "tr0ub4dor")
    stored = config.get("password_hash")
    assert "tr0ub4dor" not in stored and ":" in stored
    for path in ("/api/settings", "/api/setup"):
        assert "password_hash" not in client.get(path).text and stored not in client.get(path).text
    assert auth.matches("tr0ub4dor") and not auth.matches("Tr0ub4dor")


def test_changing_the_password_needs_the_old_one_and_signs_other_devices_out(client, services):
    set_password(client, "first-one")
    with TestClient(create_app(services)) as other:
        other.post("/api/auth/login", json={"password": "first-one"})
        assert other.get("/api/collections").status_code == 200
        refused = set_password(client, "second-one", current="nope")
        assert refused.status_code == 400 and refused.json()["detail"] == "The current password is not right."
        assert set_password(client, "second-one", current="first-one").status_code == 200
        assert client.get("/api/collections").status_code == 200  # the device that changed it stays in
        assert other.get("/api/collections").status_code == 401  # every other device must sign in again


def test_a_password_can_be_removed_and_must_not_be_too_short(client, services):
    short = set_password(client, "abc")
    assert short.status_code == 400 and short.json()["detail"] == "Use at least 6 characters."
    set_password(client, "long-enough")
    assert set_password(client, "", current="long-enough").json()["required"] is False
    with TestClient(create_app(services)) as anyone:
        assert anyone.get("/api/collections").status_code == 200


def test_a_password_from_the_environment_cannot_be_changed_in_the_app(client, monkeypatch):
    monkeypatch.setenv("CUSTOMCBOT_PASSWORD", "from-the-start")
    assert client.get("/api/auth/status").json() == {"required": True, "signed_in": False, "fixed": True}
    assert client.get("/api/collections").status_code == 401
    assert client.post("/api/auth/login", json={"password": "from-the-start"}).status_code == 200
    refused = set_password(client, "something-else", current="from-the-start")
    assert refused.status_code == 400 and "cannot be changed here" in refused.json()["detail"]


def test_a_stolen_cookie_from_an_old_password_is_useless(client):
    set_password(client, "first-one")
    old = auth.session_token()
    set_password(client, "second-one", current="first-one")
    assert not auth.signed_in(old) and auth.signed_in(auth.session_token())
