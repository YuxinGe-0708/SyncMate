from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("SYNCMATE_DB_PATH", BASE_DIR / "syncmate.db"))
AVATAR_COLORS = {"rose", "mint", "violet", "orange", "blue"}

app = FastAPI(title="SyncMate API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
        """
    )
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
            if actor["role"] != "owner" or member_id == user["id"] or body.role not in {"admin", "member", "temporary"}:
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
        if not target or target["role"] == "temporary":
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
    return {
        "stats": {"expense": round(expenses, 2), "income": round(income, 2), "net": round(expenses - income, 2)},
        "pending_bills": [dict(row) for row in pending_bills],
        "pending_payments": [dict(row) for row in payments],
        "transactions": [dict(row) for row in transaction_rows],
    }


initialize_database()
