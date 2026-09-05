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
import httpx
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


class ExpenseLocationBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    address: str = Field(default="", max_length=500)
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


class TravelPlanBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    destination: str = Field(min_length=1, max_length=200)
    start_date: str
    end_date: str
    departure_city: str = Field(default="", max_length=120)
    default_start_point: str = Field(default="", max_length=200)
    default_transport: str = Field(default="drive", max_length=30)
    estimated_people: int = Field(default=1, ge=1, le=1000)
    budget_cents: int = Field(default=0, ge=0, le=1000000000)
    budget: float | None = Field(default=None, ge=0, le=10000000)
    notes: str = Field(default="", max_length=2000)


class TravelPlanUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    destination: str | None = Field(default=None, min_length=1, max_length=200)
    start_date: str | None = None
    end_date: str | None = None
    departure_city: str | None = Field(default=None, max_length=120)
    default_start_point: str | None = Field(default=None, max_length=200)
    default_transport: str | None = Field(default=None, max_length=30)
    estimated_people: int | None = Field(default=None, ge=1, le=1000)
    budget_cents: int | None = Field(default=None, ge=0, le=1000000000)
    budget: float | None = Field(default=None, ge=0, le=10000000)
    status: str | None = Field(default=None, pattern="^(draft|planning|pending|published|ended|archived)$")
    notes: str | None = Field(default=None, max_length=2000)


class TravelPlaceBody(BaseModel):
    type: str = Field(default="other", pattern="^(attraction|hotel|restaurant|shopping|meeting|other)$")
    name: str = Field(min_length=1, max_length=160)
    address: str = Field(default="", max_length=500)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    provider_place_id: str = Field(default="", max_length=160)
    opening_hours: str = Field(default="", max_length=300)
    avg_cost: float | None = Field(default=None, ge=0, le=1000000)
    phone: str = Field(default="", max_length=60)
    rating: float | None = Field(default=None, ge=0, le=5)
    must_visit: bool = False
    note: str = Field(default="", max_length=1000)
    image_url: str = Field(default="", max_length=1000)


class TravelPlaceUpdateBody(BaseModel):
    type: str | None = Field(default=None, pattern="^(attraction|hotel|restaurant|shopping|meeting|other)$")
    name: str | None = Field(default=None, min_length=1, max_length=160)
    address: str | None = Field(default=None, max_length=500)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    provider_place_id: str | None = Field(default=None, max_length=160)
    opening_hours: str | None = Field(default=None, max_length=300)
    avg_cost: float | None = Field(default=None, ge=0, le=1000000)
    phone: str | None = Field(default=None, max_length=60)
    rating: float | None = Field(default=None, ge=0, le=5)
    must_visit: bool | None = None
    note: str | None = Field(default=None, max_length=1000)
    image_url: str | None = Field(default=None, max_length=1000)


class TravelDayBody(BaseModel):
    travel_date: str
    title: str = Field(default="", max_length=160)
    start_at: str | None = None
    end_at: str | None = None
    start_place_id: int | None = None
    end_place_id: int | None = None
    transport: str = Field(default="drive", max_length=30)
    budget_cents: int = Field(default=0, ge=0, le=1000000000)
    notes: str = Field(default="", max_length=2000)
    status: str = Field(default="draft", pattern="^(draft|confirmed)$")


class TravelDayUpdateBody(BaseModel):
    travel_date: str | None = None
    title: str | None = Field(default=None, max_length=160)
    start_at: str | None = None
    end_at: str | None = None
    start_place_id: int | None = None
    end_place_id: int | None = None
    transport: str | None = Field(default=None, max_length=30)
    budget_cents: int | None = Field(default=None, ge=0, le=1000000000)
    notes: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, pattern="^(draft|confirmed)$")


class TravelRouteNodeBody(BaseModel):
    place_id: int
    arrival_at: str | None = None
    stay_minutes: int = Field(default=60, ge=0, le=1440)
    depart_at: str | None = None
    transport: str | None = Field(default=None, max_length=30)
    confirmed: bool = True


class TravelRouteBody(BaseModel):
    nodes: list[TravelRouteNodeBody] = Field(default_factory=list, max_length=100)


class TravelAutoPlanBody(BaseModel):
    travel_date: str | None = None
    place_ids: list[int] = Field(default_factory=list, max_length=100)
    max_play_minutes: int = Field(default=600, ge=30, le=1440)
    earliest_start: str = Field(default="09:00", pattern=r"^\d{2}:\d{2}$")
    latest_end: str = Field(default="21:00", pattern=r"^\d{2}:\d{2}$")
    transport: str = Field(default="drive", max_length=30)
    prioritize: str = Field(default="balanced", pattern="^(distance|time|places|comfort|balanced)$")


class TravelApplyPlanBody(BaseModel):
    option_id: str


class TravelMemberLocationBody(BaseModel):
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    address: str = Field(default="", max_length=500)
    participating: bool = True


class TravelPlaceVoteBody(BaseModel):
    suggestion: str = Field(default="", max_length=500)


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
        CREATE TABLE IF NOT EXISTS expense_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bill_id INTEGER NOT NULL REFERENCES ai_bills(id) ON DELETE CASCADE,
            group_id INTEGER NOT NULL REFERENCES groups_table(id) ON DELETE CASCADE,
            receipt_index INTEGER NOT NULL DEFAULT 1,
            merchant_name TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '其他',
            category_breakdown TEXT NOT NULL DEFAULT '{}',
            amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
            spent_at TEXT NOT NULL,
            location_name TEXT,
            address TEXT NOT NULL DEFAULT '',
            lat REAL,
            lng REAL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(bill_id, receipt_index)
        );
        CREATE INDEX IF NOT EXISTS idx_expense_records_group_time
        ON expense_records(group_id, spent_at);
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
        CREATE TABLE IF NOT EXISTS travel_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL REFERENCES groups_table(id) ON DELETE CASCADE,
            creator_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL,
            destination TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            departure_city TEXT NOT NULL DEFAULT '',
            default_start_point TEXT NOT NULL DEFAULT '',
            default_transport TEXT NOT NULL DEFAULT 'drive',
            estimated_people INTEGER NOT NULL DEFAULT 1,
            budget_cents INTEGER NOT NULL DEFAULT 0 CHECK(budget_cents >= 0),
            status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','planning','pending','published','ended','archived')),
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            published_at TEXT,
            archived_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_travel_plans_group ON travel_plans(group_id, updated_at);
        CREATE TABLE IF NOT EXISTS travel_places (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL REFERENCES travel_plans(id) ON DELETE CASCADE,
            type TEXT NOT NULL DEFAULT 'other',
            name TEXT NOT NULL,
            address TEXT NOT NULL DEFAULT '',
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            provider_place_id TEXT NOT NULL DEFAULT '',
            opening_hours TEXT NOT NULL DEFAULT '',
            avg_cost REAL,
            phone TEXT NOT NULL DEFAULT '',
            rating REAL,
            must_visit INTEGER NOT NULL DEFAULT 0,
            note TEXT NOT NULL DEFAULT '',
            image_url TEXT NOT NULL DEFAULT '',
            created_by INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_travel_places_plan ON travel_places(plan_id, id);
        CREATE TABLE IF NOT EXISTS travel_place_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL REFERENCES travel_plans(id) ON DELETE CASCADE,
            place_id INTEGER NOT NULL REFERENCES travel_places(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            suggestion TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(plan_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_travel_place_votes_place ON travel_place_votes(place_id);
        CREATE TABLE IF NOT EXISTS travel_days (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL REFERENCES travel_plans(id) ON DELETE CASCADE,
            travel_date TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            start_at TEXT,
            end_at TEXT,
            start_place_id INTEGER REFERENCES travel_places(id) ON DELETE SET NULL,
            end_place_id INTEGER REFERENCES travel_places(id) ON DELETE SET NULL,
            transport TEXT NOT NULL DEFAULT 'drive',
            budget_cents INTEGER NOT NULL DEFAULT 0 CHECK(budget_cents >= 0),
            notes TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','confirmed')),
            total_distance_km REAL NOT NULL DEFAULT 0 CHECK(total_distance_km >= 0),
            total_duration_min INTEGER NOT NULL DEFAULT 0 CHECK(total_duration_min >= 0),
            route_score REAL,
            activity_id INTEGER REFERENCES activities(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(plan_id, travel_date)
        );
        CREATE INDEX IF NOT EXISTS idx_travel_days_plan ON travel_days(plan_id, travel_date);
        CREATE TABLE IF NOT EXISTS travel_nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day_id INTEGER NOT NULL REFERENCES travel_days(id) ON DELETE CASCADE,
            place_id INTEGER NOT NULL REFERENCES travel_places(id) ON DELETE CASCADE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            arrival_at TEXT,
            stay_minutes INTEGER NOT NULL DEFAULT 60 CHECK(stay_minutes >= 0),
            depart_at TEXT,
            transport TEXT,
            distance_km REAL NOT NULL DEFAULT 0 CHECK(distance_km >= 0),
            duration_min INTEGER NOT NULL DEFAULT 0 CHECK(duration_min >= 0),
            confirmed INTEGER NOT NULL DEFAULT 1,
            opening_conflict INTEGER NOT NULL DEFAULT 0,
            UNIQUE(day_id, sort_order)
        );
        CREATE INDEX IF NOT EXISTS idx_travel_nodes_day ON travel_nodes(day_id, sort_order);
        CREATE TABLE IF NOT EXISTS travel_member_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER NOT NULL REFERENCES travel_plans(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            lat REAL,
            lng REAL,
            address TEXT NOT NULL DEFAULT '',
            participating INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(plan_id, user_id),
            CHECK((participating = 0) OR (lat IS NOT NULL AND lng IS NOT NULL))
        );
        CREATE INDEX IF NOT EXISTS idx_travel_locations_plan ON travel_member_locations(plan_id);
        """
    )
    add_column(connection, "activities", "location_id INTEGER")
    add_column(connection, "activities", "budget_per_person REAL")
    backfill_expense_records(connection)
    connection.execute("UPDATE memberships SET role = 'member' WHERE role = 'temporary'")
    rows = connection.execute("SELECT id, color FROM groups_table WHERE invite_code IS NULL").fetchall()
    for row in rows:
        connection.execute(
            "UPDATE groups_table SET invite_code = ?, invite_expires_at = ?, theme_color = ? WHERE id = ?",
            (secrets.token_hex(4).upper(), (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(), row["color"], row["id"]),
        )


def expense_rows_from_result(result: dict, fallback_title: str, fallback_date: str) -> list[dict]:
    bill = result.get("bill") or {}
    raw_receipts = bill.get("receipts") or (result.get("raw_analysis") or {}).get("receipts") or []
    receipts = [row for row in raw_receipts if isinstance(row, dict)]
    total_cents = int(bill.get("total_cents") or 0)
    if not receipts and total_cents > 0:
        receipts = [{"receipt_index": 1, "merchant": fallback_title, "total_cents": total_cents}]
    receipt_total = sum(max(0, int(row.get("total_cents") or 0)) for row in receipts)
    if len(receipts) > 1 and total_cents > 0 and receipt_total != total_cents:
        if receipt_total > 0:
            normalized = [total_cents * max(0, int(row.get("total_cents") or 0)) // receipt_total for row in receipts]
            normalized[max(range(len(normalized)), key=lambda index: normalized[index])] += total_cents - sum(normalized)
        else:
            normalized = [total_cents // len(receipts) for _ in receipts]
            normalized[0] += total_cents - sum(normalized)
        receipts = [{**row, "total_cents": normalized[index]} for index, row in enumerate(receipts)]
    bill_category = str(bill.get("category") or "其他")
    items = [row for row in (bill.get("items") or []) if isinstance(row, dict)]
    spent_at = str(bill.get("bill_date") or fallback_date)[:10]
    try:
        datetime.strptime(spent_at, "%Y-%m-%d")
    except ValueError:
        spent_at = fallback_date[:10]
    records = []
    used_receipt_indices: set[int] = set()
    for position, receipt in enumerate(receipts, start=1):
        receipt_index = int(receipt.get("receipt_index") or position)
        if receipt_index <= 0 or receipt_index in used_receipt_indices:
            receipt_index = position
            while receipt_index in used_receipt_indices:
                receipt_index += 1
        used_receipt_indices.add(receipt_index)
        amount_cents = int(receipt.get("total_cents") or 0)
        if amount_cents <= 0 and len(receipts) == 1:
            amount_cents = total_cents
        if amount_cents <= 0:
            continue
        breakdown: dict[str, int] = {}
        for item in items:
            if int(item.get("receipt_index") or 1) != receipt_index:
                continue
            category = str(item.get("category") or bill_category)
            breakdown[category] = breakdown.get(category, 0) + int(item.get("amount_cents") or 0)
        categorized = sum(breakdown.values())
        if categorized < amount_cents:
            breakdown[bill_category] = breakdown.get(bill_category, 0) + amount_cents - categorized
        elif categorized > amount_cents and categorized:
            # OCR adjustments can make item totals differ by a few cents; scale them back to the receipt total.
            scaled = {key: amount_cents * value // categorized for key, value in breakdown.items()}
            remainder = amount_cents - sum(scaled.values())
            if scaled:
                largest = max(scaled, key=scaled.get)
                scaled[largest] += remainder
            breakdown = scaled
        primary_category = max(breakdown, key=breakdown.get) if breakdown else bill_category
        records.append({
            "receipt_index": receipt_index,
            "merchant_name": str(receipt.get("merchant") or fallback_title),
            "category": primary_category,
            "category_breakdown": breakdown or {bill_category: amount_cents},
            "amount_cents": amount_cents,
            "spent_at": spent_at,
        })
    return records


def persist_expense_records(connection: sqlite3.Connection, bill_id: int, group_id: int, result: dict, title: str, created_at: str) -> None:
    for record in expense_rows_from_result(result, title, created_at):
        connection.execute(
            """INSERT OR IGNORE INTO expense_records(
                bill_id, group_id, receipt_index, merchant_name, category,
                category_breakdown, amount_cents, spent_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                bill_id, group_id, record["receipt_index"], record["merchant_name"],
                record["category"], json.dumps(record["category_breakdown"], ensure_ascii=False),
                record["amount_cents"], record["spent_at"],
            ),
        )


def backfill_expense_records(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """SELECT ai_bills.id, ai_bills.group_id, ai_bills.title, ai_bills.result_json,
        ai_bills.created_at FROM ai_bills
        WHERE NOT EXISTS (SELECT 1 FROM expense_records WHERE bill_id = ai_bills.id)"""
    ).fetchall()
    for row in rows:
        try:
            result = json.loads(row["result_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        persist_expense_records(connection, row["id"], row["group_id"], result, row["title"], row["created_at"])


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


def showcase_seed_enabled() -> bool:
    """Keep demo showcase rows out of isolated test databases.

    The normal local database is seeded automatically.  Deployments using a
    custom database path can opt in with SYNCMATE_SEED_SHOWCASE_DATA=1.
    """
    flag = os.environ.get("SYNCMATE_SEED_SHOWCASE_DATA", "")
    if flag.lower() in {"1", "true", "yes", "on"}:
        return True
    try:
        return DB_PATH.resolve() == (BASE_DIR / "syncmate.db").resolve()
    except OSError:
        return False


def ensure_demo_showcase_data(connection: sqlite3.Connection, owner_id: int) -> None:
    """Create one coherent, idempotent dataset for product demonstrations.

    All rows are real records in the same tables used by the UI and APIs, so
    activities, calendar entries, travel routes, AI bills and finance maps
    remain consistent.  The function intentionally does nothing for test DBs.
    """
    if not showcase_seed_enabled():
        return
    groups = {
        row["name"]: int(row["id"])
        for row in connection.execute(
            "SELECT id, name FROM groups_table WHERE owner_id = ? AND is_dissolved = 0", (owner_id,)
        ).fetchall()
    }
    weekend_id = groups.get("周末聚餐")
    travel_group_id = groups.get("海边两日游")
    if not weekend_id or not travel_group_id:
        return
    member_ids = {
        row["username"]: int(row["id"])
        for row in connection.execute(
            "SELECT id, username FROM users WHERE username IN ('member_lin','member_zhou','member_wang','member_fang','member_jia')"
        ).fetchall()
    }
    travel_members = [owner_id, member_ids.get("member_lin"), member_ids.get("member_zhou")]
    travel_members = [int(value) for value in travel_members if value]
    today = datetime.now(timezone.utc).date()
    trip_start = today + timedelta(days=7)
    trip_end = trip_start + timedelta(days=1)

    # A fixed activity and a completed location/time poll, both visible in the
    # group and in every member's calendar.
    fixed_title = "周末城市漫步 · 演示活动"
    fixed = connection.execute(
        "SELECT id FROM activities WHERE group_id = ? AND title = ?", (weekend_id, fixed_title)
    ).fetchone()
    if not fixed:
        cursor = connection.execute(
            """INSERT INTO activities(
                group_id, creator_id, title, description, mode, status, start_at, end_at,
                form, notice, published_at, budget_per_person
            ) VALUES (?, ?, ?, ?, 'fixed', 'published', ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)""",
            (
                weekend_id, owner_id, fixed_title,
                "一起逛展、吃饭和散步，所有成员都可以查看。",
                f"{trip_start.isoformat()}T10:00", f"{trip_start.isoformat()}T18:00",
                "城市漫步", "请提前 10 分钟到达集合点", 120.0,
            ),
        )
        fixed_id = cursor.lastrowid
        location_cursor = connection.execute(
            """INSERT INTO activity_locations(
                activity_id, name, address, lat, lng, budget_per_person, opening_hours, sort_order
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (fixed_id, "人民广场集合点", "上海市黄浦区人民广场", 31.2304, 121.4737, 120.0, "09:00-22:00"),
        )
        connection.execute("UPDATE activities SET location_id = ? WHERE id = ?", (location_cursor.lastrowid, fixed_id))
        connection.executemany(
            "INSERT INTO activity_items(activity_id, title, start_at, end_at, note, sort_order) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (fixed_id, "上海博物馆参观", f"{trip_start.isoformat()}T10:00", f"{trip_start.isoformat()}T12:00", "提前预约入场", 0),
                (fixed_id, "午餐 AA", f"{trip_start.isoformat()}T12:30", f"{trip_start.isoformat()}T14:00", "餐费按实际账单分摊", 1),
                (fixed_id, "人民公园散步", f"{trip_start.isoformat()}T15:00", f"{trip_start.isoformat()}T18:00", "以群消息为准", 2),
            ],
        )

    poll_title = "周末电影与晚餐 · 已确认"
    poll = connection.execute(
        "SELECT id FROM activities WHERE group_id = ? AND title = ?", (weekend_id, poll_title)
    ).fetchone()
    if not poll:
        cursor = connection.execute(
            """INSERT INTO activities(
                group_id, creator_id, title, description, mode, status, start_at, end_at,
                form, notice, published_at, budget_per_person
            ) VALUES (?, ?, ?, ?, 'poll', 'published', ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)""",
            (
                weekend_id, owner_id, poll_title, "由成员投票后确定的示例活动。",
                f"{(trip_start + timedelta(days=1)).isoformat()}T14:00", f"{(trip_start + timedelta(days=1)).isoformat()}T21:00",
                "电影+晚餐", "投票结果已确认，缺席成员请提前在群内说明", 180.0,
            ),
        )
        poll_id = cursor.lastrowid
        location_rows = []
        for index, location in enumerate([
            ("百丽宫影城", "上海市黄浦区西藏中路", 31.2336, 121.4755, 180.0, "10:00-23:00"),
            ("大光明电影院", "上海市黄浦区南京西路", 31.2328, 121.4688, 160.0, "09:30-22:30"),
        ]):
            location_rows.append(
                connection.execute(
                    """INSERT INTO activity_locations(
                        activity_id, name, address, lat, lng, budget_per_person, opening_hours, sort_order
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (poll_id, *location, index),
                ).lastrowid
            )
        slot_rows = []
        for index, (start, end, suggestion) in enumerate([
            (f"{(trip_start + timedelta(days=1)).isoformat()}T14:00", f"{(trip_start + timedelta(days=1)).isoformat()}T17:00", "下午场"),
            (f"{(trip_start + timedelta(days=1)).isoformat()}T16:00", f"{(trip_start + timedelta(days=1)).isoformat()}T19:00", "傍晚场"),
        ]):
            slot_rows.append(
                connection.execute(
                    "INSERT INTO activity_slots(activity_id, start_at, end_at, suggestion, sort_order) VALUES (?, ?, ?, ?, ?)",
                    (poll_id, start, end, suggestion, index),
                ).lastrowid
            )
        poll_members = [owner_id, *[value for value in member_ids.values() if value]]
        for index, user_id in enumerate(sorted(set(poll_members))):
            selected_slot = slot_rows[index % len(slot_rows)]
            for slot_id in slot_rows:
                connection.execute(
                    "INSERT INTO activity_votes(activity_id, slot_id, user_id, available, suggestion) VALUES (?, ?, ?, ?, ?)",
                    (poll_id, slot_id, user_id, int(slot_id == selected_slot), "时间可以参加" if slot_id == selected_slot else "该时段不便"),
                )
            connection.execute(
                "INSERT INTO activity_location_votes(activity_id, location_id, user_id, suggestion) VALUES (?, ?, ?, ?)",
                (poll_id, location_rows[index % len(location_rows)], user_id, "希望交通方便"),
            )
        connection.execute(
            "INSERT INTO activity_items(activity_id, title, start_at, end_at, note, sort_order) VALUES (?, ?, ?, ?, ?, ?)",
            (poll_id, "电影观影", f"{(trip_start + timedelta(days=1)).isoformat()}T16:00", f"{(trip_start + timedelta(days=1)).isoformat()}T19:00", "最终选择百丽宫影城", 0),
        )
        connection.execute(
            "INSERT INTO activity_items(activity_id, title, start_at, end_at, note, sort_order) VALUES (?, ?, ?, ?, ?, ?)",
            (poll_id, "聚餐交流", f"{(trip_start + timedelta(days=1)).isoformat()}T19:30", f"{(trip_start + timedelta(days=1)).isoformat()}T21:00", "以群内通知为准", 1),
        )
        connection.execute("UPDATE activities SET location_id = ? WHERE id = ?", (location_rows[0], poll_id))

    # A published two-day route in the travel group.  Its route nodes and
    # linked activities are the exact source consumed by the calendar view.
    plan_name = "上海周末文化之旅 · 演示路线"
    plan = connection.execute(
        "SELECT id FROM travel_plans WHERE group_id = ? AND name = ?", (travel_group_id, plan_name)
    ).fetchone()
    if not plan:
        plan_id = connection.execute(
            """INSERT INTO travel_plans(
                group_id, creator_id, name, destination, start_date, end_date,
                departure_city, default_start_point, default_transport, estimated_people,
                budget_cents, status, notes, published_at
            ) VALUES (?, ?, ?, '上海', ?, ?, '杭州', '上海虹桥站', 'metro', ?, ?, 'published', ?, CURRENT_TIMESTAMP)""",
            (travel_group_id, owner_id, plan_name, trip_start.isoformat(), trip_end.isoformat(), len(travel_members), 360000, "路线、预算和共享日程已确认"),
        ).lastrowid
        place_specs = [
            ("hotel", "浦东精品酒店", "上海市浦东新区陆家嘴", 31.2397, 121.4998, 350.0, 4.6, 0),
            ("attraction", "外滩", "上海市黄浦区中山东一路", 31.2397, 121.4998, 0.0, 4.8, 1),
            ("attraction", "豫园", "上海市黄浦区豫园老街", 31.2271, 121.4920, 60.0, 4.7, 1),
            ("restaurant", "本帮菜餐厅", "上海市黄浦区福州路", 31.2324, 121.4749, 120.0, 4.5, 1),
            ("attraction", "朱家角古镇", "上海市青浦区朱家角镇", 31.1070, 121.0560, 80.0, 4.6, 1),
            ("attraction", "西岸艺术中心", "上海市徐汇区龙兰路", 31.1788, 121.4580, 40.0, 4.4, 1),
        ]
        place_ids = {}
        for place_type, name, address, lat, lng, avg_cost, rating, must_visit in place_specs:
            place_ids[name] = connection.execute(
                """INSERT INTO travel_places(
                    plan_id, type, name, address, lat, lng, avg_cost, rating, must_visit, note, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (plan_id, place_type, name, address, lat, lng, avg_cost, rating, must_visit, "演示数据，可直接编辑", owner_id),
            ).lastrowid
        day_specs = [
            (trip_start.isoformat(), "外滩与豫园", f"{trip_start.isoformat()}T09:00", f"{trip_start.isoformat()}T21:00", [
                ("外滩", f"{trip_start.isoformat()}T10:00", 120, f"{trip_start.isoformat()}T12:00", 0.0, 0),
                ("豫园", f"{trip_start.isoformat()}T13:30", 120, f"{trip_start.isoformat()}T15:30", 3.2, 18),
                ("本帮菜餐厅", f"{trip_start.isoformat()}T18:00", 90, f"{trip_start.isoformat()}T19:30", 2.4, 14),
            ], "浦东精品酒店", "浦东精品酒店", 90000),
            (trip_end.isoformat(), "朱家角与艺术之旅", f"{trip_end.isoformat()}T08:30", f"{trip_end.isoformat()}T20:00", [
                ("朱家角古镇", f"{trip_end.isoformat()}T10:00", 180, f"{trip_end.isoformat()}T13:00", 42.0, 65),
                ("西岸艺术中心", f"{trip_end.isoformat()}T16:00", 120, f"{trip_end.isoformat()}T18:00", 38.0, 58),
            ], "浦东精品酒店", "浦东精品酒店", 80000),
        ]
        for travel_date, title, start_at, end_at, nodes, start_name, end_name, budget_cents in day_specs:
            day_id = connection.execute(
                """INSERT INTO travel_days(
                    plan_id, travel_date, title, start_at, end_at, start_place_id, end_place_id,
                    transport, budget_cents, notes, status, total_distance_km, total_duration_min,
                    route_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'metro', ?, ?, 'confirmed', ?, ?, 94.0)""",
                (plan_id, travel_date, title, start_at, end_at, place_ids[start_name], place_ids[end_name], budget_cents, "已确认路线", sum(node[4] for node in nodes), sum(node[2] for node in nodes) + 45 * max(0, len(nodes) - 1) + 30),
            ).lastrowid
            for sort_order, (name, arrival_at, stay_minutes, depart_at, distance_km, duration_min) in enumerate(nodes):
                connection.execute(
                    """INSERT INTO travel_nodes(
                        day_id, place_id, sort_order, arrival_at, stay_minutes, depart_at,
                        transport, distance_km, duration_min, confirmed, opening_conflict
                    ) VALUES (?, ?, ?, ?, ?, ?, 'metro', ?, ?, 1, 0)""",
                    (day_id, place_ids[name], sort_order, arrival_at, stay_minutes, depart_at, distance_km, duration_min),
                )
            activity_id = connection.execute(
                """INSERT INTO activities(
                    group_id, creator_id, title, description, mode, status, start_at, end_at,
                    form, notice, published_at
                ) VALUES (?, ?, ?, '旅行路线已同步', 'fixed', 'published', ?, ?, '旅行路线', ?, CURRENT_TIMESTAMP)""",
                (travel_group_id, owner_id, f"{plan_name} · {travel_date}", start_at, end_at, "已同步旅行路线"),
            ).lastrowid
            for sort_order, (name, arrival_at, stay_minutes, depart_at, _distance_km, _duration_min) in enumerate(nodes):
                connection.execute(
                    "INSERT INTO activity_items(activity_id, title, start_at, end_at, note, sort_order) VALUES (?, ?, ?, ?, ?, ?)",
                    (activity_id, name, arrival_at, depart_at, f"停留 {stay_minutes} 分钟", sort_order),
                )
            connection.execute("UPDATE travel_days SET activity_id = ? WHERE id = ?", (activity_id, day_id))

    # One active AI bill gives the finance map and wallet a real, cross-module
    # record.  Its receipts use current/previous months and actual coordinates.
    bill_title = "上海旅行共同支出 · 演示账单"
    if not connection.execute("SELECT 1 FROM ai_bills WHERE group_id = ? AND title = ?", (travel_group_id, bill_title)).fetchone():
        payer_total = 138000
        participants = [{"user_id": user_id, "amount_cents": payer_total // len(travel_members)} for user_id in travel_members]
        participants[-1]["amount_cents"] += payer_total - sum(item["amount_cents"] for item in participants)
        transfers = [
            {"from_user_id": user_id, "to_user_id": owner_id, "amount_cents": item["amount_cents"]}
            for user_id, item in [(member_id, next(item for item in participants if item["user_id"] == member_id)) for member_id in travel_members if member_id != owner_id]
        ]
        first_of_month = today.replace(day=1)
        previous_date = (first_of_month - timedelta(days=1)).replace(day=15)
        current_date = today.replace(day=max(1, min(today.day, 25)))
        result = {
            "version": "1.0", "status": "ok",
            "bill": {
                "title": bill_title, "category": "旅行", "bill_date": current_date.isoformat(),
                "currency": "CNY", "total_cents": payer_total, "subtotal_cents": payer_total,
                "payers": [{"user_id": owner_id, "amount_cents": payer_total}],
                "participants": participants,
                "items": [
                    {"name": "本帮菜午餐", "amount_cents": 68000, "participant_ids": travel_members, "receipt_index": 1, "claim_mode": "shared", "category": "餐饮"},
                    {"name": "景点门票", "amount_cents": 40000, "participant_ids": travel_members, "receipt_index": 2, "claim_mode": "shared", "category": "门票"},
                    {"name": "酒店预订", "amount_cents": 30000, "participant_ids": travel_members, "receipt_index": 3, "claim_mode": "shared", "category": "住宿"},
                ],
                "receipts": [
                    {"receipt_index": 1, "merchant": "本帮菜餐厅", "total_cents": 68000},
                    {"receipt_index": 2, "merchant": "朱家角古镇", "total_cents": 40000},
                    {"receipt_index": 3, "merchant": "浦东精品酒店", "total_cents": 30000},
                ],
                "split_method": "equal", "ai_generated": True, "requires_confirmation": True, "actual_payer_id": owner_id,
            },
            "transfers": transfers,
            "explanation": "旅行共同支出按参加成员平均分摊，群主先行垫付。",
            "raw_analysis": {"demo": True},
        }
        bill_id = connection.execute(
            "INSERT INTO ai_bills(group_id, creator_id, title, instruction, result_json, status) VALUES (?, ?, ?, ?, ?, 'active')",
            (travel_group_id, owner_id, bill_title, "旅行期间共同支出按参加成员 AA", json.dumps(result, ensure_ascii=False)),
        ).lastrowid
        for transfer in transfers:
            connection.execute(
                "INSERT INTO ai_bill_transfers(bill_id, from_user_id, to_user_id, amount_cents, status) VALUES (?, ?, ?, ?, 'pending')",
                (bill_id, transfer["from_user_id"], transfer["to_user_id"], transfer["amount_cents"]),
            )
        expense_specs = [
            (1, "本帮菜餐厅", "餐饮", {"餐饮": 68000}, 68000, current_date.isoformat(), "本帮菜餐厅", "上海市黄浦区福州路", 31.2324, 121.4749),
            (2, "朱家角古镇", "门票", {"门票": 40000}, 40000, current_date.isoformat(), "朱家角古镇", "上海市青浦区朱家角镇", 31.1070, 121.0560),
            (3, "浦东精品酒店", "住宿", {"住宿": 30000}, 30000, previous_date.isoformat(), "浦东精品酒店", "上海市浦东新区陆家嘴", 31.2397, 121.4998),
        ]
        for receipt_index, merchant, category, breakdown, amount_cents, spent_at, location_name, address, lat, lng in expense_specs:
            connection.execute(
                """INSERT INTO expense_records(
                    bill_id, group_id, receipt_index, merchant_name, category, category_breakdown,
                    amount_cents, spent_at, location_name, address, lat, lng
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (bill_id, travel_group_id, receipt_index, merchant, category, json.dumps(breakdown, ensure_ascii=False), amount_cents, spent_at, location_name, address, lat, lng),
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
            ensure_demo_showcase_data(connection, demo["id"])
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
        ensure_demo_showcase_data(connection, user_id)
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
    headers = {"User-Agent": "SyncMate/1.0 location search"}
    # Photon is an OpenStreetMap-backed geocoder with a permissive public API.
    # Keep Nominatim as a fallback because availability varies by network.
    try:
        # Photon currently rejects `lang=zh`; omit it and preserve the source
        # names/addresses returned by OpenStreetMap instead.
        response = httpx.get("https://photon.komoot.io/api/", params={"q": query, "limit": 6}, headers=headers, timeout=8)
        response.raise_for_status()
        features = response.json().get("features", [])
        results = []
        for feature in features:
            geometry = feature.get("geometry") or {}
            coordinates = geometry.get("coordinates") or []
            properties = feature.get("properties") or {}
            if len(coordinates) < 2:
                continue
            name = properties.get("name") or properties.get("street") or query
            address_parts = [properties.get(key) for key in ("street", "housenumber", "district", "city", "state", "country")]
            address = ", ".join(str(part) for part in address_parts if part) or name
            results.append({"name": name, "address": address, "lat": float(coordinates[1]), "lng": float(coordinates[0])})
        if results:
            return results
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        pass
    try:
        response = httpx.get("https://nominatim.openstreetmap.org/search", params={"q": query, "format": "jsonv2", "limit": 6, "accept-language": "zh-CN"}, headers=headers, timeout=8)
        response.raise_for_status()
        rows = response.json()
        return [{"name": row.get("display_name", "").split(",")[0] or query, "address": row.get("display_name", ""), "lat": float(row["lat"]), "lng": float(row["lon"])} for row in rows if row.get("lat") and row.get("lon")]
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
        raise HTTPException(status_code=502, detail="地图地点搜索暂时不可用，请检查网络或直接在地图上点选") from error


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
        "expense_records": [dict(item) for item in connection.execute(
            "SELECT * FROM expense_records WHERE bill_id = ? ORDER BY receipt_index, id", (row["id"],)
        ).fetchall()],
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
    if not instruction.strip():
        raise HTTPException(status_code=422, detail="请填写分账规则后再开始分析")
    if not files:
        raise HTTPException(status_code=422, detail="请至少上传一张小票图片")
    if len(files) > 8:
        raise HTTPException(status_code=422, detail="最多支持上传 8 张小票图片")
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
        created_at = connection.execute("SELECT created_at FROM ai_bills WHERE id = ?", (bill_id,)).fetchone()["created_at"]
        persist_expense_records(connection, bill_id, group_id, result, result["bill"]["title"], created_at)
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


def previous_month(month: str) -> str:
    parsed = datetime.strptime(month, "%Y-%m")
    return f"{parsed.year - 1}-12" if parsed.month == 1 else f"{parsed.year}-{parsed.month - 1:02d}"


def category_amount(row: sqlite3.Row, category: str | None) -> int:
    if not category:
        return int(row["amount_cents"])
    try:
        breakdown = json.loads(row["category_breakdown"] or "{}")
    except (TypeError, json.JSONDecodeError):
        breakdown = {}
    return int(breakdown.get(category) or (row["amount_cents"] if row["category"] == category else 0))


@app.get("/api/finance/analytics")
def finance_analytics(
    month: str | None = None,
    group_id: int | None = None,
    category: str | None = None,
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    selected_month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    try:
        datetime.strptime(selected_month, "%Y-%m")
    except ValueError as error:
        raise HTTPException(status_code=422, detail="月份格式应为 YYYY-MM") from error
    previous = previous_month(selected_month)
    with db() as connection:
        groups = connection.execute(
            """SELECT groups_table.id, groups_table.name, groups_table.color
            FROM groups_table JOIN memberships ON memberships.group_id = groups_table.id
            WHERE memberships.user_id = ? AND groups_table.is_dissolved = 0
            ORDER BY groups_table.name""", (user["id"],),
        ).fetchall()
        allowed_group_ids = {int(row["id"]) for row in groups}
        if group_id is not None and group_id not in allowed_group_ids:
            raise HTTPException(status_code=403, detail="你不在该群组中")
        parameters: list[object] = [user["id"]]
        group_clause = ""
        if group_id is not None:
            group_clause = " AND expense_records.group_id = ?"
            parameters.append(group_id)
        rows = connection.execute(
            f"""SELECT expense_records.*, groups_table.name AS group_name, ai_bills.status AS bill_status
            FROM expense_records
            JOIN ai_bills ON ai_bills.id = expense_records.bill_id
            JOIN groups_table ON groups_table.id = expense_records.group_id
            JOIN memberships ON memberships.group_id = expense_records.group_id AND memberships.user_id = ?
            WHERE groups_table.is_dissolved = 0 AND ai_bills.status IN ('active', 'archived')
            {group_clause}
            ORDER BY expense_records.spent_at DESC, expense_records.id DESC""", parameters,
        ).fetchall()

    all_categories: set[str] = set()
    for row in rows:
        try:
            all_categories.update(str(key) for key, value in json.loads(row["category_breakdown"] or "{}").items() if int(value or 0) > 0)
        except (TypeError, ValueError, json.JSONDecodeError):
            all_categories.add(row["category"])
    current_rows = [(row, category_amount(row, category)) for row in rows if str(row["spent_at"])[:7] == selected_month]
    previous_rows = [(row, category_amount(row, category)) for row in rows if str(row["spent_at"])[:7] == previous]
    current_rows = [(row, amount) for row, amount in current_rows if amount > 0]
    previous_rows = [(row, amount) for row, amount in previous_rows if amount > 0]
    current_total = sum(amount for _, amount in current_rows)
    previous_total = sum(amount for _, amount in previous_rows)
    change_percent = None if previous_total == 0 else round((current_total - previous_total) / previous_total * 100, 1)

    group_totals: dict[int, dict] = {
        int(row["id"]): {"group_id": row["id"], "group_name": row["name"], "current_cents": 0, "previous_cents": 0}
        for row in groups if group_id is None or int(row["id"]) == group_id
    }
    for period_key, period_rows in (("current_cents", current_rows), ("previous_cents", previous_rows)):
        for row, amount in period_rows:
            if int(row["group_id"]) in group_totals:
                group_totals[int(row["group_id"])][period_key] += amount
    max_group = max((entry["current_cents"] for entry in group_totals.values()), default=0)
    group_heatmap = []
    for entry in sorted(group_totals.values(), key=lambda item: item["current_cents"], reverse=True):
        entry["intensity"] = round(entry["current_cents"] / max_group, 4) if max_group else 0
        group_heatmap.append(entry)

    category_week_totals: dict[str, list[int]] = {}
    for row, _ in current_rows:
        try:
            breakdown = json.loads(row["category_breakdown"] or "{}")
        except (TypeError, json.JSONDecodeError):
            breakdown = {row["category"]: row["amount_cents"]}
        week = min(4, max(0, (int(str(row["spent_at"])[8:10]) - 1) // 7))
        for name, raw_amount in breakdown.items():
            if category and name != category:
                continue
            category_week_totals.setdefault(str(name), [0, 0, 0, 0, 0])[week] += int(raw_amount or 0)
    max_category_cell = max((max(values) for values in category_week_totals.values()), default=0)
    category_heatmap = [
        {
            "category": name,
            "total_cents": sum(values),
            "weeks": [
                {"week": index + 1, "amount_cents": amount, "intensity": round(amount / max_category_cell, 4) if max_category_cell else 0}
                for index, amount in enumerate(values)
            ],
        }
        for name, values in sorted(category_week_totals.items(), key=lambda item: sum(item[1]), reverse=True)
    ]

    merchants: dict[str, dict] = {}
    for row, amount in current_rows:
        merchant = row["merchant_name"] or row["location_name"] or "未识别商户"
        target = merchants.setdefault(merchant, {"merchant": merchant, "amount_cents": 0, "count": 0, "group_names": set()})
        target["amount_cents"] += amount
        target["count"] += 1
        target["group_names"].add(row["group_name"])
    merchant_ranking = []
    for entry in sorted(merchants.values(), key=lambda item: item["amount_cents"], reverse=True)[:10]:
        merchant_ranking.append({**entry, "group_names": sorted(entry["group_names"])})

    def point_payload(period_rows: list[tuple[sqlite3.Row, int]]) -> list[dict]:
        return [
            {
                "expense_id": row["id"], "bill_id": row["bill_id"], "group_id": row["group_id"],
                "group_name": row["group_name"], "merchant": row["merchant_name"], "category": category or row["category"],
                "amount_cents": amount, "spent_at": row["spent_at"], "location_name": row["location_name"],
                "address": row["address"], "lat": row["lat"], "lng": row["lng"],
            }
            for row, amount in period_rows if row["lat"] is not None and row["lng"] is not None
        ]

    current_points = point_payload(current_rows)
    previous_points = point_payload(previous_rows)
    areas: dict[str, dict] = {}
    for key, points in (("current_cents", current_points), ("previous_cents", previous_points)):
        for point in points:
            area_key = f"{float(point['lat']):.2f},{float(point['lng']):.2f}"
            target = areas.setdefault(area_key, {
                "area_key": area_key, "name": point["location_name"] or point["address"] or point["merchant"],
                "lat": point["lat"], "lng": point["lng"], "current_cents": 0, "previous_cents": 0,
            })
            target[key] += point["amount_cents"]
    area_comparison = []
    for area in sorted(areas.values(), key=lambda item: item["current_cents"], reverse=True):
        old = area["previous_cents"]
        area["change_percent"] = None if old == 0 else round((area["current_cents"] - old) / old * 100, 1)
        area_comparison.append(area)

    unlocated = [
        {
            "expense_id": row["id"], "bill_id": row["bill_id"], "group_id": row["group_id"],
            "group_name": row["group_name"], "merchant": row["merchant_name"], "amount_cents": amount,
            "spent_at": row["spent_at"],
        }
        for row, amount in current_rows if row["lat"] is None or row["lng"] is None
    ]
    return {
        "filters": {"month": selected_month, "previous_month": previous, "group_id": group_id, "category": category},
        "groups": [dict(row) for row in groups], "categories": sorted(all_categories),
        "summary": {
            "current_total_cents": current_total, "previous_total_cents": previous_total,
            "change_percent": change_percent, "expense_count": len(current_rows),
            "located_count": len(current_points), "coverage_percent": round(len(current_points) / len(current_rows) * 100, 1) if current_rows else 0,
        },
        "group_heatmap": group_heatmap, "category_heatmap": category_heatmap,
        "merchant_ranking": merchant_ranking, "points": {"current": current_points, "previous": previous_points},
        "area_comparison": area_comparison, "unlocated": unlocated,
    }


@app.patch("/api/finance/expenses/{expense_id}/location")
def update_expense_location(
    expense_id: int,
    body: ExpenseLocationBody,
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    with db() as connection:
        row = connection.execute(
            """SELECT expense_records.*, ai_bills.creator_id, memberships.role
            FROM expense_records JOIN ai_bills ON ai_bills.id = expense_records.bill_id
            JOIN memberships ON memberships.group_id = expense_records.group_id AND memberships.user_id = ?
            WHERE expense_records.id = ?""", (user["id"], expense_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="消费记录不存在")
        if row["creator_id"] != user["id"] and row["role"] not in {"owner", "admin"}:
            raise HTTPException(status_code=403, detail="只有账单创建者、群主或管理员可以修改消费地点")
        connection.execute(
            """UPDATE expense_records SET location_name = ?, address = ?, lat = ?, lng = ?,
            updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
            (body.name.strip(), body.address.strip(), body.lat, body.lng, expense_id),
        )
        updated = connection.execute("SELECT * FROM expense_records WHERE id = ?", (expense_id,)).fetchone()
        return dict(updated)


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


# ---------------------------------------------------------------------------
# Travel route planning
# ---------------------------------------------------------------------------

TRAVEL_STATUSES = {"draft", "planning", "pending", "published", "ended", "archived"}
TRAVEL_TYPES = {"attraction", "hotel", "restaurant", "shopping", "meeting", "other"}
TRAVEL_SPEEDS_KMH = {"walk": 4.5, "walking": 4.5, "transit": 25.0, "公交": 25.0, "drive": 35.0, "driving": 35.0, "驾车": 35.0, "bike": 15.0, "骑行": 15.0}


def parse_travel_date(value: str) -> datetime.date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail="旅行日期格式必须为 YYYY-MM-DD") from error


def validate_travel_dates(start_date: str, end_date: str) -> None:
    start = parse_travel_date(start_date)
    end = parse_travel_date(end_date)
    if end < start:
        raise HTTPException(status_code=400, detail="结束日期不能早于出发日期")
    if (end - start).days > 90:
        raise HTTPException(status_code=400, detail="旅行日期不能超过 90 天")


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp, dl = math.radians(float(lat2) - float(lat1)), math.radians(float(lng2) - float(lng1))
    value = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return max(0.0, radius * 2 * math.asin(min(1.0, math.sqrt(value))))


def travel_duration_minutes(distance_km: float, transport: str) -> int:
    if distance_km <= 0:
        return 0
    speed = TRAVEL_SPEEDS_KMH.get((transport or "drive").lower(), 30.0)
    return max(1, int(math.ceil(distance_km / speed * 60)))


def opening_time_conflict(opening_hours: str, arrival_at: str | None, depart_at: str | None) -> bool:
    """Best-effort check for the common ``HH:MM-HH:MM`` opening-hours format."""
    if not opening_hours or not arrival_at:
        return False
    compact = opening_hours.strip().replace("：", ":")
    if "-" not in compact:
        return False
    start_text, end_text = [part.strip() for part in compact.split("-", 1)]
    try:
        opening = datetime.strptime(start_text, "%H:%M").time()
        closing = datetime.strptime(end_text, "%H:%M").time()
        arrival = datetime.fromisoformat(arrival_at.replace("Z", "+00:00")).time()
        departure = datetime.fromisoformat((depart_at or arrival_at).replace("Z", "+00:00")).time()
    except (TypeError, ValueError):
        return False
    if opening <= closing:
        return arrival < opening or departure > closing
    # Overnight hours, e.g. 18:00-02:00.
    return not (arrival >= opening or departure <= closing)


def travel_membership(connection: sqlite3.Connection, plan_id: int, user_id: int) -> sqlite3.Row:
    row = connection.execute(
        """SELECT travel_plans.*, memberships.role FROM travel_plans
        JOIN memberships ON memberships.group_id = travel_plans.group_id AND memberships.user_id = ?
        WHERE travel_plans.id = ?""", (user_id, plan_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="旅行计划不存在或你不在所属群组中")
    return row


def travel_place_json(row: sqlite3.Row) -> dict:
    payload = dict(row)
    payload["must_visit"] = bool(payload.get("must_visit"))
    if payload.get("avg_cost") is not None:
        payload["avg_cost"] = round(float(payload["avg_cost"]), 2)
    if payload.get("rating") is not None:
        payload["rating"] = round(float(payload["rating"]), 1)
    return payload


def travel_day_json(connection: sqlite3.Connection, row: sqlite3.Row) -> dict:
    nodes = connection.execute(
        """SELECT travel_nodes.*, travel_places.name AS place_name, travel_places.type AS place_type,
        travel_places.address AS place_address, travel_places.lat AS place_lat, travel_places.lng AS place_lng,
        travel_places.avg_cost AS place_avg_cost, travel_places.opening_hours AS place_opening_hours,
        travel_places.must_visit AS place_must_visit
        FROM travel_nodes JOIN travel_places ON travel_places.id = travel_nodes.place_id
        WHERE travel_nodes.day_id = ? ORDER BY travel_nodes.sort_order, travel_nodes.id""", (row["id"],),
    ).fetchall()
    payload = dict(row)
    payload["nodes"] = []
    for node in nodes:
        item = dict(node)
        item["confirmed"] = bool(item.get("confirmed"))
        item["opening_conflict"] = bool(item.get("opening_conflict"))
        payload["nodes"].append(item)
    payload["total_distance_km"] = round(float(payload.get("total_distance_km") or 0), 2)
    payload["total_duration_min"] = int(payload.get("total_duration_min") or 0)
    return payload


def travel_plan_json(connection: sqlite3.Connection, row: sqlite3.Row, user_id: int, include_members: bool = False) -> dict:
    places = connection.execute("SELECT * FROM travel_places WHERE plan_id = ? ORDER BY must_visit DESC, id", (row["id"],)).fetchall()
    days = connection.execute("SELECT * FROM travel_days WHERE plan_id = ? ORDER BY travel_date, id", (row["id"],)).fetchall()
    payload = dict(row)
    payload["budget"] = round(int(payload.get("budget_cents") or 0) / 100, 2)
    votes = connection.execute("SELECT travel_place_votes.*, users.nickname FROM travel_place_votes JOIN users ON users.id = travel_place_votes.user_id WHERE plan_id = ? ORDER BY id", (row["id"],)).fetchall()
    payload["places"] = []
    for place in places:
        place_payload = travel_place_json(place)
        place_votes = [dict(vote) for vote in votes if vote["place_id"] == place["id"]]
        place_payload["vote_count"] = len(place_votes)
        place_payload["votes"] = place_votes
        place_payload["my_vote"] = next((vote for vote in place_votes if int(vote["user_id"]) == int(user_id)), None)
        member_count = connection.execute("SELECT COUNT(*) FROM memberships WHERE group_id = ?", (row["group_id"],)).fetchone()[0]
        positions = connection.execute("SELECT lat, lng FROM travel_member_locations WHERE plan_id = ? AND participating = 1 AND lat IS NOT NULL AND lng IS NOT NULL", (row["id"],)).fetchall()
        distances = [haversine_km(position["lat"], position["lng"], place["lat"], place["lng"]) for position in positions]
        average_distance = sum(distances) / len(distances) if distances else None
        distance_score = max(0.0, min(100.0, 100.0 - (average_distance or 0) * 12))
        vote_score = (len(place_votes) / member_count * 100) if member_count else 0.0
        budget_score = 100.0
        if place["avg_cost"] is not None and row["budget_cents"] and row["estimated_people"]:
            per_person_budget = row["budget_cents"] / 100 / max(row["estimated_people"], 1)
            budget_score = max(0.0, 100.0 - abs(float(place["avg_cost"]) - per_person_budget) / max(per_person_budget, 1) * 100)
        place_payload.update({"average_distance_km": round(average_distance, 2) if average_distance is not None else None, "distance_score": round(distance_score, 1), "vote_score": round(vote_score, 1), "budget_score": round(budget_score, 1), "opening_score": 100.0, "score": round(distance_score * 0.35 + vote_score * 0.30 + budget_score * 0.20 + 15, 1)})
        payload["places"].append(place_payload)
    payload["days"] = [travel_day_json(connection, day) for day in days]
    payload["place_count"] = len(places)
    payload["day_count"] = len(days)
    payload["must_visit_count"] = sum(bool(place["must_visit"]) for place in places)
    payload["is_manager"] = row["role"] in {"owner", "admin"}
    if include_members:
        payload["members"] = [dict(member) for member in connection.execute(
            """SELECT users.id, COALESCE(memberships.group_nickname, users.nickname) AS name,
            memberships.role FROM memberships JOIN users ON users.id = memberships.user_id
            WHERE memberships.group_id = ? ORDER BY memberships.role DESC, users.id""", (row["group_id"],)
        ).fetchall()]
    return payload


def require_travel_manager(connection: sqlite3.Connection, plan_id: int, user_id: int) -> sqlite3.Row:
    row = travel_membership(connection, plan_id, user_id)
    if row["role"] not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="只有群主或管理员可以管理旅行计划")
    return row


def ensure_plan_place(connection: sqlite3.Connection, plan_id: int, place_id: int | None) -> sqlite3.Row | None:
    if place_id is None:
        return None
    row = connection.execute("SELECT * FROM travel_places WHERE id = ? AND plan_id = ?", (place_id, plan_id)).fetchone()
    if not row:
        raise HTTPException(status_code=400, detail="路线地点不属于当前旅行计划")
    return row


def travel_day_bounds(plan: sqlite3.Row, travel_date: str) -> None:
    target = parse_travel_date(travel_date)
    if target < parse_travel_date(plan["start_date"]) or target > parse_travel_date(plan["end_date"]):
        raise HTTPException(status_code=400, detail="行程日期必须位于旅行日期范围内")


def travel_route_metrics(connection: sqlite3.Connection, day: sqlite3.Row, nodes: list[TravelRouteNodeBody]) -> tuple[list[dict], float, int]:
    place_ids = [node.place_id for node in nodes]
    if len(set(place_ids)) != len(place_ids):
        raise HTTPException(status_code=400, detail="同一个地点不能在同一天路线中重复添加")
    places = []
    for place_id in place_ids:
        place = ensure_plan_place(connection, day["plan_id"], place_id)
        if place:
            places.append(place)
    total_distance = 0.0
    total_duration = 0
    previous = connection.execute("SELECT * FROM travel_places WHERE id = ?", (day["start_place_id"],)).fetchone() if day["start_place_id"] else None
    metrics = []
    for index, node in enumerate(nodes):
        current = places[index]
        distance = haversine_km(previous["lat"], previous["lng"], current["lat"], current["lng"]) if previous else 0.0
        segment_transport = node.transport or day["transport"] or "drive"
        duration = travel_duration_minutes(distance, segment_transport)
        total_distance += distance
        total_duration += duration + int(node.stay_minutes or 0)
        metrics.append({"node": node, "place": current, "distance_km": round(distance, 3), "duration_min": duration, "opening_conflict": opening_time_conflict(current["opening_hours"], node.arrival_at, node.depart_at)})
        previous = current
    if places and day["end_place_id"]:
        end_place = connection.execute("SELECT * FROM travel_places WHERE id = ?", (day["end_place_id"],)).fetchone()
        distance = haversine_km(previous["lat"], previous["lng"], end_place["lat"], end_place["lng"])
        total_distance += distance
        total_duration += travel_duration_minutes(distance, day["transport"] or "drive")
    # If explicit day times are present, flag a route that cannot fit in its window.
    if day["start_at"] and day["end_at"]:
        try:
            available = int((datetime.fromisoformat(day["end_at"].replace("Z", "+00:00")) - datetime.fromisoformat(day["start_at"].replace("Z", "+00:00"))).total_seconds() // 60)
            if total_duration > available:
                for metric in metrics:
                    metric["opening_conflict"] = True
        except ValueError:
            pass
    return metrics, round(max(0.0, total_distance), 3), max(0, total_duration)


@app.get("/api/groups/{group_id}/travel-plans")
def list_travel_plans(group_id: int, user: sqlite3.Row = Depends(current_user)) -> list[dict]:
    with db() as connection:
        membership(connection, group_id, user["id"])
        rows = connection.execute("SELECT travel_plans.*, memberships.role FROM travel_plans JOIN memberships ON memberships.group_id = travel_plans.group_id AND memberships.user_id = ? WHERE travel_plans.group_id = ? ORDER BY travel_plans.updated_at DESC, travel_plans.id DESC", (user["id"], group_id)).fetchall()
        return [travel_plan_json(connection, row, user["id"]) for row in rows]


@app.post("/api/groups/{group_id}/travel-plans", status_code=201)
def create_travel_plan(group_id: int, body: TravelPlanBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    validate_travel_dates(body.start_date, body.end_date)
    with db() as connection:
        require_role(connection, group_id, user["id"], {"owner", "admin"})
        cursor = connection.execute(
            """INSERT INTO travel_plans(group_id, creator_id, name, destination, start_date, end_date,
            departure_city, default_start_point, default_transport, estimated_people, budget_cents, notes, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft')""",
            (group_id, user["id"], body.name.strip(), body.destination.strip(), body.start_date, body.end_date,
             body.departure_city.strip(), body.default_start_point.strip(), body.default_transport.strip(), body.estimated_people,
             round(body.budget * 100) if body.budget is not None else body.budget_cents, body.notes.strip()),
        )
        row = connection.execute("SELECT travel_plans.*, memberships.role FROM travel_plans JOIN memberships ON memberships.group_id = travel_plans.group_id AND memberships.user_id = ? WHERE travel_plans.id = ?", (user["id"], cursor.lastrowid)).fetchone()
        audit(connection, group_id, user["id"], "travel_plan_created", f"创建旅行计划“{body.name.strip()}”", target_id=cursor.lastrowid)
        return travel_plan_json(connection, row, user["id"], True)


@app.get("/api/travel-plans/{plan_id}")
def get_travel_plan(plan_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        row = travel_membership(connection, plan_id, user["id"])
        return travel_plan_json(connection, row, user["id"], True)


@app.patch("/api/travel-plans/{plan_id}")
def update_travel_plan(plan_id: int, body: TravelPlanUpdateBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        plan = require_travel_manager(connection, plan_id, user["id"])
        values = body.model_dump(exclude_none=True)
        if "budget" in values:
            values["budget_cents"] = round(float(values.pop("budget")) * 100)
        start_date = values.get("start_date", plan["start_date"])
        end_date = values.get("end_date", plan["end_date"])
        validate_travel_dates(start_date, end_date)
        if values.get("status") == "archived" and plan["status"] != "ended":
            raise HTTPException(status_code=400, detail="只有已结束的旅行计划可以归档")
        if values:
            assignments = ", ".join(f"{key} = ?" for key in values)
            connection.execute(f"UPDATE travel_plans SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (*values.values(), plan_id))
        row = connection.execute("SELECT travel_plans.*, memberships.role FROM travel_plans JOIN memberships ON memberships.group_id = travel_plans.group_id AND memberships.user_id = ? WHERE travel_plans.id = ?", (user["id"], plan_id)).fetchone()
        return travel_plan_json(connection, row, user["id"], True)


@app.delete("/api/travel-plans/{plan_id}")
def delete_travel_plan(plan_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        plan = require_travel_manager(connection, plan_id, user["id"])
        connection.execute("DELETE FROM travel_plans WHERE id = ?", (plan_id,))
        audit(connection, plan["group_id"], user["id"], "travel_plan_deleted", f"删除旅行计划“{plan['name']}”", target_id=plan_id)
        return {"ok": True, "deleted_id": plan_id}


@app.post("/api/travel-plans/{plan_id}/places", status_code=201)
def create_travel_place(plan_id: int, body: TravelPlaceBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        plan = require_travel_manager(connection, plan_id, user["id"])
        cursor = connection.execute(
            """INSERT INTO travel_places(plan_id, type, name, address, lat, lng, provider_place_id,
            opening_hours, avg_cost, phone, rating, must_visit, note, image_url, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (plan_id, body.type, body.name.strip(), body.address.strip(), body.lat, body.lng, body.provider_place_id.strip(),
             body.opening_hours.strip(), body.avg_cost, body.phone.strip(), body.rating, int(body.must_visit), body.note.strip(), body.image_url.strip(), user["id"]),
        )
        row = connection.execute("SELECT * FROM travel_places WHERE id = ?", (cursor.lastrowid,)).fetchone()
        connection.execute("UPDATE travel_plans SET updated_at = CURRENT_TIMESTAMP, status = CASE WHEN status = 'draft' THEN 'planning' ELSE status END WHERE id = ?", (plan_id,))
        return travel_place_json(row)


@app.patch("/api/travel-places/{place_id}")
def update_travel_place(place_id: int, body: TravelPlaceUpdateBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        place = connection.execute("SELECT * FROM travel_places WHERE id = ?", (place_id,)).fetchone()
        if not place:
            raise HTTPException(status_code=404, detail="旅行地点不存在")
        require_travel_manager(connection, place["plan_id"], user["id"])
        values = body.model_dump(exclude_none=True)
        if values:
            assignments = ", ".join(f"{key} = ?" for key in values)
            connection.execute(f"UPDATE travel_places SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (*values.values(), place_id))
        return travel_place_json(connection.execute("SELECT * FROM travel_places WHERE id = ?", (place_id,)).fetchone())


@app.post("/api/travel-plans/{plan_id}/places/{place_id}/vote")
def vote_travel_place(plan_id: int, place_id: int, body: TravelPlaceVoteBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        travel_membership(connection, plan_id, user["id"])
        place = connection.execute("SELECT id FROM travel_places WHERE id = ? AND plan_id = ?", (place_id, plan_id)).fetchone()
        if not place:
            raise HTTPException(status_code=404, detail="旅行地点不存在")
        connection.execute(
            """INSERT INTO travel_place_votes(plan_id, place_id, user_id, suggestion, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(plan_id, user_id) DO UPDATE SET place_id = excluded.place_id, suggestion = excluded.suggestion, updated_at = CURRENT_TIMESTAMP""",
            (plan_id, place_id, user["id"], body.suggestion.strip()),
        )
        return {"ok": True, "plan_id": plan_id, "place_id": place_id, "suggestion": body.suggestion.strip()}


@app.get("/api/travel-plans/{plan_id}/place-votes")
def list_travel_place_votes(plan_id: int, user: sqlite3.Row = Depends(current_user)) -> list[dict]:
    with db() as connection:
        travel_membership(connection, plan_id, user["id"])
        return [dict(row) for row in connection.execute(
            """SELECT travel_place_votes.*, users.nickname, travel_places.name AS place_name
            FROM travel_place_votes JOIN users ON users.id = travel_place_votes.user_id
            JOIN travel_places ON travel_places.id = travel_place_votes.place_id
            WHERE travel_place_votes.plan_id = ? ORDER BY travel_place_votes.id""", (plan_id,)
        ).fetchall()]


@app.delete("/api/travel-places/{place_id}")
def delete_travel_place(place_id: int, force: bool = False, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        place = connection.execute("SELECT * FROM travel_places WHERE id = ?", (place_id,)).fetchone()
        if not place:
            raise HTTPException(status_code=404, detail="旅行地点不存在")
        require_travel_manager(connection, place["plan_id"], user["id"])
        linked = connection.execute("SELECT COUNT(*) FROM travel_nodes WHERE place_id = ?", (place_id,)).fetchone()[0]
        if linked and not force:
            raise HTTPException(status_code=409, detail={"message": "该地点已被安排在路线中", "linked_days": linked, "can_force": True})
        connection.execute("DELETE FROM travel_places WHERE id = ?", (place_id,))
        return {"ok": True, "deleted_id": place_id, "removed_route_days": linked}


@app.get("/api/travel-plans/{plan_id}/days")
def list_travel_days(plan_id: int, user: sqlite3.Row = Depends(current_user)) -> list[dict]:
    with db() as connection:
        travel_membership(connection, plan_id, user["id"])
        return [travel_day_json(connection, row) for row in connection.execute("SELECT * FROM travel_days WHERE plan_id = ? ORDER BY travel_date, id", (plan_id,)).fetchall()]


@app.post("/api/travel-plans/{plan_id}/days", status_code=201)
def create_travel_day(plan_id: int, body: TravelDayBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        plan = require_travel_manager(connection, plan_id, user["id"])
        travel_day_bounds(plan, body.travel_date)
        if (body.start_at and not body.end_at) or (body.end_at and not body.start_at):
            raise HTTPException(status_code=400, detail="每日行程需要同时填写开始和结束时间")
        if body.start_at and body.end_at:
            validate_time_range(body.start_at, body.end_at)
        ensure_plan_place(connection, plan_id, body.start_place_id)
        ensure_plan_place(connection, plan_id, body.end_place_id)
        try:
            cursor = connection.execute(
                """INSERT INTO travel_days(plan_id, travel_date, title, start_at, end_at, start_place_id,
                end_place_id, transport, budget_cents, notes, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (plan_id, body.travel_date, body.title.strip() or f"{body.travel_date} 行程", body.start_at, body.end_at, body.start_place_id, body.end_place_id, body.transport.strip(), body.budget_cents, body.notes.strip(), body.status),
            )
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="该日期已经有每日行程") from error
        return travel_day_json(connection, connection.execute("SELECT * FROM travel_days WHERE id = ?", (cursor.lastrowid,)).fetchone())


@app.patch("/api/travel-days/{day_id}")
def update_travel_day(day_id: int, body: TravelDayUpdateBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        day = connection.execute("SELECT * FROM travel_days WHERE id = ?", (day_id,)).fetchone()
        if not day:
            raise HTTPException(status_code=404, detail="每日行程不存在")
        plan = require_travel_manager(connection, day["plan_id"], user["id"])
        values = body.model_dump(exclude_none=True)
        target_date = values.get("travel_date", day["travel_date"])
        travel_day_bounds(plan, target_date)
        start_at, end_at = values.get("start_at", day["start_at"]), values.get("end_at", day["end_at"])
        if (start_at and not end_at) or (end_at and not start_at):
            raise HTTPException(status_code=400, detail="每日行程需要同时填写开始和结束时间")
        if start_at and end_at:
            validate_time_range(start_at, end_at)
        ensure_plan_place(connection, day["plan_id"], values.get("start_place_id", day["start_place_id"]))
        ensure_plan_place(connection, day["plan_id"], values.get("end_place_id", day["end_place_id"]))
        if values:
            assignments = ", ".join(f"{key} = ?" for key in values)
            connection.execute(f"UPDATE travel_days SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (*values.values(), day_id))
        return travel_day_json(connection, connection.execute("SELECT * FROM travel_days WHERE id = ?", (day_id,)).fetchone())


@app.delete("/api/travel-days/{day_id}")
def delete_travel_day(day_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        day = connection.execute("SELECT * FROM travel_days WHERE id = ?", (day_id,)).fetchone()
        if not day:
            raise HTTPException(status_code=404, detail="每日行程不存在")
        require_travel_manager(connection, day["plan_id"], user["id"])
        connection.execute("DELETE FROM travel_days WHERE id = ?", (day_id,))
        return {"ok": True, "deleted_id": day_id}


@app.put("/api/travel-days/{day_id}/route")
def save_travel_route(day_id: int, body: TravelRouteBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        day = connection.execute("SELECT * FROM travel_days WHERE id = ?", (day_id,)).fetchone()
        if not day:
            raise HTTPException(status_code=404, detail="每日行程不存在")
        require_travel_manager(connection, day["plan_id"], user["id"])
        metrics, total_distance, total_duration = travel_route_metrics(connection, day, body.nodes)
        connection.execute("DELETE FROM travel_nodes WHERE day_id = ?", (day_id,))
        cursor_time = None
        if day["start_at"]:
            try:
                cursor_time = datetime.fromisoformat(day["start_at"].replace("Z", "+00:00"))
            except ValueError:
                cursor_time = None
        elapsed = 0
        for index, metric in enumerate(metrics):
            node = metric["node"]
            arrival_at = node.arrival_at
            depart_at = node.depart_at
            if cursor_time and not arrival_at:
                arrival_at = (cursor_time + timedelta(minutes=elapsed)).isoformat(timespec="minutes")
            if arrival_at and not depart_at:
                try:
                    depart_at = (datetime.fromisoformat(arrival_at.replace("Z", "+00:00")) + timedelta(minutes=node.stay_minutes)).isoformat(timespec="minutes")
                except ValueError:
                    depart_at = None
            metric["opening_conflict"] = opening_time_conflict(metric["place"]["opening_hours"], arrival_at, depart_at) or metric["opening_conflict"]
            connection.execute(
                """INSERT INTO travel_nodes(day_id, place_id, sort_order, arrival_at, stay_minutes, depart_at,
                transport, distance_km, duration_min, confirmed, opening_conflict) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (day_id, node.place_id, index, arrival_at, node.stay_minutes, depart_at, node.transport or day["transport"], metric["distance_km"], metric["duration_min"], int(node.confirmed), int(metric["opening_conflict"])),
            )
            elapsed += metric["duration_min"] + int(node.stay_minutes or 0)
        score = max(0.0, min(100.0, 100.0 - total_distance * 2 - max(0, total_duration - 600) * 0.05)) if metrics else 0.0
        connection.execute("UPDATE travel_days SET total_distance_km = ?, total_duration_min = ?, route_score = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (total_distance, total_duration, round(score, 1), day_id))
        return travel_day_json(connection, connection.execute("SELECT * FROM travel_days WHERE id = ?", (day_id,)).fetchone())


@app.get("/api/travel-days/{day_id}/route")
def get_travel_route(day_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        day = connection.execute("SELECT * FROM travel_days WHERE id = ?", (day_id,)).fetchone()
        if not day:
            raise HTTPException(status_code=404, detail="每日行程不存在")
        travel_membership(connection, day["plan_id"], user["id"])
        return travel_day_json(connection, day)


def build_auto_plan_options(connection: sqlite3.Connection, plan: sqlite3.Row, body: TravelAutoPlanBody) -> list[dict]:
    place_rows = connection.execute("SELECT * FROM travel_places WHERE plan_id = ? ORDER BY must_visit DESC, id", (plan["id"],)).fetchall()
    if body.place_ids:
        allowed = set(body.place_ids)
        place_rows = [place for place in place_rows if place["id"] in allowed]
    if not place_rows:
        raise HTTPException(status_code=400, detail="请先添加至少一个旅行地点")
    dates = [body.travel_date] if body.travel_date else [row["travel_date"] for row in connection.execute("SELECT * FROM travel_days WHERE plan_id = ? ORDER BY travel_date", (plan["id"],)).fetchall()]
    if not dates:
        dates = [plan["start_date"]]
    for date_value in dates:
        travel_day_bounds(plan, date_value)
    candidates = []
    for mode, label in [("distance", "距离最短"), ("time", "时间最省"), ("places", "景点最多"), ("comfort", "舒适度最高")]:
        ordered = list(place_rows)
        if mode == "distance":
            ordered.sort(key=lambda place: (not place["must_visit"], place["id"]))
        elif mode == "time":
            ordered.sort(key=lambda place: (not place["must_visit"], float(place["avg_cost"] or 0), place["id"]))
        elif mode == "places":
            ordered.sort(key=lambda place: (not place["must_visit"], -(float(place["rating"] or 0)), place["id"]))
        else:
            ordered.sort(key=lambda place: (not place["must_visit"], float(place["avg_cost"] or 0), -(float(place["rating"] or 0))))
        day_payloads = []
        cursor = 0
        for date_value in dates:
            existing = connection.execute("SELECT * FROM travel_days WHERE plan_id = ? AND travel_date = ?", (plan["id"], date_value)).fetchone()
            max_count = max(1, min(len(ordered), int(body.max_play_minutes / 90)))
            selected = ordered[cursor:cursor + max_count] if len(dates) > 1 else ordered[:max_count]
            cursor += max_count
            if not selected:
                selected = ordered[:max_count]
            nodes = []
            current_minutes = int(body.earliest_start[:2]) * 60 + int(body.earliest_start[3:])
            for place in selected:
                arrival = f"{date_value}T{current_minutes // 60:02d}:{current_minutes % 60:02d}"
                depart_minutes = current_minutes + 60
                nodes.append({"place_id": place["id"], "place_name": place["name"], "arrival_at": arrival, "stay_minutes": 60, "depart_at": f"{date_value}T{depart_minutes // 60:02d}:{depart_minutes % 60:02d}", "transport": body.transport, "confirmed": False})
                current_minutes = depart_minutes + 30
            total_distance = sum(haversine_km(selected[index - 1]["lat"], selected[index - 1]["lng"], selected[index]["lat"], selected[index]["lng"]) for index in range(1, len(selected)))
            total_duration = len(selected) * 60 + max(0, len(selected) - 1) * 30 + travel_duration_minutes(total_distance, body.transport)
            day_payloads.append({"travel_date": date_value, "title": f"{date_value} 推荐路线", "day_id": existing["id"] if existing else None, "nodes": nodes, "total_distance_km": round(total_distance, 2), "total_duration_min": total_duration, "budget_cents": int(sum(float(place["avg_cost"] or 0) * 100 for place in selected)), "unassigned_place_ids": [place["id"] for place in ordered if place["id"] not in {item["place_id"] for item in nodes}]})
        total_distance = round(sum(day["total_distance_km"] for day in day_payloads), 2)
        total_duration = sum(day["total_duration_min"] for day in day_payloads)
        score = max(0.0, min(100.0, 100.0 - total_distance * 2 + (10 if mode in {"places", "comfort"} else 0)))
        candidates.append({"option_id": mode, "name": label, "description": f"按{label}排序，使用免费距离估算", "days": day_payloads, "total_distance_km": total_distance, "total_duration_min": total_duration, "estimated_budget_cents": sum(day["budget_cents"] for day in day_payloads), "score": round(score, 1), "unassigned_place_ids": sorted({item for day in day_payloads for item in day["unassigned_place_ids"]})})
    return candidates


@app.post("/api/travel-plans/{plan_id}/auto-plan")
def auto_plan_travel(plan_id: int, body: TravelAutoPlanBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        plan = require_travel_manager(connection, plan_id, user["id"])
        options = build_auto_plan_options(connection, plan, body)
        return {"plan_id": plan_id, "options": options, "provider": "haversine-estimate", "notice": "当前使用免费直线距离和交通速度估算；可在地图中查看地点位置。"}


@app.post("/api/travel-plans/{plan_id}/apply-plan")
def apply_travel_plan(plan_id: int, body: TravelApplyPlanBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        plan = require_travel_manager(connection, plan_id, user["id"])
        if body.option_id not in {"distance", "time", "places", "comfort", "balanced"}:
            raise HTTPException(status_code=400, detail="路线方案不存在，请重新生成")
        options = build_auto_plan_options(connection, plan, TravelAutoPlanBody(prioritize=body.option_id if body.option_id != "balanced" else "distance"))
        option = next((item for item in options if item["option_id"] == body.option_id), options[0])
        applied = []
        for day_data in option["days"]:
            day = connection.execute("SELECT * FROM travel_days WHERE id = ?", (day_data["day_id"],)).fetchone() if day_data["day_id"] else None
            if not day:
                day = connection.execute("SELECT * FROM travel_days WHERE plan_id = ? AND travel_date = ?", (plan_id, day_data["travel_date"])).fetchone()
            if not day:
                cursor = connection.execute("INSERT INTO travel_days(plan_id, travel_date, title, transport, budget_cents) VALUES (?, ?, ?, ?, ?)", (plan_id, day_data["travel_date"], day_data["title"], plan["default_transport"], day_data["budget_cents"]))
                day = connection.execute("SELECT * FROM travel_days WHERE id = ?", (cursor.lastrowid,)).fetchone()
            nodes = [TravelRouteNodeBody(place_id=node["place_id"], arrival_at=node["arrival_at"], stay_minutes=node["stay_minutes"], depart_at=node["depart_at"], transport=node["transport"], confirmed=False) for node in day_data["nodes"]]
            metrics, distance, duration = travel_route_metrics(connection, day, nodes)
            connection.execute("DELETE FROM travel_nodes WHERE day_id = ?", (day["id"],))
            for index, metric in enumerate(metrics):
                node = metric["node"]
                connection.execute("INSERT INTO travel_nodes(day_id, place_id, sort_order, arrival_at, stay_minutes, depart_at, transport, distance_km, duration_min, confirmed, opening_conflict) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)", (day["id"], node.place_id, index, node.arrival_at, node.stay_minutes, node.depart_at, node.transport or day["transport"], metric["distance_km"], metric["duration_min"], int(metric["opening_conflict"])))
            connection.execute("UPDATE travel_days SET total_distance_km = ?, total_duration_min = ?, route_score = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (distance, duration, option["score"], day["id"]))
            applied.append(travel_day_json(connection, connection.execute("SELECT * FROM travel_days WHERE id = ?", (day["id"],)).fetchone()))
        connection.execute("UPDATE travel_plans SET status = 'planning', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (plan_id,))
        return {"plan_id": plan_id, "option_id": body.option_id, "days": applied, "score": option["score"]}


@app.post("/api/travel-plans/{plan_id}/location")
def save_travel_member_location(plan_id: int, body: TravelMemberLocationBody, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        plan = travel_membership(connection, plan_id, user["id"])
        if body.participating and (body.lat is None or body.lng is None):
            raise HTTPException(status_code=400, detail="参与集合点推荐时需要提供位置，未授权定位可手动填写经纬度")
        connection.execute(
            """INSERT INTO travel_member_locations(plan_id, user_id, lat, lng, address, participating, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(plan_id, user_id) DO UPDATE SET lat = excluded.lat, lng = excluded.lng, address = excluded.address, participating = excluded.participating, updated_at = CURRENT_TIMESTAMP""",
            (plan_id, user["id"], body.lat, body.lng, body.address.strip(), int(body.participating)),
        )
        return {"ok": True, "plan_id": plan_id, "participating": body.participating}


@app.get("/api/travel-plans/{plan_id}/locations")
def list_travel_member_locations(plan_id: int, user: sqlite3.Row = Depends(current_user)) -> list[dict]:
    with db() as connection:
        plan = travel_membership(connection, plan_id, user["id"])
        rows = connection.execute(
            """SELECT travel_member_locations.*, COALESCE(memberships.group_nickname, users.nickname) AS user_name
            FROM travel_member_locations JOIN users ON users.id = travel_member_locations.user_id
            JOIN memberships ON memberships.group_id = ? AND memberships.user_id = users.id
            WHERE travel_member_locations.plan_id = ? ORDER BY users.id""", (plan["group_id"], plan_id)
        ).fetchall()
        return [dict(row) for row in rows]


@app.get("/api/travel-plans/{plan_id}/meeting-recommendation")
def travel_meeting_recommendation(plan_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        plan = travel_membership(connection, plan_id, user["id"])
        locations = connection.execute("SELECT travel_member_locations.*, COALESCE(memberships.group_nickname, users.nickname) AS user_name FROM travel_member_locations JOIN users ON users.id = travel_member_locations.user_id JOIN memberships ON memberships.group_id = ? AND memberships.user_id = travel_member_locations.user_id WHERE travel_member_locations.plan_id = ? AND participating = 1 AND lat IS NOT NULL AND lng IS NOT NULL", (plan["group_id"], plan_id)).fetchall()
        if len(locations) < 2:
            return {"ready": False, "count": len(locations), "required": 2, "message": "至少需要 2 名成员提交参与位置后才能推荐集合点", "candidates": []}
        lat = sum(float(row["lat"]) for row in locations) / len(locations)
        lng = sum(float(row["lng"]) for row in locations) / len(locations)
        place = connection.execute("SELECT * FROM travel_places WHERE plan_id = ? ORDER BY must_visit DESC, id LIMIT 1", (plan_id,)).fetchone()
        candidates = [{"name": "成员位置几何中心", "address": f"{lat:.6f}, {lng:.6f}", "lat": round(lat, 6), "lng": round(lng, 6)},]
        if place:
            candidates.append({"name": place["name"], "address": place["address"], "lat": place["lat"], "lng": place["lng"]})
        scored = []
        for candidate in candidates:
            distances = [{"user_id": row["user_id"], "user_name": row["user_name"], "distance_km": round(haversine_km(row["lat"], row["lng"], candidate["lat"], candidate["lng"]), 2)} for row in locations]
            average = sum(item["distance_km"] for item in distances) / len(distances)
            longest = max(item["distance_km"] for item in distances)
            score = max(0.0, min(100.0, 100.0 - average * 12 - longest * 3))
            scored.append({**candidate, "member_distances": distances, "average_distance_km": round(average, 2), "max_distance_km": round(longest, 2), "score": round(score, 1)})
        scored.sort(key=lambda item: item["score"], reverse=True)
        return {"ready": True, "count": len(locations), "recommended": scored[0], "candidates": scored, "formula": "距离便利度综合评分，使用 Haversine 免费估算"}


def travel_publish_checks(connection: sqlite3.Connection, plan: sqlite3.Row) -> dict:
    places = connection.execute("SELECT * FROM travel_places WHERE plan_id = ?", (plan["id"],)).fetchall()
    days = connection.execute("SELECT * FROM travel_days WHERE plan_id = ? ORDER BY travel_date", (plan["id"],)).fetchall()
    nodes = connection.execute("SELECT travel_nodes.*, travel_days.travel_date FROM travel_nodes JOIN travel_days ON travel_days.id = travel_nodes.day_id WHERE travel_days.plan_id = ?", (plan["id"],)).fetchall()
    assigned = {row["place_id"] for row in nodes}
    missing_must = [row["name"] for row in places if row["must_visit"] and row["id"] not in assigned]
    conflicts = [row["travel_date"] for row in nodes if row["opening_conflict"]]
    over_time = [row["travel_date"] for row in days if row["start_at"] and row["end_at"] and row["total_duration_min"] > int((datetime.fromisoformat(row["end_at"].replace("Z", "+00:00")) - datetime.fromisoformat(row["start_at"].replace("Z", "+00:00"))).total_seconds() // 60)]
    duplicate_rows = connection.execute("SELECT travel_nodes.place_id, COUNT(*) AS count FROM travel_nodes JOIN travel_days ON travel_days.id = travel_nodes.day_id WHERE travel_days.plan_id = ? GROUP BY travel_nodes.place_id HAVING COUNT(*) > 1", (plan["id"],)).fetchall()
    duplicate_places = [next((place["name"] for place in places if place["id"] == row["place_id"]), str(row["place_id"])) for row in duplicate_rows]
    missing_endpoints = [row["travel_date"] for row in days if not row["start_place_id"] or not row["end_place_id"]]
    total_budget = sum(int(row["budget_cents"] or 0) + int(sum(float(place["place_avg_cost"] or 0) * 100 for place in connection.execute("SELECT travel_places.avg_cost AS place_avg_cost FROM travel_nodes JOIN travel_places ON travel_places.id = travel_nodes.place_id WHERE travel_nodes.day_id = ?", (row["id"],)).fetchall())) for row in days)
    over_budget = bool(plan["budget_cents"] and total_budget > plan["budget_cents"])
    errors = []
    if not days: errors.append("至少需要一个每日行程")
    if missing_must: errors.append(f"存在未安排的必去地点：{'、'.join(missing_must)}")
    if conflicts: errors.append("路线存在营业时间或每日可用时间冲突")
    if over_time: errors.append(f"以下日期超出可用时间：{'、'.join(over_time)}")
    if duplicate_places: errors.append(f"地点重复安排：{'、'.join(duplicate_places)}")
    if missing_endpoints: errors.append(f"以下日期缺少起点或终点：{'、'.join(missing_endpoints)}")
    if over_budget: errors.append("每日预算合计超过旅行总预算")
    return {"passed": not errors, "errors": errors, "missing_must_visit": missing_must, "opening_conflicts": sorted(set(conflicts)), "over_time_days": sorted(set(over_time)), "duplicate_places": duplicate_places, "missing_endpoints": sorted(set(missing_endpoints)), "total_budget_cents": total_budget, "budget_cents": int(plan["budget_cents"] or 0)}


@app.get("/api/travel-plans/{plan_id}/publish-check")
def check_travel_publish(plan_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        plan = travel_membership(connection, plan_id, user["id"])
        return travel_publish_checks(connection, plan)


@app.post("/api/travel-plans/{plan_id}/publish")
def publish_travel_plan(plan_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        plan = require_travel_manager(connection, plan_id, user["id"])
        checks = travel_publish_checks(connection, plan)
        if not checks["passed"]:
            raise HTTPException(status_code=400, detail={"message": "发布前检查未通过", "details": checks["errors"], "checks": checks})
        connection.execute("UPDATE travel_plans SET status = 'published', published_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (plan_id,))
        connection.execute("UPDATE travel_days SET status = 'confirmed', updated_at = CURRENT_TIMESTAMP WHERE plan_id = ?", (plan_id,))
        audit(connection, plan["group_id"], user["id"], "travel_plan_published", f"发布旅行行程“{plan['name']}”", target_id=plan_id)
        row = connection.execute("SELECT travel_plans.*, memberships.role FROM travel_plans JOIN memberships ON memberships.group_id = travel_plans.group_id AND memberships.user_id = ? WHERE travel_plans.id = ?", (user["id"], plan_id)).fetchone()
        return {"plan": travel_plan_json(connection, row, user["id"], True), "checks": checks}


@app.post("/api/travel-plans/{plan_id}/sync-calendar")
def sync_travel_calendar(plan_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        plan = require_travel_manager(connection, plan_id, user["id"])
        if plan["status"] != "published":
            raise HTTPException(status_code=400, detail="只有已发布的旅行路线才能同步到共享日程")
        days = connection.execute("SELECT * FROM travel_days WHERE plan_id = ? ORDER BY travel_date", (plan_id,)).fetchall()
        synced = []
        for day in days:
            day_payload = travel_day_json(connection, day)
            if not day_payload["nodes"]:
                continue
            first = day_payload["nodes"][0]
            last = day_payload["nodes"][-1]
            start_at = first.get("arrival_at") or day["start_at"] or f"{day['travel_date']}T09:00"
            end_at = last.get("depart_at") or day["end_at"] or f"{day['travel_date']}T18:00"
            items = [(node["place_name"], node.get("arrival_at") or start_at, node.get("depart_at") or end_at) for node in day_payload["nodes"]]
            activity_id = day["activity_id"]
            if activity_id:
                activity = connection.execute("SELECT id FROM activities WHERE id = ? AND group_id = ?", (activity_id, plan["group_id"])).fetchone()
            else:
                activity = None
            if activity:
                connection.execute("UPDATE activities SET title = ?, description = ?, mode = 'fixed', status = 'published', start_at = ?, end_at = ?, form = '旅行路线', notice = ?, published_at = CURRENT_TIMESTAMP WHERE id = ?", (f"{plan['name']} · {day['travel_date']}", plan["destination"], start_at, end_at, day["notes"] or "已同步旅行路线", activity_id))
                connection.execute("DELETE FROM activity_items WHERE activity_id = ?", (activity_id,))
            else:
                cursor = connection.execute("INSERT INTO activities(group_id, creator_id, title, description, mode, status, start_at, end_at, form, notice, published_at) VALUES (?, ?, ?, ?, 'fixed', 'published', ?, ?, '旅行路线', ?, CURRENT_TIMESTAMP)", (plan["group_id"], user["id"], f"{plan['name']} · {day['travel_date']}", plan["destination"], start_at, end_at, day["notes"] or "已同步旅行路线"))
                activity_id = cursor.lastrowid
                connection.execute("UPDATE travel_days SET activity_id = ? WHERE id = ?", (activity_id, day["id"]))
            for index, (title, item_start, item_end) in enumerate(items):
                connection.execute("INSERT INTO activity_items(activity_id, title, start_at, end_at, note, sort_order) VALUES (?, ?, ?, ?, '', ?)", (activity_id, title, item_start, item_end, index))
            synced.append({"day_id": day["id"], "activity_id": activity_id, "travel_date": day["travel_date"], "title": f"{plan['name']} · {day['travel_date']}"})
        connection.execute("UPDATE travel_plans SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (plan_id,))
        return {"plan_id": plan_id, "synced": synced, "count": len(synced), "message": "旅行路线已同步到共享日程"}


@app.get("/api/travel-plans/{plan_id}/report")
def travel_plan_report(plan_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    with db() as connection:
        plan = travel_membership(connection, plan_id, user["id"])
        days = [travel_day_json(connection, row) for row in connection.execute("SELECT * FROM travel_days WHERE plan_id = ? ORDER BY travel_date", (plan_id,)).fetchall()]
        checks = travel_publish_checks(connection, plan)
        return {"plan": {"id": plan_id, "name": plan["name"], "destination": plan["destination"], "status": plan["status"]}, "days": days, "summary": {"total_distance_km": round(sum(day["total_distance_km"] for day in days), 2), "total_duration_min": sum(day["total_duration_min"] for day in days), "estimated_budget_cents": checks["total_budget_cents"], "place_count": connection.execute("SELECT COUNT(*) FROM travel_places WHERE plan_id = ?", (plan_id,)).fetchone()[0]}, "checks": checks}


initialize_database()
