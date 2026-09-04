from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import base64
import importlib.util
import math
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("SYNCMATE_DB_PATH", BASE_DIR / "syncmate.db"))
AVATAR_COLORS = {"rose", "mint", "violet", "orange", "blue"}

app = FastAPI(title="SyncMate API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_origin_regex=r"https?://(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\]):5173$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def load_receipt_helper():
    configured = os.environ.get("SYNCMATE_RECEIPT_SPLITTER")
    candidates = [configured] if configured else []
    candidates.append(str(Path.home() / ".codex" / "skills" / "receipt-splitter" / "scripts" / "receipt_splitter.py"))
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            spec = importlib.util.spec_from_file_location("syncmate_receipt_splitter", candidate)
            module = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(module)
            return module
    raise RuntimeError("receipt-splitter skill script not found")


class AuthBody(BaseModel):
    username: str = Field(min_length=3, max_length=30)
    password: str = Field(min_length=6, max_length=100)
    nickname: str | None = Field(default=None, max_length=30)


class ProfileBody(BaseModel):
    nickname: str = Field(min_length=1, max_length=30)
    avatar_color: str = Field(default="rose")


class PasswordBody(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6, max_length=100)


class GroupBody(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    type: str = Field(default="好友", max_length=20)
    template_key: str | None = None


class GroupUpdateBody(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    type: str = Field(max_length=20)
    announcement: str = Field(default="", max_length=500)
    theme_color: str = Field(default="mint", max_length=20)
    cover_style: str = Field(default="waves", max_length=20)
    join_requires_approval: bool = True


class InviteBody(BaseModel):
    valid_days: int = Field(default=7, ge=1, le=30)


class JoinBody(BaseModel):
    invite_code: str = Field(min_length=6, max_length=30)


class ReviewBody(BaseModel):
    decision: str


class MemberUpdateBody(BaseModel):
    role: str | None = None
    group_nickname: str | None = Field(default=None, max_length=30)
    member_note: str | None = Field(default=None, max_length=60)


class TransferBody(BaseModel):
    new_owner_id: int


class MessageBody(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class ActivityItemBody(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    start_at: str
    end_at: str
    note: str = Field(default="", max_length=300)


class ActivityLocationBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    address: str = Field(default="", max_length=300)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    budget_per_person: float | None = Field(default=None, ge=0, le=100000)
    opening_hours: str = Field(default="", max_length=120)


class ActivityBody(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    mode: str = Field(default="fixed")
    start_at: str | None = None
    end_at: str | None = None
    form: str = Field(default="", max_length=80)
    items: list[ActivityItemBody] = Field(default_factory=list)
    slots: list[ActivityItemBody] = Field(default_factory=list)
    notice: str = Field(default="", max_length=1000)
    locations: list[ActivityLocationBody] = Field(default_factory=list)
    budget_per_person: float | None = Field(default=None, ge=0, le=100000)
    location_id: int | None = None


class VoteBody(BaseModel):
    choices: list[dict] = Field(default_factory=list)
    location_choices: list[dict] = Field(default_factory=list)


class LocationBody(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class AvailabilityBody(BaseModel):
    start_at: str
    end_at: str
    visibility: str = Field(default="private", pattern="^(private|group)$")
    group_id: int | None = None
    note: str = Field(default="", max_length=200)


class PublishBody(BaseModel):
    items: list[ActivityItemBody] = Field(default_factory=list)
    notice: str = Field(default="", max_length=1000)
    location_id: int | None = None


@contextmanager
def db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"{salt.hex()}:{digest.hex()}"


def password_matches(password: str, stored: str) -> bool:
    salt_hex, expected = stored.split(":", 1)
    actual = password_hash(password, bytes.fromhex(salt_hex)).split(":", 1)[1]
    return hmac.compare_digest(actual, expected)


def initials(nickname: str) -> str:
    if not nickname:
        return "SM"
    if all(ord(char) < 128 for char in nickname):
        words = nickname.replace("_", " ").split()
        return ("".join(word[0] for word in words[:2]) if len(words) > 1 else words[0][:2]).upper()
    return nickname[-2:]


def user_json(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "nickname": row["nickname"],
        "avatar_color": row["avatar_color"],
        "initials": initials(row["nickname"]),
    }


def create_session(connection: sqlite3.Connection, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    connection.execute(
        "INSERT INTO sessions(token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, expires_at.isoformat()),
    )
    return token


def add_column(connection: sqlite3.Connection, table: str, definition: str) -> None:
    column = definition.split()[0]
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def migrate_group_schema(connection: sqlite3.Connection) -> None:
    add_column(connection, "groups_table", "announcement TEXT NOT NULL DEFAULT ''")
    add_column(connection, "groups_table", "theme_color TEXT NOT NULL DEFAULT 'mint'")
    add_column(connection, "groups_table", "cover_style TEXT NOT NULL DEFAULT 'waves'")
    add_column(connection, "groups_table", "invite_code TEXT")
    add_column(connection, "groups_table", "invite_expires_at TEXT")
    add_column(connection, "groups_table", "join_requires_approval INTEGER NOT NULL DEFAULT 1")
    add_column(connection, "groups_table", "is_dissolved INTEGER NOT NULL DEFAULT 0")
    add_column(connection, "memberships", "group_nickname TEXT")
    add_column(connection, "memberships", "member_note TEXT NOT NULL DEFAULT ''")
    add_column(connection, "memberships", "joined_at TEXT NOT NULL DEFAULT '2026-08-01 09:00:00'")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS join_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL REFERENCES groups_table(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            reviewed_at TEXT,
            UNIQUE(group_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            actor_id INTEGER NOT NULL REFERENCES users(id),
            action TEXT NOT NULL,
            summary TEXT NOT NULL,
            before_data TEXT,
            target_id INTEGER,
            undoable INTEGER NOT NULL DEFAULT 0,
            undone INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_groups_invite_code ON groups_table(invite_code);
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL REFERENCES groups_table(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL REFERENCES groups_table(id) ON DELETE CASCADE,
            creator_id INTEGER NOT NULL REFERENCES users(id),
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            mode TEXT NOT NULL CHECK(mode IN ('fixed','poll')),
            status TEXT NOT NULL DEFAULT 'published' CHECK(status IN ('open','ended','published')),
            start_at TEXT,
            end_at TEXT,
            form TEXT NOT NULL DEFAULT '',
            notice TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            published_at TEXT
        );
        CREATE TABLE IF NOT EXISTS activity_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            start_at TEXT NOT NULL,
            end_at TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS activity_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
            start_at TEXT NOT NULL,
            end_at TEXT NOT NULL,
            suggestion TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS activity_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
            slot_id INTEGER NOT NULL REFERENCES activity_slots(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            available INTEGER NOT NULL DEFAULT 0,
            suggestion TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(activity_id, slot_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS activity_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            address TEXT NOT NULL DEFAULT '',
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            budget_per_person REAL,
            opening_hours TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS activity_location_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
            location_id INTEGER NOT NULL REFERENCES activity_locations(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            suggestion TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(activity_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS member_locations (
            group_id INTEGER NOT NULL REFERENCES groups_table(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(group_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS ai_bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL REFERENCES groups_table(id) ON DELETE CASCADE,
            creator_id INTEGER NOT NULL REFERENCES users(id),
            title TEXT NOT NULL,
            instruction TEXT NOT NULL,
            result_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','active','archived')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            archived_at TEXT
        );
        CREATE TABLE IF NOT EXISTS ai_bill_transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_id INTEGER NOT NULL REFERENCES ai_bills(id) ON DELETE CASCADE,
            from_user_id INTEGER NOT NULL REFERENCES users(id),
            to_user_id INTEGER NOT NULL REFERENCES users(id),
            amount_cents INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS calendar_availability (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            group_id INTEGER REFERENCES groups_table(id) ON DELETE CASCADE,
            start_at TEXT NOT NULL,
            end_at TEXT NOT NULL,
            visibility TEXT NOT NULL DEFAULT 'private' CHECK(visibility IN ('private','group')),
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CHECK(end_at > start_at)
        );
        CREATE INDEX IF NOT EXISTS idx_calendar_availability_user_time
        ON calendar_availability(user_id, start_at);
        """
    )
    add_column(connection, "activities", "location_id INTEGER")
    add_column(connection, "activities", "budget_per_person REAL")
    connection.execute("UPDATE memberships SET role = 'member' WHERE role = 'temporary'")
    rows = connection.execute("SELECT id, color FROM groups_table WHERE invite_code IS NULL").fetchall()
    for row in rows:
        connection.execute(
            "UPDATE groups_table SET invite_code = ?, invite_expires_at = ?, theme_color = ? WHERE id = ?",
            (secrets.token_hex(4).upper(), (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(), row["color"], row["id"]),
        )


def audit(
    connection: sqlite3.Connection, group_id: int, actor_id: int, action: str,
    summary: str, before_data: dict | None = None, target_id: int | None = None,
    undoable: bool = False,
) -> None:
    connection.execute(
        """INSERT INTO audit_logs(group_id, actor_id, action, summary, before_data, target_id, undoable)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (group_id, actor_id, action, summary, json.dumps(before_data, ensure_ascii=False) if before_data else None, target_id, int(undoable)),
    )


def membership(connection: sqlite3.Connection, group_id: int, user_id: int) -> sqlite3.Row:
    row = connection.execute(
        """SELECT memberships.*, groups_table.owner_id, groups_table.is_dissolved
        FROM memberships JOIN groups_table ON groups_table.id = memberships.group_id
        WHERE memberships.group_id = ? AND memberships.user_id = ?""",
        (group_id, user_id),
    ).fetchone()
    if not row or row["is_dissolved"]:
        raise HTTPException(status_code=404, detail="群组不存在或你已不在群组中")
    return row


def require_role(connection: sqlite3.Connection, group_id: int, user_id: int, roles: set[str]) -> sqlite3.Row:
    row = membership(connection, group_id, user_id)
    if row["role"] not in roles:
        raise HTTPException(status_code=403, detail="你没有执行此操作的权限")
    return row


def validate_time_range(start_at: str, end_at: str) -> None:
    try:
        start = datetime.fromisoformat(start_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_at.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail="活动时间格式无效") from error
    if end <= start:
        raise HTTPException(status_code=400, detail="结束时间必须晚于开始时间")


def ensure_demo_members(connection: sqlite3.Connection, owner_id: int) -> None:
    member_specs = [
        ("member_lin", "小林", "mint"), ("member_zhou", "小周", "violet"),
        ("member_wang", "小王", "orange"), ("member_fang", "方方", "blue"),
        ("member_jia", "佳佳", "rose"),
    ]
    member_ids = {}
    for username, nickname, color in member_specs:
        connection.execute(
            "INSERT OR IGNORE INTO users(username, password_hash, nickname, avatar_color) VALUES (?, ?, ?, ?)",
            (username, password_hash(secrets.token_urlsafe(12)), nickname, color),
        )
        member_ids[username] = connection.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()["id"]
    group_members = {
        "周末聚餐": ["member_lin", "member_zhou", "member_wang", "member_fang", "member_jia"],
        "海边两日游": ["member_lin", "member_zhou", "member_wang"],
        "302 宿舍": ["member_zhou", "member_wang", "member_fang"],
    }
    for group_name, usernames in group_members.items():
        group = connection.execute("SELECT id FROM groups_table WHERE name = ? AND owner_id = ?", (group_name, owner_id)).fetchone()
        if not group:
            continue
        for username in usernames:
            connection.execute(
                "INSERT OR IGNORE INTO memberships(group_id, user_id, role) VALUES (?, ?, 'member')",
                (group["id"], member_ids[username]),
            )


def current_user(authorization: str | None = Header(default=None)) -> sqlite3.Row:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="请先登录")
    token = authorization.removeprefix("Bearer ").strip()
    with db() as connection:
        row = connection.execute(
            """
            SELECT users.* FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ? AND sessions.expires_at > ?
            """,
            (token, datetime.now(timezone.utc).isoformat()),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="登录状态已失效")
    return row


def initialize_database() -> None:
    with db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                nickname TEXT NOT NULL,
                avatar_color TEXT NOT NULL DEFAULT 'rose',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS groups_table (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                color TEXT NOT NULL,
                owner_id INTEGER NOT NULL REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS memberships (
                group_id INTEGER NOT NULL REFERENCES groups_table(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role TEXT NOT NULL DEFAULT 'member',
                PRIMARY KEY(group_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS bills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL REFERENCES groups_table(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                amount REAL NOT NULL,
                payer_id INTEGER NOT NULL REFERENCES users(id),
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL REFERENCES groups_table(id) ON DELETE CASCADE,
                from_user_id INTEGER NOT NULL REFERENCES users(id),
                to_user_id INTEGER NOT NULL REFERENCES users(id),
                amount REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                group_id INTEGER REFERENCES groups_table(id) ON DELETE SET NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                amount REAL NOT NULL,
                direction TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        migrate_group_schema(connection)
        demo = connection.execute("SELECT id FROM users WHERE username = 'demo'").fetchone()
        if demo:
            ensure_demo_members(connection, demo["id"])
            return
        cursor = connection.execute(
            "INSERT INTO users(username, password_hash, nickname, avatar_color) VALUES (?, ?, ?, ?)",
            ("demo", password_hash("123456"), "Yilin", "rose"),
        )
        user_id = cursor.lastrowid
        group_specs = [
            ("周末聚餐", "好友", "mint"),
            ("海边两日游", "旅行", "peach"),
            ("302 宿舍", "宿舍", "lavender"),
        ]
        group_ids = []
        for name, kind, color in group_specs:
            group_cursor = connection.execute(
                "INSERT INTO groups_table(name, type, color, owner_id) VALUES (?, ?, ?, ?)",
                (name, kind, color, user_id),
            )
            group_ids.append(group_cursor.lastrowid)
            connection.execute(
                "INSERT INTO memberships(group_id, user_id, role) VALUES (?, ?, 'owner')",
                (group_cursor.lastrowid, user_id),
            )
        ensure_demo_members(connection, user_id)
        connection.executemany(
            "INSERT INTO bills(group_id, title, amount, payer_id, status) VALUES (?, ?, ?, ?, ?)",
            [
                (group_ids[0], "火锅聚餐", 268, user_id, "pending"),
                (group_ids[1], "海边住宿", 1246.5, user_id, "confirmed"),
                (group_ids[2], "宿舍公共用品", 86, user_id, "confirmed"),
            ],
        )
        connection.executemany(
            "INSERT INTO payments(group_id, from_user_id, to_user_id, amount, status) VALUES (?, ?, ?, ?, ?)",
            [
                (group_ids[0], user_id, user_id, 42.5, "pending_out"),
                (group_ids[1], user_id, user_id, 86, "pending_in"),
            ],
        )
        connection.executemany(
            "INSERT INTO transactions(user_id, group_id, title, category, amount, direction) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (user_id, group_ids[0], "火锅聚餐", "餐饮", 128, "expense"),
                (user_id, group_ids[1], "住宿结算", "旅行", 312, "income"),
                (user_id, group_ids[2], "宿舍用品", "生活", 46.5, "expense"),
            ],
        )


@app.on_event("startup")
def startup() -> None:
    initialize_database()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/auth/register", status_code=201)
def register(body: AuthBody) -> dict:
    nickname = (body.nickname or body.username).strip()
    with db() as connection:
        try:
            cursor = connection.execute(
                "INSERT INTO users(username, password_hash, nickname, avatar_color) VALUES (?, ?, ?, 'violet')",
                (body.username.strip(), password_hash(body.password), nickname),
            )
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="用户名已存在") from error
        token = create_session(connection, cursor.lastrowid)
        row = connection.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return {"token": token, "user": user_json(row)}


@app.post("/api/auth/login")
def login(body: AuthBody) -> dict:
    with db() as connection:
        row = connection.execute("SELECT * FROM users WHERE username = ?", (body.username.strip(),)).fetchone()
        if not row or not password_matches(body.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        token = create_session(connection, row["id"])
    return {"token": token, "user": user_json(row)}


@app.post("/api/auth/logout")
def logout(authorization: str | None = Header(default=None)) -> dict:
    if authorization and authorization.startswith("Bearer "):
        with db() as connection:
            connection.execute("DELETE FROM sessions WHERE token = ?", (authorization.removeprefix("Bearer ").strip(),))
    return {"ok": True}


@app.get("/api/me")
def get_me(user: sqlite3.Row = Depends(current_user)) -> dict:
    return user_json(user)


@app.patch("/api/me")
def update_me(body: ProfileBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    if body.avatar_color not in AVATAR_COLORS:
        raise HTTPException(status_code=400, detail="头像颜色无效")
    with db() as connection:
        connection.execute(
            "UPDATE users SET nickname = ?, avatar_color = ? WHERE id = ?",
            (body.nickname.strip(), body.avatar_color, user["id"]),
        )
        row = connection.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    return user_json(row)


@app.patch("/api/me/password")
def update_password(body: PasswordBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    if not password_matches(body.current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    with db() as connection:
        connection.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash(body.new_password), user["id"]))
    return {"ok": True}


def group_json(connection: sqlite3.Connection, row: sqlite3.Row, current_user_id: int | None = None) -> dict:
    members = connection.execute(
        """
        SELECT users.nickname FROM memberships
        JOIN users ON users.id = memberships.user_id
        WHERE memberships.group_id = ? ORDER BY memberships.role DESC
        """,
        (row["id"],),
    ).fetchall()
    total = connection.execute("SELECT COALESCE(SUM(amount), 0) AS total FROM bills WHERE group_id = ?", (row["id"],)).fetchone()["total"]
    current_role = None
    if current_user_id:
        role_row = connection.execute("SELECT role FROM memberships WHERE group_id = ? AND user_id = ?", (row["id"], current_user_id)).fetchone()
        current_role = role_row["role"] if role_row else None
    return {
        "id": row["id"], "name": row["name"], "type": row["type"], "color": row["color"],
        "amount": f"¥{total:,.2f}", "people": len(members),
        "members": [initials(member["nickname"]) for member in members],
        "current_role": current_role, "owner_id": row["owner_id"],
        "announcement": row["announcement"], "theme_color": row["theme_color"],
        "cover_style": row["cover_style"], "join_requires_approval": bool(row["join_requires_approval"]),
    }


@app.get("/api/groups")
def list_groups(user: sqlite3.Row = Depends(current_user)) -> list[dict]:
    with db() as connection:
        rows = connection.execute(
            """SELECT groups_table.* FROM groups_table
            JOIN memberships ON memberships.group_id = groups_table.id
            WHERE memberships.user_id = ? AND groups_table.is_dissolved = 0 ORDER BY groups_table.id DESC""",
            (user["id"],),
        ).fetchall()
        return [group_json(connection, row, user["id"]) for row in rows]


@app.post("/api/groups", status_code=201)
def create_group(body: GroupBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    colors = ["mint", "peach", "lavender", "blue"]
    templates = {
        "dorm": ("宿舍", "每周值日与公共费用请及时确认。", "mint", "grid"),
        "roommate": ("合租", "房租、水电及公共采购统一在群内记录。", "blue", "home"),
        "trip": ("旅行", "行程变化和共同支出请同步更新。", "peach", "sun"),
        "dinner": ("聚餐", "活动结束后请认领消费并确认账单。", "lavender", "waves"),
    }
    with db() as connection:
        count = connection.execute("SELECT COUNT(*) FROM groups_table").fetchone()[0]
        kind, announcement, theme, cover = templates.get(body.template_key, (body.type, "", colors[count % len(colors)], "waves"))
        invite_code = secrets.token_hex(4).upper()
        expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        cursor = connection.execute(
            """INSERT INTO groups_table(name, type, color, owner_id, announcement, theme_color, cover_style, invite_code, invite_expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (body.name.strip(), kind, theme, user["id"], announcement, theme, cover, invite_code, expires),
        )
        connection.execute(
            "INSERT INTO memberships(group_id, user_id, role) VALUES (?, ?, 'owner')",
            (cursor.lastrowid, user["id"]),
        )
        audit(connection, cursor.lastrowid, user["id"], "group_created", f"创建了群组“{body.name.strip()}”")
        row = connection.execute("SELECT * FROM groups_table WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return group_json(connection, row, user["id"])


@app.get("/api/groups/{group_id}")
def group_detail(group_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        member = membership(connection, group_id, user["id"])
        group = connection.execute("SELECT * FROM groups_table WHERE id = ?", (group_id,)).fetchone()
        members = connection.execute(
            """SELECT users.id, users.username, users.nickname, users.avatar_color,
            memberships.role, memberships.group_nickname, memberships.member_note, memberships.joined_at
            FROM memberships JOIN users ON users.id = memberships.user_id
            WHERE memberships.group_id = ?
            ORDER BY CASE memberships.role WHEN 'owner' THEN 1 WHEN 'admin' THEN 2 WHEN 'member' THEN 3 ELSE 4 END,
            memberships.joined_at""",
            (group_id,),
        ).fetchall()
        requests = []
        if member["role"] in {"owner", "admin"}:
            requests = connection.execute(
                """SELECT join_requests.id, join_requests.created_at, users.id AS user_id,
                users.nickname, users.username, users.avatar_color
                FROM join_requests JOIN users ON users.id = join_requests.user_id
                WHERE join_requests.group_id = ? AND join_requests.status = 'pending'
                ORDER BY join_requests.created_at DESC""",
                (group_id,),
            ).fetchall()
        logs = connection.execute(
            """SELECT audit_logs.id, audit_logs.action, audit_logs.summary, audit_logs.undoable,
            audit_logs.undone, audit_logs.created_at, users.nickname AS actor
            FROM audit_logs JOIN users ON users.id = audit_logs.actor_id
            WHERE audit_logs.group_id = ? ORDER BY audit_logs.id DESC LIMIT 30""",
            (group_id,),
        ).fetchall()
        payload = group_json(connection, group, user["id"])
        payload.update({
            "invite_code": group["invite_code"] if member["role"] in {"owner", "admin"} else None,
            "invite_expires_at": group["invite_expires_at"] if member["role"] in {"owner", "admin"} else None,
            "members_detail": [
                {
                    **dict(row), "display_name": row["group_nickname"] or row["nickname"],
                    "initials": initials(row["group_nickname"] or row["nickname"]),
                    "activity_score": min(100, 35 + (20 if row["role"] == "owner" else 10 if row["role"] == "admin" else 0) + 12 * connection.execute(
                        "SELECT COUNT(*) FROM audit_logs WHERE group_id = ? AND actor_id = ?", (group_id, row["id"])
                    ).fetchone()[0]),
                } for row in members
            ],
            "join_requests": [dict(row) for row in requests],
            "audit_logs": [dict(row) for row in logs],
        })
        return payload


@app.patch("/api/groups/{group_id}")
def update_group(group_id: int, body: GroupUpdateBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    if body.theme_color not in {"mint", "peach", "lavender", "blue", "rose"}:
        raise HTTPException(status_code=400, detail="主题色无效")
    with db() as connection:
        require_role(connection, group_id, user["id"], {"owner", "admin"})
        old = connection.execute("SELECT * FROM groups_table WHERE id = ?", (group_id,)).fetchone()
        before = {key: old[key] for key in ("name", "type", "announcement", "theme_color", "cover_style", "join_requires_approval")}
        connection.execute(
            """UPDATE groups_table SET name = ?, type = ?, announcement = ?, theme_color = ?, color = ?,
            cover_style = ?, join_requires_approval = ? WHERE id = ?""",
            (body.name.strip(), body.type, body.announcement.strip(), body.theme_color, body.theme_color,
             body.cover_style, int(body.join_requires_approval), group_id),
        )
        audit(connection, group_id, user["id"], "group_updated", "更新了群组资料与设置", before, undoable=True)
        row = connection.execute("SELECT * FROM groups_table WHERE id = ?", (group_id,)).fetchone()
        return group_json(connection, row, user["id"])


@app.post("/api/groups/{group_id}/invite")
def refresh_invite(group_id: int, body: InviteBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        require_role(connection, group_id, user["id"], {"owner", "admin"})
        code = secrets.token_hex(4).upper()
        expires = datetime.now(timezone.utc) + timedelta(days=body.valid_days)
        connection.execute("UPDATE groups_table SET invite_code = ?, invite_expires_at = ? WHERE id = ?", (code, expires.isoformat(), group_id))
        audit(connection, group_id, user["id"], "invite_refreshed", f"更新了邀请，有效期 {body.valid_days} 天")
        return {"invite_code": code, "invite_expires_at": expires.isoformat(), "join_path": f"/join/{code}"}


@app.post("/api/groups/join")
def join_group(body: JoinBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        group = connection.execute(
            "SELECT * FROM groups_table WHERE invite_code = ? AND is_dissolved = 0",
            (body.invite_code.strip().upper(),),
        ).fetchone()
        if not group:
            raise HTTPException(status_code=404, detail="邀请码无效")
        if not group["invite_expires_at"] or group["invite_expires_at"] < datetime.now(timezone.utc).isoformat():
            raise HTTPException(status_code=400, detail="邀请已过期")
        existing = connection.execute("SELECT 1 FROM memberships WHERE group_id = ? AND user_id = ?", (group["id"], user["id"])).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="你已经在该群组中")
        if group["join_requires_approval"]:
            connection.execute(
                """INSERT INTO join_requests(group_id, user_id, status) VALUES (?, ?, 'pending')
                ON CONFLICT(group_id, user_id) DO UPDATE SET status = 'pending', created_at = CURRENT_TIMESTAMP""",
                (group["id"], user["id"]),
            )
            audit(connection, group["id"], user["id"], "join_requested", f"{user['nickname']} 申请加入群组")
            return {"status": "pending", "group_name": group["name"]}
        connection.execute("INSERT INTO memberships(group_id, user_id, role) VALUES (?, ?, 'member')", (group["id"], user["id"]))
        audit(connection, group["id"], user["id"], "member_joined", f"{user['nickname']} 通过邀请加入群组")
        return {"status": "joined", "group_name": group["name"]}


@app.post("/api/groups/{group_id}/requests/{request_id}/review")
def review_request(group_id: int, request_id: int, body: ReviewBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    if body.decision not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="审核结果无效")
    with db() as connection:
        require_role(connection, group_id, user["id"], {"owner", "admin"})
        request = connection.execute(
            """SELECT join_requests.*, users.nickname FROM join_requests JOIN users ON users.id = join_requests.user_id
            WHERE join_requests.id = ? AND join_requests.group_id = ? AND join_requests.status = 'pending'""",
            (request_id, group_id),
        ).fetchone()
        if not request:
            raise HTTPException(status_code=404, detail="申请不存在或已处理")
        connection.execute("UPDATE join_requests SET status = ?, reviewed_at = CURRENT_TIMESTAMP WHERE id = ?", (body.decision, request_id))
        if body.decision == "approved":
            connection.execute("INSERT OR IGNORE INTO memberships(group_id, user_id, role) VALUES (?, ?, 'member')", (group_id, request["user_id"]))
        summary = f"{'通过' if body.decision == 'approved' else '拒绝'}了 {request['nickname']} 的入群申请"
        audit(connection, group_id, user["id"], "join_reviewed", summary)
        return {"ok": True}


@app.patch("/api/groups/{group_id}/members/{member_id}")
def update_member(group_id: int, member_id: int, body: MemberUpdateBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        actor = membership(connection, group_id, user["id"])
        target = connection.execute(
            """SELECT memberships.*, users.nickname FROM memberships JOIN users ON users.id = memberships.user_id
            WHERE group_id = ? AND user_id = ?""", (group_id, member_id),
        ).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="成员不存在")
        role = target["role"]
        group_nickname = target["group_nickname"]
        member_note = target["member_note"]
        if body.role is not None:
            if actor["role"] != "owner" or member_id == user["id"] or body.role not in {"admin", "member"}:
                raise HTTPException(status_code=403, detail="只有群主可以调整其他成员角色")
            role = body.role
        if body.group_nickname is not None:
            if member_id != user["id"] and actor["role"] not in {"owner", "admin"}:
                raise HTTPException(status_code=403, detail="无权修改该成员群昵称")
            group_nickname = body.group_nickname.strip() or None
        if body.member_note is not None:
            if actor["role"] not in {"owner", "admin"}:
                raise HTTPException(status_code=403, detail="只有管理员可以设置成员备注")
            member_note = body.member_note.strip()
        before = {"role": target["role"], "group_nickname": target["group_nickname"], "member_note": target["member_note"]}
        connection.execute(
            "UPDATE memberships SET role = ?, group_nickname = ?, member_note = ? WHERE group_id = ? AND user_id = ?",
            (role, group_nickname, member_note, group_id, member_id),
        )
        audit(connection, group_id, user["id"], "member_updated", f"更新了 {target['nickname']} 的角色或备注", before, member_id, True)
        return {"ok": True}


@app.delete("/api/groups/{group_id}/members/{member_id}")
def remove_member(group_id: int, member_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        actor = require_role(connection, group_id, user["id"], {"owner", "admin"})
        target = connection.execute("SELECT memberships.*, users.nickname FROM memberships JOIN users ON users.id = memberships.user_id WHERE group_id = ? AND user_id = ?", (group_id, member_id)).fetchone()
        if not target or target["role"] == "owner" or (actor["role"] == "admin" and target["role"] == "admin"):
            raise HTTPException(status_code=403, detail="不能移除该成员")
        before = dict(target)
        connection.execute("DELETE FROM memberships WHERE group_id = ? AND user_id = ?", (group_id, member_id))
        audit(connection, group_id, user["id"], "member_removed", f"移除了成员 {target['nickname']}", before, member_id, True)
        return {"ok": True}


@app.post("/api/groups/{group_id}/transfer")
def transfer_owner(group_id: int, body: TransferBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        require_role(connection, group_id, user["id"], {"owner"})
        target = connection.execute("SELECT memberships.*, users.nickname FROM memberships JOIN users ON users.id = memberships.user_id WHERE group_id = ? AND user_id = ?", (group_id, body.new_owner_id)).fetchone()
        if not target:
            raise HTTPException(status_code=400, detail="请选择正式成员作为新群主")
        connection.execute("UPDATE memberships SET role = 'admin' WHERE group_id = ? AND user_id = ?", (group_id, user["id"]))
        connection.execute("UPDATE memberships SET role = 'owner' WHERE group_id = ? AND user_id = ?", (group_id, body.new_owner_id))
        connection.execute("UPDATE groups_table SET owner_id = ? WHERE id = ?", (body.new_owner_id, group_id))
        audit(connection, group_id, user["id"], "owner_transferred", f"将群主转让给 {target['nickname']}")
        return {"ok": True}


@app.post("/api/groups/{group_id}/leave")
def leave_group(group_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        member = membership(connection, group_id, user["id"])
        if member["role"] == "owner":
            raise HTTPException(status_code=400, detail="群主需要先转让群主后才能退出")
        connection.execute("DELETE FROM memberships WHERE group_id = ? AND user_id = ?", (group_id, user["id"]))
        audit(connection, group_id, user["id"], "member_left", f"{user['nickname']} 退出了群组")
        return {"ok": True}


@app.delete("/api/groups/{group_id}")
def dissolve_group(group_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        require_role(connection, group_id, user["id"], {"owner"})
        connection.execute("UPDATE groups_table SET is_dissolved = 1 WHERE id = ?", (group_id,))
        audit(connection, group_id, user["id"], "group_dissolved", "解散了群组")
        return {"ok": True}


def activity_json(connection: sqlite3.Connection, activity: sqlite3.Row, user_id: int) -> dict:
    items = connection.execute("SELECT * FROM activity_items WHERE activity_id = ? ORDER BY sort_order, id", (activity["id"],)).fetchall()
    slots = connection.execute("SELECT * FROM activity_slots WHERE activity_id = ? ORDER BY sort_order, id", (activity["id"],)).fetchall()
    member_count = connection.execute("SELECT COUNT(*) FROM memberships WHERE group_id = ?", (activity["group_id"],)).fetchone()[0]
    voted_count = connection.execute("SELECT COUNT(DISTINCT user_id) FROM activity_votes WHERE activity_id = ?", (activity["id"],)).fetchone()[0]
    votes = []
    for slot in slots:
        rows = connection.execute(
            """SELECT activity_votes.*, users.nickname, memberships.group_nickname FROM activity_votes
            JOIN users ON users.id = activity_votes.user_id JOIN memberships ON memberships.user_id = users.id AND memberships.group_id = ?
            WHERE activity_votes.activity_id = ? AND activity_votes.slot_id = ? ORDER BY users.id""",
            (activity["group_id"], activity["id"], slot["id"]),
        ).fetchall()
        votes.append({**dict(slot), "votes": [dict(row) for row in rows], "available_count": sum(row["available"] for row in rows)})
    creator = connection.execute("SELECT nickname FROM users WHERE id = ?", (activity["creator_id"],)).fetchone()
    location_rows = connection.execute("SELECT * FROM activity_locations WHERE activity_id = ? ORDER BY sort_order, id", (activity["id"],)).fetchall()
    member_positions = connection.execute("SELECT user_id, lat, lng FROM member_locations WHERE group_id = ?", (activity["group_id"],)).fetchall()
    location_votes = connection.execute("SELECT activity_location_votes.*, users.nickname, memberships.group_nickname FROM activity_location_votes JOIN users ON users.id = activity_location_votes.user_id JOIN memberships ON memberships.user_id = users.id AND memberships.group_id = ? WHERE activity_location_votes.activity_id = ? ORDER BY users.id", (activity["group_id"], activity["id"])).fetchall()
    def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        radius = 6371.0
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp = math.radians(lat2 - lat1)
        dl = math.radians(lng2 - lng1)
        value = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return radius * 2 * math.asin(min(1, math.sqrt(value)))
    location_payload = []
    for location in location_rows:
        distances = [distance_km(float(location["lat"]), float(location["lng"]), float(pos["lat"]), float(pos["lng"])) for pos in member_positions]
        average_distance = sum(distances) / len(distances) if distances else None
        distance_score = max(0.0, min(100.0, 100.0 - (average_distance or 0) * 12))
        votes_for = [dict(vote) for vote in location_votes if vote["location_id"] == location["id"]]
        vote_score = (len(votes_for) / member_count * 100) if member_count else 0
        budget_score = 100.0
        if activity["budget_per_person"] is not None and location["budget_per_person"] is not None:
            ratio = float(location["budget_per_person"]) / max(float(activity["budget_per_person"]), 1)
            budget_score = max(0.0, 100.0 - abs(ratio - 1) * 100)
        score = distance_score * 0.35 + vote_score * 0.30 + budget_score * 0.20 + 100.0 * 0.15
        location_payload.append({**dict(location), "average_distance_km": round(average_distance, 2) if average_distance is not None else None, "distance_score": round(distance_score, 1), "vote_count": len(votes_for), "vote_score": round(vote_score, 1), "budget_score": round(budget_score, 1), "opening_score": 100.0, "score": round(score, 1), "votes": votes_for})
    return {
        **dict(activity), "creator_name": creator["nickname"] if creator else "", "items": [dict(row) for row in items],
        "slots": votes, "member_count": member_count, "voted_count": voted_count,
        "all_voted": member_count > 0 and voted_count >= member_count,
        "my_votes": [dict(row) for row in connection.execute("SELECT * FROM activity_votes WHERE activity_id = ? AND user_id = ?", (activity["id"], user_id)).fetchall()],
        "locations": location_payload,
        "my_location_vote": next((dict(row) for row in location_votes if row["user_id"] == user_id), None),
        "member_location_count": len(member_positions),
        "selected_location_id": activity["location_id"],
    }


@app.get("/api/groups/{group_id}/messages")
def list_messages(group_id: int, user: sqlite3.Row = Depends(current_user)) -> list[dict]:
    with db() as connection:
        membership(connection, group_id, user["id"])
        rows = connection.execute(
            """SELECT chat_messages.*, users.nickname, users.avatar_color, memberships.group_nickname
            FROM chat_messages JOIN users ON users.id = chat_messages.user_id
            LEFT JOIN memberships ON memberships.user_id = users.id AND memberships.group_id = ?
            WHERE chat_messages.group_id = ? ORDER BY chat_messages.id DESC LIMIT 100""", (group_id, group_id),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]


@app.post("/api/groups/{group_id}/messages", status_code=201)
def send_message(group_id: int, body: MessageBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        membership(connection, group_id, user["id"])
        cursor = connection.execute("INSERT INTO chat_messages(group_id, user_id, content) VALUES (?, ?, ?)", (group_id, user["id"], body.content.strip()))
        row = connection.execute(
            """SELECT chat_messages.*, users.nickname, users.avatar_color, memberships.group_nickname
            FROM chat_messages JOIN users ON users.id = chat_messages.user_id
            LEFT JOIN memberships ON memberships.user_id = users.id AND memberships.group_id = ? WHERE chat_messages.id = ?""", (group_id, cursor.lastrowid),
        ).fetchone()
        audit(connection, group_id, user["id"], "message_sent", f"发送了一条群聊消息")
        return dict(row)


@app.get("/api/groups/{group_id}/activities")
def list_activities(group_id: int, user: sqlite3.Row = Depends(current_user)) -> list[dict]:
    with db() as connection:
        membership(connection, group_id, user["id"])
        rows = connection.execute("SELECT * FROM activities WHERE group_id = ? ORDER BY id DESC", (group_id,)).fetchall()
        return [activity_json(connection, row, user["id"]) for row in rows]


@app.get("/api/geo/search")
def search_locations(q: str, user: sqlite3.Row = Depends(current_user)) -> list[dict]:
    query = q.strip()
    if len(query) < 2:
        return []
    try:
        response = httpx.get("https://nominatim.openstreetmap.org/search", params={"q": query, "format": "jsonv2", "limit": 6, "accept-language": "zh-CN"}, headers={"User-Agent": "SyncMate/1.0 location search"}, timeout=12)
        response.raise_for_status()
        rows = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(status_code=502, detail="地图地点搜索暂时不可用") from error
    return [{"name": row.get("display_name", "").split(",")[0] or query, "address": row.get("display_name", ""), "lat": float(row["lat"]), "lng": float(row["lon"])} for row in rows if row.get("lat") and row.get("lon")]


@app.post("/api/groups/{group_id}/location")
def save_member_location(group_id: int, body: LocationBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        membership(connection, group_id, user["id"])
        connection.execute("INSERT INTO member_locations(group_id, user_id, lat, lng, updated_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(group_id, user_id) DO UPDATE SET lat = excluded.lat, lng = excluded.lng, updated_at = CURRENT_TIMESTAMP", (group_id, user["id"], body.lat, body.lng))
    return {"ok": True}


@app.post("/api/groups/{group_id}/activities", status_code=201)
def create_activity(group_id: int, body: ActivityBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    if body.mode not in {"fixed", "poll"}:
        raise HTTPException(status_code=400, detail="活动类型无效")
    if body.mode == "fixed" and (not body.items or not body.start_at or not body.end_at):
        raise HTTPException(status_code=400, detail="固定活动需要时间范围和至少一个小活动")
    if body.mode == "poll" and len(body.slots) < 2:
        raise HTTPException(status_code=400, detail="投票活动至少需要两个时间段")
    values = body.items if body.mode == "fixed" else body.slots
    for item in values:
        validate_time_range(item.start_at, item.end_at)
    if body.mode == "fixed":
        validate_time_range(body.start_at, body.end_at)
        overall_start = datetime.fromisoformat(body.start_at.replace("Z", "+00:00"))
        overall_end = datetime.fromisoformat(body.end_at.replace("Z", "+00:00"))
        if any(datetime.fromisoformat(item.start_at.replace("Z", "+00:00")) < overall_start or datetime.fromisoformat(item.end_at.replace("Z", "+00:00")) > overall_end for item in body.items):
            raise HTTPException(status_code=400, detail="小活动时间必须位于活动总时间内")
    with db() as connection:
        require_role(connection, group_id, user["id"], {"owner", "admin"})
        status = "published" if body.mode == "fixed" else "open"
        cursor = connection.execute(
            """INSERT INTO activities(group_id, creator_id, title, description, mode, status, start_at, end_at, form, notice, published_at, budget_per_person)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (group_id, user["id"], body.title.strip(), body.description.strip(), body.mode, status, body.start_at, body.end_at, body.form.strip(), body.notice.strip(), datetime.now(timezone.utc).isoformat() if status == "published" else None, body.budget_per_person),
        )
        activity_id = cursor.lastrowid
        if body.mode == "poll" and len(body.locations) < 2:
            raise HTTPException(status_code=400, detail="地点投票至少需要两个候选地点")
        if body.mode == "fixed" and len(body.locations) > 1:
            raise HTTPException(status_code=400, detail="固定活动只能选择一个地点")
        for index, location in enumerate(body.locations):
            connection.execute("INSERT INTO activity_locations(activity_id, name, address, lat, lng, budget_per_person, opening_hours, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (activity_id, location.name.strip(), location.address.strip(), location.lat, location.lng, location.budget_per_person, location.opening_hours.strip(), index))
        if body.mode == "fixed" and body.locations:
            connection.execute("UPDATE activities SET location_id = (SELECT id FROM activity_locations WHERE activity_id = ? ORDER BY sort_order, id LIMIT 1) WHERE id = ?", (activity_id, activity_id))
        table = "activity_items" if body.mode == "fixed" else "activity_slots"
        for index, item in enumerate(values):
            if body.mode == "fixed":
                connection.execute(f"INSERT INTO {table}(activity_id, title, start_at, end_at, note, sort_order) VALUES (?, ?, ?, ?, ?, ?)", (activity_id, item.title.strip(), item.start_at, item.end_at, item.note.strip(), index))
            else:
                connection.execute(f"INSERT INTO {table}(activity_id, start_at, end_at, suggestion, sort_order) VALUES (?, ?, ?, ?, ?)", (activity_id, item.start_at, item.end_at, item.title.strip(), index))
        audit(connection, group_id, user["id"], "activity_created", f"创建了{'投票' if body.mode == 'poll' else '固定'}活动“{body.title.strip()}”")
        row = connection.execute("SELECT * FROM activities WHERE id = ?", (activity_id,)).fetchone()
        return activity_json(connection, row, user["id"])


@app.post("/api/groups/{group_id}/activities/{activity_id}/vote")
def vote_activity(group_id: int, activity_id: int, body: VoteBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        membership(connection, group_id, user["id"])
        activity = connection.execute("SELECT * FROM activities WHERE id = ? AND group_id = ?", (activity_id, group_id)).fetchone()
        if not activity or activity["mode"] != "poll" or activity["status"] != "open":
            raise HTTPException(status_code=400, detail="该活动当前不可投票")
        valid_slots = {row["id"] for row in connection.execute("SELECT id FROM activity_slots WHERE activity_id = ?", (activity_id,)).fetchall()}
        valid_locations = {row["id"] for row in connection.execute("SELECT id FROM activity_locations WHERE activity_id = ?", (activity_id,)).fetchall()}
        submitted_slots = {int(choice.get("slot_id", 0)) for choice in body.choices}
        if submitted_slots != valid_slots:
            raise HTTPException(status_code=400, detail="请填写每一个候选时间段")
        location_choice = body.location_choices[0] if body.location_choices else None
        if valid_locations and (not location_choice or int(location_choice.get("location_id", 0)) not in valid_locations):
            raise HTTPException(status_code=400, detail="请选择一个候选地点")
        connection.execute("DELETE FROM activity_votes WHERE activity_id = ? AND user_id = ?", (activity_id, user["id"]))
        for choice in body.choices:
            slot_id = int(choice.get("slot_id", 0))
            if slot_id not in valid_slots:
                continue
            connection.execute("INSERT INTO activity_votes(activity_id, slot_id, user_id, available, suggestion) VALUES (?, ?, ?, ?, ?)", (activity_id, slot_id, user["id"], int(bool(choice.get("available"))), str(choice.get("suggestion", ""))[:300]))
        if location_choice:
            connection.execute("INSERT INTO activity_location_votes(activity_id, location_id, user_id, suggestion) VALUES (?, ?, ?, ?) ON CONFLICT(activity_id, user_id) DO UPDATE SET location_id = excluded.location_id, suggestion = excluded.suggestion, updated_at = CURRENT_TIMESTAMP", (activity_id, int(location_choice["location_id"]), user["id"], str(location_choice.get("suggestion", ""))[:300]))
        audit(connection, group_id, user["id"], "activity_voted", f"提交了活动“{activity['title']}”的时间投票")
        return activity_json(connection, activity, user["id"])


@app.post("/api/groups/{group_id}/activities/{activity_id}/end-vote")
def end_activity_vote(group_id: int, activity_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        require_role(connection, group_id, user["id"], {"owner", "admin"})
        activity = connection.execute("SELECT * FROM activities WHERE id = ? AND group_id = ? AND mode = 'poll' AND status = 'open'", (activity_id, group_id)).fetchone()
        if not activity:
            raise HTTPException(status_code=404, detail="投票活动不存在或已结束")
        connection.execute("UPDATE activities SET status = 'ended' WHERE id = ?", (activity_id,))
        audit(connection, group_id, user["id"], "activity_vote_ended", f"结束了活动“{activity['title']}”投票")
        return activity_json(connection, connection.execute("SELECT * FROM activities WHERE id = ?", (activity_id,)).fetchone(), user["id"])


@app.post("/api/groups/{group_id}/activities/{activity_id}/publish")
def publish_activity(group_id: int, activity_id: int, body: PublishBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        require_role(connection, group_id, user["id"], {"owner"})
        activity = connection.execute("SELECT * FROM activities WHERE id = ? AND group_id = ? AND mode = 'poll' AND status = 'ended'", (activity_id, group_id)).fetchone()
        if not activity:
            raise HTTPException(status_code=404, detail="投票活动不存在")
        if not body.items:
            raise HTTPException(status_code=400, detail="发布活动需要至少一个小活动")
        if body.location_id is not None:
            location = connection.execute("SELECT id FROM activity_locations WHERE id = ? AND activity_id = ?", (body.location_id, activity_id)).fetchone()
            if not location:
                raise HTTPException(status_code=400, detail="最终地点无效")
        for item in body.items:
            validate_time_range(item.start_at, item.end_at)
        connection.execute("DELETE FROM activity_items WHERE activity_id = ?", (activity_id,))
        absence_lines = []
        for index, item in enumerate(body.items):
            connection.execute("INSERT INTO activity_items(activity_id, title, start_at, end_at, note, sort_order) VALUES (?, ?, ?, ?, ?, ?)", (activity_id, item.title.strip(), item.start_at, item.end_at, item.note.strip(), index))
            slot = connection.execute("SELECT id FROM activity_slots WHERE activity_id = ? AND start_at = ? AND end_at = ?", (activity_id, item.start_at, item.end_at)).fetchone()
            if slot:
                absent = connection.execute(
                    """SELECT COALESCE(memberships.group_nickname, users.nickname) AS name FROM memberships
                    JOIN users ON users.id = memberships.user_id
                    LEFT JOIN activity_votes ON activity_votes.user_id = users.id AND activity_votes.activity_id = ? AND activity_votes.slot_id = ?
                    WHERE memberships.group_id = ? AND COALESCE(activity_votes.available, 0) = 0 ORDER BY users.id""", (activity_id, slot["id"], group_id),
                ).fetchall()
                if absent:
                    absence_lines.append(f"缺席提醒：{', '.join(row['name'] for row in absent)} 无法参加“{item.title.strip()}”")
            else:
                absence_lines.append(f"出席提醒：“{item.title.strip()}”采用了新时间，请全体成员重新确认是否参加")
        start_at = min(item.start_at for item in body.items)
        end_at = max(item.end_at for item in body.items)
        notice = "\n".join(part for part in [body.notice.strip(), *absence_lines] if part)
        connection.execute("UPDATE activities SET status = 'published', start_at = ?, end_at = ?, notice = ?, published_at = ?, location_id = COALESCE(?, location_id) WHERE id = ?", (start_at, end_at, notice, datetime.now(timezone.utc).isoformat(), body.location_id, activity_id))
        audit(connection, group_id, user["id"], "activity_published", f"正式发布了活动“{activity['title']}”")
        row = connection.execute("SELECT * FROM activities WHERE id = ?", (activity_id,)).fetchone()
        return activity_json(connection, row, user["id"])


def ai_bill_json(connection: sqlite3.Connection, row: sqlite3.Row, user_id: int) -> dict:
    transfers = connection.execute(
        """SELECT ai_bill_transfers.*, fu.nickname AS from_nickname, tu.nickname AS to_nickname
        FROM ai_bill_transfers JOIN users fu ON fu.id = from_user_id JOIN users tu ON tu.id = to_user_id
        WHERE bill_id = ? ORDER BY id""", (row["id"],),
    ).fetchall()
    payload = json.loads(row["result_json"])
    transfer_payload = [dict(item) for item in transfers]
    my_transfers = [item for item in transfer_payload if int(item["from_user_id"]) == int(user_id)]
    if not my_transfers:
        my_payment_status = "not_required"
    elif all(item["status"] == "completed" for item in my_transfers):
        my_payment_status = "paid"
    else:
        my_payment_status = "unpaid"
    payload.update({
        "id": row["id"], "group_id": row["group_id"], "title": row["title"],
        "instruction": row["instruction"], "status": row["status"],
        "created_at": row["created_at"], "transfers": transfer_payload,
        "my_payment_status": my_payment_status,
        "my_transfers": my_transfers,
        "all_transfers_completed": bool(transfer_payload) and all(item["status"] == "completed" for item in transfer_payload),
    })
    return payload


def validate_ai_bill_result(result: dict, member_ids: set[int], payer_id: int) -> None:
    bill = result.get("bill") or {}
    total = int(bill.get("total_cents") or 0)
    payers = bill.get("payers") or []
    participants = bill.get("participants") or []
    transfers = result.get("transfers") or []
    if total <= 0:
        raise HTTPException(status_code=422, detail="AI 未能识别出有效的票据总额")
    if payers != [{"user_id": payer_id, "amount_cents": total}]:
        raise HTTPException(status_code=422, detail="实际付款人或付款金额校验失败")
    if sum(int(item.get("amount_cents") or 0) for item in participants) != total:
        raise HTTPException(status_code=422, detail="成员承担金额合计与票据总额不一致")
    referenced_ids = {
        *(int(item.get("user_id") or 0) for item in payers),
        *(int(item.get("user_id") or 0) for item in participants),
        *(int(item.get("from_user_id") or 0) for item in transfers),
        *(int(item.get("to_user_id") or 0) for item in transfers),
    }
    if not referenced_ids.issubset(member_ids):
        raise HTTPException(status_code=422, detail="分账结果包含不属于目标群组的成员")


@app.post("/api/groups/{group_id}/ai-bills/analyze", status_code=201)
async def analyze_ai_bill(
    group_id: int,
    instruction: str = Form(...),
    payer_id: int = Form(...),
    files: list[UploadFile] = File(...),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    skill = load_receipt_helper()
    with db() as connection:
        membership(connection, group_id, user["id"])
        payer = membership(connection, group_id, payer_id)
        members = connection.execute(
            """SELECT users.id, users.nickname, users.username, memberships.group_nickname
            FROM memberships JOIN users ON users.id = memberships.user_id WHERE memberships.group_id = ? ORDER BY users.id""", (group_id,),
        ).fetchall()
        member_payload = [dict(row) for row in members]
        member_ids = {int(row["id"]) for row in members}
    images = []
    for uploaded in files:
        if not uploaded.content_type or not uploaded.content_type.startswith("image/"):
            raise HTTPException(status_code=422, detail=f"{uploaded.filename or '文件'} 不是图片")
        raw = await uploaded.read()
        images.append({"filename": uploaded.filename or "receipt", "content_type": uploaded.content_type, "content_base64": base64.b64encode(raw).decode("ascii")})
    try:
        result = skill.analyze_receipts(images, instruction, member_payload, current_user_id=user["id"], actual_payer_id=payer["user_id"])
    except skill.ReceiptSplitError as error:
        raise HTTPException(status_code=422, detail={"code": error.code, "message": error.message, "details": error.details}) from error
    validate_ai_bill_result(result, member_ids, int(payer["user_id"]))
    with db() as connection:
        cursor = connection.execute("INSERT INTO ai_bills(group_id, creator_id, title, instruction, result_json) VALUES (?, ?, ?, ?, ?)", (group_id, user["id"], result["bill"]["title"], instruction.strip(), json.dumps(result, ensure_ascii=False)))
        bill_id = cursor.lastrowid
        for transfer in result["transfers"]:
            connection.execute("INSERT INTO ai_bill_transfers(bill_id, from_user_id, to_user_id, amount_cents) VALUES (?, ?, ?, ?)", (bill_id, transfer["from_user_id"], transfer["to_user_id"], transfer["amount_cents"]))
        row = connection.execute("SELECT * FROM ai_bills WHERE id = ?", (bill_id,)).fetchone()
        audit(connection, group_id, user["id"], "ai_bill_analyzed", f"AI 生成了分账方案“{result['bill']['title']}”")
        return ai_bill_json(connection, row, user["id"])


@app.get("/api/groups/{group_id}/ai-bills")
def list_ai_bills(group_id: int, user: sqlite3.Row = Depends(current_user)) -> list[dict]:
    with db() as connection:
        membership(connection, group_id, user["id"])
        rows = connection.execute("SELECT * FROM ai_bills WHERE group_id = ? AND status != 'archived' ORDER BY id DESC", (group_id,)).fetchall()
        return [ai_bill_json(connection, row, user["id"]) for row in rows]


@app.get("/api/ai-bills")
def list_my_ai_bills(user: sqlite3.Row = Depends(current_user)) -> list[dict]:
    """Return one record per AI bill across all groups the current user belongs to."""
    with db() as connection:
        rows = connection.execute(
            """SELECT ai_bills.*, groups_table.name AS group_name
            FROM ai_bills
            JOIN groups_table ON groups_table.id = ai_bills.group_id
            JOIN memberships ON memberships.group_id = ai_bills.group_id AND memberships.user_id = ?
            WHERE groups_table.is_dissolved = 0
            ORDER BY ai_bills.id DESC""",
            (user["id"],),
        ).fetchall()
        records = []
        for row in rows:
            record = ai_bill_json(connection, row, user["id"])
            record["group_name"] = row["group_name"]
            if row["status"] == "pending":
                record["workflow_status"] = "pending_confirmation"
            elif row["status"] == "archived":
                record["workflow_status"] = "archived"
            elif record["my_payment_status"] == "unpaid":
                record["workflow_status"] = "unpaid"
            else:
                record["workflow_status"] = "active"
            records.append(record)
        return records


@app.post("/api/groups/{group_id}/ai-bills/{bill_id}/activate")
def activate_ai_bill(group_id: int, bill_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        require_role(connection, group_id, user["id"], {"owner"})
        row = connection.execute("SELECT * FROM ai_bills WHERE id = ? AND group_id = ? AND status = 'pending'", (bill_id, group_id)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="分账方案不存在或已确认")
        payload = json.loads(row["result_json"])
        group_member_ids = {int(item["user_id"]) for item in connection.execute("SELECT user_id FROM memberships WHERE group_id = ?", (group_id,)).fetchall()}
        payer_rows = payload.get("bill", {}).get("payers") or []
        if len(payer_rows) != 1:
            raise HTTPException(status_code=422, detail="分账方案付款人数据无效，请重新生成")
        payer_id = int(payer_rows[0].get("user_id") or 0)
        persisted_transfers = [dict(item) for item in connection.execute("SELECT from_user_id, to_user_id, amount_cents FROM ai_bill_transfers WHERE bill_id = ? ORDER BY id", (bill_id,)).fetchall()]
        expected_transfers = [{key: int(item.get(key) or 0) for key in ("from_user_id", "to_user_id", "amount_cents")} for item in (payload.get("transfers") or [])]
        validate_ai_bill_result(payload, group_member_ids, payer_id)
        if persisted_transfers != expected_transfers:
            raise HTTPException(status_code=422, detail="分账现金流数据校验失败，请重新生成")
        connection.execute("UPDATE ai_bills SET status = 'active' WHERE id = ?", (bill_id,))
        audit(connection, group_id, user["id"], "ai_bill_activated", f"确认了 AI 分账方案“{row['title']}”")
        return ai_bill_json(connection, connection.execute("SELECT * FROM ai_bills WHERE id = ?", (bill_id,)).fetchone(), user["id"])


@app.post("/api/groups/{group_id}/ai-bills/{bill_id}/transfers/{transfer_id}/complete")
def complete_ai_transfer(group_id: int, bill_id: int, transfer_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        membership(connection, group_id, user["id"])
        row = connection.execute("SELECT * FROM ai_bill_transfers WHERE id = ? AND bill_id = ?", (transfer_id, bill_id)).fetchone()
        if not row or row["from_user_id"] != user["id"]:
            raise HTTPException(status_code=403, detail="只能确认自己发起的转账")
        bill = connection.execute("SELECT * FROM ai_bills WHERE id = ? AND group_id = ? AND status = 'active'", (bill_id, group_id)).fetchone()
        if not bill:
            raise HTTPException(status_code=400, detail="分账方案尚未激活")
        connection.execute("UPDATE ai_bill_transfers SET status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE id = ?", (transfer_id,))
        return ai_bill_json(connection, bill, user["id"])


@app.post("/api/groups/{group_id}/ai-bills/{bill_id}/archive")
def archive_ai_bill(group_id: int, bill_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        require_role(connection, group_id, user["id"], {"owner"})
        row = connection.execute("SELECT * FROM ai_bills WHERE id = ? AND group_id = ? AND status = 'active'", (bill_id, group_id)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="分账方案不存在或尚未激活")
        pending = connection.execute("SELECT COUNT(*) FROM ai_bill_transfers WHERE bill_id = ? AND status != 'completed'", (bill_id,)).fetchone()[0]
        if pending:
            raise HTTPException(status_code=409, detail=f"还有 {pending} 笔转账未完成")
        connection.execute("UPDATE ai_bills SET status = 'archived', archived_at = CURRENT_TIMESTAMP WHERE id = ?", (bill_id,))
        audit(connection, group_id, user["id"], "ai_bill_archived", f"归档了 AI 分账方案“{row['title']}”")
        return {"ok": True}


@app.post("/api/groups/{group_id}/logs/{log_id}/undo")
def undo_log(group_id: int, log_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        require_role(connection, group_id, user["id"], {"owner", "admin"})
        log = connection.execute("SELECT * FROM audit_logs WHERE id = ? AND group_id = ? AND undoable = 1 AND undone = 0", (log_id, group_id)).fetchone()
        if not log:
            raise HTTPException(status_code=404, detail="该操作不可撤销或已经撤销")
        before = json.loads(log["before_data"] or "{}")
        if log["action"] == "group_updated":
            connection.execute(
                """UPDATE groups_table SET name = ?, type = ?, announcement = ?, theme_color = ?, color = ?, cover_style = ?, join_requires_approval = ? WHERE id = ?""",
                (before["name"], before["type"], before["announcement"], before["theme_color"], before["theme_color"], before["cover_style"], before["join_requires_approval"], group_id),
            )
        elif log["action"] == "member_updated":
            connection.execute("UPDATE memberships SET role = ?, group_nickname = ?, member_note = ? WHERE group_id = ? AND user_id = ?", (before["role"], before["group_nickname"], before["member_note"], group_id, log["target_id"]))
        elif log["action"] == "member_removed":
            connection.execute(
                """INSERT OR IGNORE INTO memberships(group_id, user_id, role, group_nickname, member_note, joined_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (group_id, log["target_id"], before["role"], before["group_nickname"], before["member_note"], before["joined_at"]),
            )
        else:
            raise HTTPException(status_code=400, detail="暂不支持撤销该操作")
        connection.execute("UPDATE audit_logs SET undone = 1 WHERE id = ?", (log_id,))
        audit(connection, group_id, user["id"], "operation_undone", f"撤销了操作：{log['summary']}")
        return {"ok": True}


@app.get("/api/dashboard")
def dashboard(user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        expenses = connection.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM transactions WHERE user_id = ? AND direction = 'expense'",
            (user["id"],),
        ).fetchone()["total"]
        income = connection.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM transactions WHERE user_id = ? AND direction = 'income'",
            (user["id"],),
        ).fetchone()["total"]
        pending_bills = connection.execute(
            """SELECT bills.id, bills.title, bills.amount, groups_table.name AS group_name
            FROM bills JOIN groups_table ON groups_table.id = bills.group_id
            JOIN memberships ON memberships.group_id = groups_table.id
            WHERE memberships.user_id = ? AND bills.status = 'pending'""",
            (user["id"],),
        ).fetchall()
        payments = connection.execute(
            """SELECT payments.id, payments.amount, payments.status, groups_table.name AS group_name
            FROM payments JOIN groups_table ON groups_table.id = payments.group_id
            WHERE (from_user_id = ? OR to_user_id = ?) AND payments.status != 'confirmed'""",
            (user["id"], user["id"]),
        ).fetchall()
        transaction_rows = connection.execute(
            """SELECT transactions.*, groups_table.name AS group_name FROM transactions
            LEFT JOIN groups_table ON groups_table.id = transactions.group_id
            WHERE user_id = ? ORDER BY transactions.id DESC LIMIT 6""",
            (user["id"],),
        ).fetchall()
        activity_notifications = connection.execute(
            """SELECT activities.id, activities.group_id, activities.title, activities.status, groups_table.name AS group_name
            FROM activities JOIN groups_table ON groups_table.id = activities.group_id
            WHERE groups_table.owner_id = ? AND activities.mode = 'poll' AND activities.status IN ('open','ended')
            AND (SELECT COUNT(DISTINCT activity_votes.user_id) FROM activity_votes WHERE activity_votes.activity_id = activities.id)
                >= (SELECT COUNT(*) FROM memberships WHERE memberships.group_id = activities.group_id)
            ORDER BY activities.id DESC""", (user["id"],),
        ).fetchall()
        ai_bill_notifications = connection.execute(
            """SELECT ai_bills.id, ai_bills.group_id, ai_bills.title, ai_bills.status,
            groups_table.name AS group_name,
            json_extract(ai_bills.result_json, '$.bill.total_cents') AS total_cents
            FROM ai_bills
            JOIN groups_table ON groups_table.id = ai_bills.group_id
            JOIN memberships ON memberships.group_id = ai_bills.group_id AND memberships.user_id = ?
            WHERE ai_bills.status != 'archived'
            AND (
                (ai_bills.status = 'pending' AND memberships.role = 'owner')
                OR (ai_bills.status = 'active' AND EXISTS (
                    SELECT 1 FROM ai_bill_transfers
                    WHERE ai_bill_transfers.bill_id = ai_bills.id
                    AND ai_bill_transfers.from_user_id = ?
                    AND ai_bill_transfers.status != 'completed'
                ))
            )
            ORDER BY ai_bills.id DESC""", (user["id"], user["id"]),
        ).fetchall()
    return {
        "stats": {"expense": round(expenses, 2), "income": round(income, 2), "net": round(expenses - income, 2)},
        "pending_bills": [dict(row) for row in pending_bills],
        "pending_payments": [dict(row) for row in payments],
        "transactions": [dict(row) for row in transaction_rows],
        "activity_notifications": [dict(row) for row in activity_notifications],
        "ai_bill_notifications": [dict(row) for row in ai_bill_notifications],
    }


@app.get("/api/calendar")
def calendar(user: sqlite3.Row = Depends(current_user)) -> list[dict]:
    with db() as connection:
        rows = connection.execute(
            """SELECT activities.*, groups_table.name AS group_name FROM activities
            JOIN memberships ON memberships.group_id = activities.group_id AND memberships.user_id = ?
            JOIN groups_table ON groups_table.id = activities.group_id
            WHERE activities.status = 'published' ORDER BY activities.start_at, activities.id""", (user["id"],),
        ).fetchall()
        now = datetime.now(timezone.utc)
        result = []
        for row in rows:
            activity = {**activity_json(connection, connection.execute("SELECT * FROM activities WHERE id = ?", (row["id"],)).fetchone(), user["id"]), "group_name": row["group_name"]}
            activity.update({"calendar_type": "confirmed_activity", "is_confirmed": True, "reminder_at": activity.get("start_at")})
            try:
                start = datetime.fromisoformat((activity.get("start_at") or "").replace("Z", "+00:00"))
                activity["reminder_label"] = "即将开始" if start <= now + timedelta(hours=24) else "已加入日程"
            except (TypeError, ValueError):
                activity["reminder_label"] = "已加入日程"
            result.append(activity)
        return result


@app.get("/api/calendar/availability")
def list_calendar_availability(group_id: int | None = None, user: sqlite3.Row = Depends(current_user)) -> list[dict]:
    """List the current user's free slots, or group-visible slots for a group."""
    with db() as connection:
        if group_id is None:
            rows = connection.execute(
                """SELECT calendar_availability.*, NULL AS group_name, 1 AS is_mine
                FROM calendar_availability WHERE user_id = ? ORDER BY start_at""", (user["id"],)
            ).fetchall()
        else:
            membership(connection, group_id, user["id"])
            rows = connection.execute(
                """SELECT calendar_availability.*, groups_table.name AS group_name,
                CASE WHEN calendar_availability.user_id = ? THEN 1 ELSE 0 END AS is_mine,
                COALESCE(memberships.group_nickname, users.nickname) AS user_name
                FROM calendar_availability
                JOIN memberships ON memberships.group_id = ? AND memberships.user_id = calendar_availability.user_id
                JOIN users ON users.id = calendar_availability.user_id
                LEFT JOIN groups_table ON groups_table.id = calendar_availability.group_id
                WHERE (calendar_availability.user_id = ?)
                   OR (calendar_availability.visibility = 'group' AND (calendar_availability.group_id IS NULL OR calendar_availability.group_id = ?))
                ORDER BY start_at""", (user["id"], group_id, user["id"], group_id)
            ).fetchall()
        return [dict(row) for row in rows]


@app.post("/api/calendar/availability", status_code=201)
def create_calendar_availability(body: AvailabilityBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    validate_time_range(body.start_at, body.end_at)
    if body.visibility == "group" and body.group_id is None:
        raise HTTPException(status_code=400, detail="群友可见的空闲时间需要选择群组")
    with db() as connection:
        if body.group_id is not None:
            membership(connection, body.group_id, user["id"])
        cursor = connection.execute(
            """INSERT INTO calendar_availability(user_id, group_id, start_at, end_at, visibility, note)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (user["id"], body.group_id if body.visibility == "group" else None, body.start_at, body.end_at, body.visibility, body.note.strip()),
        )
        row = connection.execute("SELECT * FROM calendar_availability WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return dict(row)


@app.delete("/api/calendar/availability/{slot_id}")
def delete_calendar_availability(slot_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        row = connection.execute("SELECT * FROM calendar_availability WHERE id = ? AND user_id = ?", (slot_id, user["id"])).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="空闲时间不存在")
        connection.execute("DELETE FROM calendar_availability WHERE id = ?", (slot_id,))
        return {"ok": True}


initialize_database()
