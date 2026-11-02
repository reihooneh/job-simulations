# Kudos Feature: Specification

**Project:** Datacom internal employee portal · **Author:** Reihaneh Rahmati (Graduate Developer, acting as AI Architect) · **Status:** ✅ Approved for implementation

**Original request:** "We need a way for people to give kudos to each other."

**Initial prompt to the AI agent:**

> Create a feature for our internal web app that allows users to give 'kudos' to their colleagues. A user should be able to select another user from a list, write a short message of appreciation, and submit it. There should also be a public feed on the main dashboard where all recently submitted kudos are visible.

**Architect review:** the AI's first draft covered giving kudos and the feed, but had **no content moderation**. Before approving, I added user story **US-4** (with its acceptance criteria) and an `is_visible` flag and moderation audit fields to the data model. Changes I made to the AI draft are marked **[Added in review]**.

---

## 1. Requirements

### 1.1 User stories

| ID | As a… | I want to… | So that… |
| --- | --- | --- | --- |
| US-1 | Employee | pick a colleague from a list and send them a short message of appreciation | I can recognise their work |
| US-2 | Employee | see a feed of recent kudos on the main dashboard | I can celebrate wins across the company |
| US-3 | Employee | get clear feedback if my kudos can't be sent | I know what to fix |
| **US-4** | **Administrator** | **hide or delete inappropriate kudos messages** | **the feed stays respectful and safe for everyone** **[Added in review]** |

### 1.2 Acceptance criteria

**US-1: Give kudos**

- AC-1.1 The recipient list shows all active colleagues, sorted by name, **excluding the current user**.
- AC-1.2 The message is required, is trimmed of surrounding whitespace, and is 1 to 280 characters long.
- AC-1.3 Users cannot send kudos to themselves. The server rejects this even if the UI is bypassed.
- AC-1.4 A successful submission returns `201 Created` with the saved kudos, and the new kudos appears at the top of the feed.
- AC-1.5 The sender is taken from the authenticated session, never from the request body, so users can't impersonate someone else.

**US-2: Public feed**

- AC-2.1 The dashboard shows the 50 most recent **visible** kudos, newest first.
- AC-2.2 Each item shows the sender name, recipient name, message and a relative time.
- AC-2.3 Messages are rendered as plain text, so HTML and scripts are escaped (XSS protection).

**US-3: Validation feedback**

- AC-3.1 Invalid requests return `400` with a JSON `error` message that the UI shows next to the form.
- AC-3.2 An unknown recipient returns `404`.

**US-4: Moderation** **[Added in review]**

- AC-4.1 Only users with `is_admin = true` can moderate. Everyone else gets `403 Forbidden`.
- AC-4.2 **Hide:** the admin sets a kudos to hidden, with an optional reason. It disappears from the public feed immediately but stays in the database for audit, and it can be **restored**.
- AC-4.3 **Delete:** the admin permanently removes a kudos, for example for content with legal or privacy issues.
- AC-4.4 Every hide or restore records who moderated it, when, and why (`moderated_by`, `moderated_at`, `moderation_reason`).
- AC-4.5 Admins can see a moderation view listing **all** kudos, including hidden ones.

### 1.3 Non-functional requirements

- **Security:** parameterised SQL only, sender identity taken from the session, admin checks on the server, output escaped.
- **Performance:** a feed query under 50 ms for 100,000 kudos, using an index on `(is_visible, created_at)`.
- **Quality:** automated tests for every acceptance criterion above.
- **Accessibility:** form fields have labels, a live character counter, and errors that screen readers announce.

### 1.4 Out of scope (v1)

Reactions, comments, notifications, editing kudos, and automated profanity filtering (a candidate for v2, alongside US-4).

---

## 2. Technical design

### 2.1 Architecture

```text
Browser (dashboard.html + app.js)
        │  fetch JSON
        ▼
Flask app (app.py) ── auth: current user from session header (demo) ── admin guard
        │  parameterised SQL
        ▼
SQLite (kudos.db): users, kudos
```

- **Backend:** Python 3 and Flask, a small REST API (`app.py`).
- **Database:** SQLite through the standard `sqlite3` module (swappable for PostgreSQL).
- **Frontend:** a plain HTML, CSS and JavaScript dashboard (`static/`), with no build step.
- **Auth (demo):** the current user is read from an `X-User-Id` header, set by a user switcher in the demo UI. In production this would come from the portal's existing single sign-on session.

### 2.2 Data model

**users**

| Column | Type | Notes |
| --- | --- | --- |
| id | INTEGER PK | |
| name | TEXT NOT NULL | |
| email | TEXT UNIQUE NOT NULL | |
| is_admin | BOOLEAN NOT NULL DEFAULT 0 | Needed for US-4 **[Added in review]** |
| is_active | BOOLEAN NOT NULL DEFAULT 1 | Inactive users are hidden from the recipient list |

**kudos**

| Column | Type | Notes |
| --- | --- | --- |
| id | INTEGER PK | |
| sender_id | INTEGER NOT NULL → users.id | |
| recipient_id | INTEGER NOT NULL → users.id | `CHECK (sender_id <> recipient_id)` |
| message | TEXT NOT NULL | `CHECK (length(message) BETWEEN 1 AND 280)` |
| created_at | TEXT NOT NULL | UTC, ISO 8601 |
| **is_visible** | **BOOLEAN NOT NULL DEFAULT 1** | **Moderation flag: `false` hides the kudos from the feed [Added in review]** |
| moderated_by | INTEGER NULL → users.id | Audit: the admin who last hid or restored it **[Added in review]** |
| moderated_at | TEXT NULL | Audit timestamp **[Added in review]** |
| moderation_reason | TEXT NULL | Optional reason **[Added in review]** |

Index: `idx_kudos_feed ON kudos(is_visible, created_at DESC)`.

### 2.3 API

| Method | Path | Who | Description |
| --- | --- | --- | --- |
| GET | `/api/me` | any user | Current user |
| GET | `/api/users` | any user | Active colleagues, excluding the current user (AC-1.1) |
| GET | `/api/kudos` | any user | Feed of visible kudos, newest first, `?limit=` up to 50 (US-2) |
| POST | `/api/kudos` | any user | Body `{recipient_id, message}` returns `201` (US-1) |
| GET | `/api/admin/kudos` | admin | All kudos, including hidden ones (AC-4.5) |
| PATCH | `/api/admin/kudos/<id>` | admin | Body `{is_visible: bool, reason?: str}` hides or restores (AC-4.2, 4.4) |
| DELETE | `/api/admin/kudos/<id>` | admin | Permanent delete, returns `204` (AC-4.3) |

Errors use a consistent JSON body: `{ "error": "message" }` with status `400`, `401`, `403` or `404`.

### 2.4 Test plan

`test_app.py` (pytest) covers:

- the happy path for giving kudos
- self-kudos rejection
- empty, whitespace-only and too-long messages
- unknown recipient
- sender spoofing being ignored
- feed order and limit
- HTML being stored safely as plain text
- the recipient list excluding the current user
- the admin-only checks (`403` for non-admins)
- hide, restore and delete, including the audit fields
- the feed excluding hidden kudos

---

## 3. Approval

- [x] Requirements reviewed, with moderation (US-4) added
- [x] Design reviewed, with `is_visible` and the audit fields added
- [x] Approved for AI-driven implementation

**Approved by:** Reihaneh Rahmati, AI Architect / Graduate Developer · November 2026
