"""Kudos feature for the internal employee portal (see SPECIFICATION.md)."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, g, jsonify, request, send_from_directory

MAX_MESSAGE_LENGTH = 280
FEED_LIMIT = 50

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL,
    email      TEXT    NOT NULL UNIQUE,
    is_admin   BOOLEAN NOT NULL DEFAULT 0,
    is_active  BOOLEAN NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS kudos (
    id                INTEGER PRIMARY KEY,
    sender_id         INTEGER NOT NULL REFERENCES users(id),
    recipient_id      INTEGER NOT NULL REFERENCES users(id),
    message           TEXT    NOT NULL CHECK (length(message) BETWEEN 1 AND 280),
    created_at        TEXT    NOT NULL,
    is_visible        BOOLEAN NOT NULL DEFAULT 1,
    moderated_by      INTEGER REFERENCES users(id),
    moderated_at      TEXT,
    moderation_reason TEXT,
    CHECK (sender_id <> recipient_id)
);

CREATE INDEX IF NOT EXISTS idx_kudos_feed ON kudos (is_visible, created_at DESC);
"""

SEED_USERS = [
    ("Aroha Ngata", "aroha.ngata@example.com", 1),
    ("Ben Carter", "ben.carter@example.com", 0),
    ("Chloe Nguyen", "chloe.nguyen@example.com", 0),
    ("Dev Patel", "dev.patel@example.com", 0),
    ("Emma Wilson", "emma.wilson@example.com", 0),
]

KUDOS_SELECT = """
SELECT k.id, k.message, k.created_at, k.is_visible,
       k.moderated_at, k.moderation_reason,
       s.id AS sender_id, s.name AS sender_name,
       r.id AS recipient_id, r.name AS recipient_name,
       m.name AS moderated_by_name
FROM kudos k
JOIN users s ON s.id = k.sender_id
JOIN users r ON r.id = k.recipient_id
LEFT JOIN users m ON m.id = k.moderated_by
"""


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_app(db_path: str | None = None) -> Flask:
    app = Flask(__name__, static_folder="static")
    app.config["DATABASE"] = db_path or os.environ.get("KUDOS_DB", "kudos.db")

    # ------------------------------------------------------------- database
    def get_db() -> sqlite3.Connection:
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def init_db() -> None:
        db = sqlite3.connect(app.config["DATABASE"])
        db.executescript(SCHEMA)
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            db.executemany(
                "INSERT INTO users (name, email, is_admin) VALUES (?, ?, ?)", SEED_USERS
            )
        db.commit()
        db.close()

    init_db()

    def kudos_to_dict(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "message": row["message"],
            "created_at": row["created_at"],
            "is_visible": bool(row["is_visible"]),
            "sender": {"id": row["sender_id"], "name": row["sender_name"]},
            "recipient": {"id": row["recipient_id"], "name": row["recipient_name"]},
            "moderation": {
                "by": row["moderated_by_name"],
                "at": row["moderated_at"],
                "reason": row["moderation_reason"],
            },
        }

    def error(message: str, status: int):
        return jsonify({"error": message}), status

    # ----------------------------------------------------------------- auth
    # Demo auth: the portal's single sign-on would provide the user in
    # production. The sender is never taken from the request body (AC-1.5).
    def current_user():
        user_id = request.headers.get("X-User-Id", "")
        if not user_id.isdigit():
            return None
        return get_db().execute(
            "SELECT * FROM users WHERE id = ? AND is_active = 1", (int(user_id),)
        ).fetchone()

    def login_required(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user = current_user()
            if user is None:
                return error("Sign in required", 401)
            g.user = user
            return view(*args, **kwargs)

        return wrapper

    def admin_required(view):
        @wraps(view)
        @login_required
        def wrapper(*args, **kwargs):
            if not g.user["is_admin"]:
                return error("Administrator access required", 403)  # AC-4.1
            return view(*args, **kwargs)

        return wrapper

    # ------------------------------------------------------------------ API
    @app.get("/api/me")
    @login_required
    def me():
        u = g.user
        return jsonify({"id": u["id"], "name": u["name"], "is_admin": bool(u["is_admin"])})

    @app.get("/api/users")
    @login_required
    def users():  # AC-1.1
        rows = get_db().execute(
            "SELECT id, name FROM users WHERE is_active = 1 AND id <> ? ORDER BY name",
            (g.user["id"],),
        ).fetchall()
        return jsonify([dict(r) for r in rows])

    @app.get("/api/users/all")
    def all_users():  # demo user switcher only
        rows = get_db().execute(
            "SELECT id, name, is_admin FROM users WHERE is_active = 1 ORDER BY id"
        ).fetchall()
        return jsonify([{**dict(r), "is_admin": bool(r["is_admin"])} for r in rows])

    @app.get("/api/kudos")
    @login_required
    def feed():  # US-2
        try:
            limit = min(max(int(request.args.get("limit", FEED_LIMIT)), 1), FEED_LIMIT)
        except ValueError:
            return error("limit must be a number", 400)
        rows = get_db().execute(
            KUDOS_SELECT + " WHERE k.is_visible = 1 ORDER BY k.created_at DESC, k.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return jsonify([kudos_to_dict(r) for r in rows])

    @app.post("/api/kudos")
    @login_required
    def give_kudos():  # US-1, US-3
        data = request.get_json(silent=True) or {}
        recipient_id = data.get("recipient_id")
        message = data.get("message")

        if not isinstance(recipient_id, int) or isinstance(recipient_id, bool):
            return error("Choose a colleague to send kudos to", 400)
        if not isinstance(message, str) or not message.strip():
            return error("Write a short message of appreciation", 400)
        message = message.strip()
        if len(message) > MAX_MESSAGE_LENGTH:
            return error(f"Message must be {MAX_MESSAGE_LENGTH} characters or fewer", 400)
        if recipient_id == g.user["id"]:
            return error("You can't send kudos to yourself", 400)

        db = get_db()
        recipient = db.execute(
            "SELECT id FROM users WHERE id = ? AND is_active = 1", (recipient_id,)
        ).fetchone()
        if recipient is None:
            return error("Colleague not found", 404)

        cur = db.execute(
            "INSERT INTO kudos (sender_id, recipient_id, message, created_at) VALUES (?, ?, ?, ?)",
            (g.user["id"], recipient_id, message, now_utc()),
        )
        db.commit()
        row = db.execute(KUDOS_SELECT + " WHERE k.id = ?", (cur.lastrowid,)).fetchone()
        return jsonify(kudos_to_dict(row)), 201

    # ----------------------------------------------------------- moderation
    @app.get("/api/admin/kudos")
    @admin_required
    def admin_list():  # AC-4.5
        rows = get_db().execute(
            KUDOS_SELECT + " ORDER BY k.created_at DESC, k.id DESC"
        ).fetchall()
        return jsonify([kudos_to_dict(r) for r in rows])

    @app.patch("/api/admin/kudos/<int:kudos_id>")
    @admin_required
    def moderate(kudos_id: int):  # AC-4.2, AC-4.4
        data = request.get_json(silent=True) or {}
        visible = data.get("is_visible")
        if not isinstance(visible, bool):
            return error("is_visible must be true or false", 400)
        reason = data.get("reason")
        if reason is not None and not isinstance(reason, str):
            return error("reason must be text", 400)

        db = get_db()
        cur = db.execute(
            "UPDATE kudos SET is_visible = ?, moderated_by = ?, moderated_at = ?, "
            "moderation_reason = ? WHERE id = ?",
            (visible, g.user["id"], now_utc(), (reason or "").strip() or None, kudos_id),
        )
        if cur.rowcount == 0:
            return error("Kudos not found", 404)
        db.commit()
        row = db.execute(KUDOS_SELECT + " WHERE k.id = ?", (kudos_id,)).fetchone()
        return jsonify(kudos_to_dict(row))

    @app.delete("/api/admin/kudos/<int:kudos_id>")
    @admin_required
    def delete_kudos(kudos_id: int):  # AC-4.3
        db = get_db()
        cur = db.execute("DELETE FROM kudos WHERE id = ?", (kudos_id,))
        if cur.rowcount == 0:
            return error("Kudos not found", 404)
        db.commit()
        return "", 204

    # ------------------------------------------------------------------ UI
    @app.get("/")
    def dashboard():
        return send_from_directory(app.static_folder, "dashboard.html")

    return app


if __name__ == "__main__":
    create_app().run(debug=True, port=5000)
