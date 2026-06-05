from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from threading import RLock
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Header, HTTPException, status

from app.core.settings import settings
from app.models.schemas import HouseholdProfileRequest


class AuthStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = RLock()
        self._setup()

    def _setup(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS access_tokens (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_health_profiles (
                user_id TEXT PRIMARY KEY,
                profile_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS relatives (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                relative_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        self._connection.commit()

    def register(self, username: str, password: str) -> dict[str, Any]:
        with self._lock:
            if self._get_user_by_username(username):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="username already exists")

            now = _now()
            user_id = secrets.token_urlsafe(12)
            salt = secrets.token_hex(16)
            password_hash = _hash_password(password, salt)
            self._connection.execute(
                """
                INSERT INTO users (id, username, password_hash, salt, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, username, password_hash, salt, now),
            )
            self._connection.commit()
            return self._create_session({"id": user_id, "username": username})

    def login(self, username: str, password: str) -> dict[str, Any]:
        with self._lock:
            user = self._get_user_by_username(username)
            if not user or not _verify_password(password, user["salt"], user["password_hash"]):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid username or password")
            return self._create_session({"id": user["id"], "username": user["username"]})

    def get_user_by_token(self, token: str) -> dict[str, str]:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT u.id, u.username, t.expires_at
                FROM access_tokens t
                JOIN users u ON u.id = t.user_id
                WHERE t.token = ?
                """,
                (token,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")

            expires_at = datetime.fromisoformat(row["expires_at"])
            if expires_at <= datetime.now(timezone.utc):
                self.logout(token)
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token expired")

            return {"id": row["id"], "username": row["username"]}

    def logout(self, token: str) -> None:
        with self._lock:
            self._connection.execute("DELETE FROM access_tokens WHERE token = ?", (token,))
            self._connection.commit()

    def get_household_profile(self, user_id: str) -> dict[str, Any]:
        import json

        with self._lock:
            profile_row = self._connection.execute(
                "SELECT profile_json FROM user_health_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            relative_rows = self._connection.execute(
                """
                SELECT relative_json
                FROM relatives
                WHERE user_id = ?
                ORDER BY updated_at DESC
                """,
                (user_id,),
            ).fetchall()
            profile = json.loads(profile_row["profile_json"]) if profile_row else _empty_profile()
            relatives = [json.loads(row["relative_json"]) for row in relative_rows]
            return {"profile": profile, "relatives": relatives}

    def save_household_profile(self, user_id: str, request: HouseholdProfileRequest) -> dict[str, Any]:
        import json

        with self._lock:
            now = _now()
            profile_payload = request.profile.model_dump()
            self._connection.execute(
                """
                INSERT INTO user_health_profiles (user_id, profile_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    profile_json=excluded.profile_json,
                    updated_at=excluded.updated_at
                """,
                (user_id, json.dumps(profile_payload, ensure_ascii=False), now),
            )

            self._connection.execute("DELETE FROM relatives WHERE user_id = ?", (user_id,))
            for relative in request.relatives:
                relative_payload = relative.model_dump()
                relative_id = relative_payload["id"] or secrets.token_urlsafe(10)
                relative_payload["id"] = relative_id
                self._connection.execute(
                    """
                    INSERT INTO relatives (id, user_id, relative_json, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (relative_id, user_id, json.dumps(relative_payload, ensure_ascii=False), now),
                )
            self._connection.commit()
            return self.get_household_profile(user_id)

    def _get_user_by_username(self, username: str) -> sqlite3.Row | None:
        return self._connection.execute(
            """
            SELECT id, username, password_hash, salt
            FROM users
            WHERE username = ?
            """,
            (username,),
        ).fetchone()

    def _create_session(self, user: dict[str, str]) -> dict[str, Any]:
        with self._lock:
            now = datetime.now(timezone.utc)
            token = secrets.token_urlsafe(32)
            expires_at = now + timedelta(days=7)
            self._connection.execute(
                """
                INSERT INTO access_tokens (token, user_id, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (token, user["id"], expires_at.isoformat(timespec="seconds"), now.isoformat(timespec="seconds")),
            )
            self._connection.commit()
            return {"access_token": token, "token_type": "bearer", "user": user}


auth_store = AuthStore(settings.auth_db_path)


def household_context(user_id: str | None) -> str:
    if not user_id:
        return ""

    household = auth_store.get_household_profile(user_id)
    profile = household["profile"]
    relatives = household["relatives"]
    has_profile = any(
        profile.get(key)
        for key in (
            "age",
            "gender",
            "height_cm",
            "weight_kg",
            "activity_level",
            "health_goals",
            "conditions",
            "allergies",
            "dietary_preferences",
            "notes",
        )
    )
    if not has_profile and not relatives:
        return ""

    lines = ["用户与家庭饮食档案:"]
    if has_profile:
        lines.extend(
            [
                "本人:",
                f"- age={profile.get('age')}, gender={profile.get('gender')}",
                f"- height_cm={profile.get('height_cm')}, weight_kg={profile.get('weight_kg')}",
                f"- activity_level={profile.get('activity_level')}",
                f"- health_goals={profile.get('health_goals')}",
                f"- conditions={profile.get('conditions')}",
                f"- allergies={profile.get('allergies')}",
                f"- dietary_preferences={profile.get('dietary_preferences')}",
                f"- notes={profile.get('notes')}",
            ]
        )
    if relatives:
        lines.append("共同用餐家人:")
        for relative in relatives[:10]:
            lines.append(
                "- "
                f"name={relative.get('name')}, relation={relative.get('relation')}, age={relative.get('age')}, "
                f"conditions={relative.get('conditions')}, allergies={relative.get('allergies')}, "
                f"dietary_preferences={relative.get('dietary_preferences')}, notes={relative.get('notes')}"
            )
    lines.append("请把这些信息仅作为饮食规划参考，不做医疗诊断。")
    return "\n".join(lines)


def get_current_user(authorization: str = Header("")) -> dict[str, str]:
    token = _extract_bearer_token(authorization)
    return auth_store.get_user_by_token(token)


def get_current_token(authorization: str = Header("")) -> str:
    return _extract_bearer_token(authorization)


def _extract_bearer_token(authorization: str) -> str:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    return token.strip()


def _hash_password(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return digest.hex()


def _verify_password(password: str, salt: str, expected_hash: str) -> bool:
    actual_hash = _hash_password(password, salt)
    return hmac.compare_digest(actual_hash, expected_hash)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty_profile() -> dict[str, Any]:
    return {
        "age": None,
        "gender": "",
        "height_cm": None,
        "weight_kg": None,
        "activity_level": "",
        "health_goals": [],
        "conditions": [],
        "allergies": [],
        "dietary_preferences": [],
        "notes": "",
    }
