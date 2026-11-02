"""Tests for every acceptance criterion in SPECIFICATION.md. Run: pytest -v"""

import pytest

from app import create_app

ADMIN, BEN, CHLOE = 1, 2, 3  # seeded users (Aroha is the admin)


@pytest.fixture()
def client(tmp_path):
    app = create_app(str(tmp_path / "test.db"))
    app.testing = True
    return app.test_client()


def as_user(user_id):
    return {"X-User-Id": str(user_id)}


def give(client, sender, recipient, message):
    return client.post(
        "/api/kudos", json={"recipient_id": recipient, "message": message},
        headers=as_user(sender),
    )


# ---------------------------------------------------------------- US-1 / US-3
def test_give_kudos_happy_path(client):
    res = give(client, BEN, CHLOE, "  Thanks for the code review!  ")
    assert res.status_code == 201
    body = res.get_json()
    assert body["message"] == "Thanks for the code review!"  # trimmed (AC-1.2)
    assert body["sender"]["id"] == BEN and body["recipient"]["id"] == CHLOE
    assert body["is_visible"] is True


def test_recipient_list_excludes_current_user_and_is_sorted(client):
    names = [u["name"] for u in client.get("/api/users", headers=as_user(BEN)).get_json()]
    assert "Ben Carter" not in names
    assert names == sorted(names)


def test_cannot_send_kudos_to_self(client):
    res = give(client, BEN, BEN, "I'm great")
    assert res.status_code == 400
    assert "yourself" in res.get_json()["error"]


@pytest.mark.parametrize("message", ["", "   ", None, 123])
def test_message_is_required(client, message):
    assert give(client, BEN, CHLOE, message).status_code == 400


def test_message_length_limit(client):
    assert give(client, BEN, CHLOE, "x" * 280).status_code == 201
    assert give(client, BEN, CHLOE, "x" * 281).status_code == 400


def test_unknown_recipient(client):
    assert give(client, BEN, 999, "Hello").status_code == 404


def test_invalid_recipient_type(client):
    assert give(client, BEN, "3", "Hello").status_code == 400


def test_sender_cannot_be_spoofed(client):
    res = client.post(
        "/api/kudos",
        json={"recipient_id": CHLOE, "message": "Hi", "sender_id": ADMIN},
        headers=as_user(BEN),
    )
    assert res.get_json()["sender"]["id"] == BEN  # AC-1.5


def test_requires_sign_in(client):
    assert client.get("/api/kudos").status_code == 401
    assert client.post("/api/kudos", json={}).status_code == 401


# ------------------------------------------------------------------------ US-2
def test_feed_is_newest_first(client):
    give(client, BEN, CHLOE, "first")
    give(client, CHLOE, BEN, "second")
    feed = client.get("/api/kudos", headers=as_user(BEN)).get_json()
    assert [k["message"] for k in feed] == ["second", "first"]


def test_feed_limit(client):
    for i in range(55):
        give(client, BEN, CHLOE, f"kudos {i}")
    feed = client.get("/api/kudos?limit=100", headers=as_user(BEN)).get_json()
    assert len(feed) == 50
    assert client.get("/api/kudos?limit=abc", headers=as_user(BEN)).status_code == 400


def test_html_is_stored_as_plain_text(client):
    payload = "<script>alert('x')</script>"
    give(client, BEN, CHLOE, payload)
    # Returned verbatim as JSON text; the UI renders it with textContent (AC-2.3).
    assert client.get("/api/kudos", headers=as_user(BEN)).get_json()[0]["message"] == payload


# ------------------------------------------------------------------------ US-4
def test_non_admin_cannot_moderate(client):
    kid = give(client, BEN, CHLOE, "hello").get_json()["id"]
    assert client.get("/api/admin/kudos", headers=as_user(BEN)).status_code == 403
    assert client.patch(f"/api/admin/kudos/{kid}", json={"is_visible": False},
                        headers=as_user(BEN)).status_code == 403
    assert client.delete(f"/api/admin/kudos/{kid}", headers=as_user(BEN)).status_code == 403


def test_admin_hides_and_restores_with_audit(client):
    kid = give(client, BEN, CHLOE, "something rude").get_json()["id"]

    res = client.patch(f"/api/admin/kudos/{kid}",
                       json={"is_visible": False, "reason": "Inappropriate language"},
                       headers=as_user(ADMIN))
    assert res.status_code == 200
    body = res.get_json()
    assert body["is_visible"] is False
    assert body["moderation"]["by"] == "Aroha Ngata"
    assert body["moderation"]["reason"] == "Inappropriate language"
    assert body["moderation"]["at"]

    assert client.get("/api/kudos", headers=as_user(BEN)).get_json() == []  # gone from feed
    admin_view = client.get("/api/admin/kudos", headers=as_user(ADMIN)).get_json()
    assert admin_view[0]["id"] == kid  # still kept for audit (AC-4.5)

    client.patch(f"/api/admin/kudos/{kid}", json={"is_visible": True}, headers=as_user(ADMIN))
    assert len(client.get("/api/kudos", headers=as_user(BEN)).get_json()) == 1


def test_admin_deletes_permanently(client):
    kid = give(client, BEN, CHLOE, "delete me").get_json()["id"]
    assert client.delete(f"/api/admin/kudos/{kid}", headers=as_user(ADMIN)).status_code == 204
    assert client.get("/api/admin/kudos", headers=as_user(ADMIN)).get_json() == []
    assert client.delete(f"/api/admin/kudos/{kid}", headers=as_user(ADMIN)).status_code == 404


def test_moderation_validation(client):
    kid = give(client, BEN, CHLOE, "hi").get_json()["id"]
    bad = client.patch(f"/api/admin/kudos/{kid}", json={"is_visible": "no"}, headers=as_user(ADMIN))
    assert bad.status_code == 400
    missing = client.patch("/api/admin/kudos/999", json={"is_visible": False}, headers=as_user(ADMIN))
    assert missing.status_code == 404


def test_new_kudos_visible_by_default(client):
    kid = give(client, BEN, CHLOE, "hi").get_json()["id"]
    admin_view = client.get("/api/admin/kudos", headers=as_user(ADMIN)).get_json()
    assert next(k for k in admin_view if k["id"] == kid)["is_visible"] is True
