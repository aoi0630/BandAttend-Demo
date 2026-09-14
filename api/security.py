from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any

from fastapi import Header, HTTPException, status

from database import ensure_members_optional_columns, get_connection, maintenance_mode_enabled


EVENT_EDITORS = {"部長", "副部長", "管理者"}
ANNOUNCEMENT_PUBLISHERS = {"部長", "副部長", "顧問", "管理者"}
OPERATION_VIEWERS = {"パートリーダー", "部長", "副部長", "管理者"}
STUDENT_ID_VIEWERS = {"管理者"}
APP_SECRET = os.getenv("APP_SECRET", "bandattend-local-development-secret")
PIN_ITERATIONS = 210_000


def hash_pin(pin: str, salt: str | None = None) -> tuple[str, str]:
    salt_value = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), bytes.fromhex(salt_value), PIN_ITERATIONS)
    return digest.hex(), salt_value


def verify_pin(pin: str, stored_hash: str | None, salt: str | None) -> bool:
    if not stored_hash or not salt:
        return False
    candidate, _ = hash_pin(pin, salt)
    return hmac.compare_digest(candidate, stored_hash)


def display_role(role: str) -> str:
    return "先生" if role == "顧問" else role


def weekdays_from_text(value):
    return [weekday for weekday in str(value or "").split(",") if weekday in {"月", "火", "水", "木", "金", "土", "日"}]


def row_value(row, key, default=None):
    try:
        return row[key]
    except Exception:
        return default


def make_token(member_id: int) -> str:
    payload = {"member_id": member_id}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    signature = hmac.new(APP_SECRET.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def read_token(token: str) -> int:
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(APP_SECRET.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid signature")
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        return int(payload["member_id"])
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        ) from exc


def permissions_for_role(role: str) -> dict[str, bool]:
    return {
        "canEditEvents": role in EVENT_EDITORS,
        "canPublishAnnouncements": role in ANNOUNCEMENT_PUBLISHERS,
        "canViewOperations": role in OPERATION_VIEWERS,
        "canViewStudentIds": role in STUDENT_ID_VIEWERS,
        "canSubmitAttendance": role in {"一般部員", "パートリーダー", "部長", "副部長"},
    }


def member_to_user(member: Any) -> dict[str, Any]:
    role = member["role"]
    read_only = bool(row_value(member, "read_only"))
    can_view_student_id = role in STUDENT_ID_VIEWERS
    user = {
        "id": member["id"],
        "name": member["name"],
        "grade": member["grade"],
        "birthday": member["birthday"],
        "part": member["part"],
        "role": role,
        "roleLabel": display_role(role),
        "status": member["status"],
        "email": member["email"],
        "phone": member["phone"],
        "hometown": member["hometown"],
        "bandYears": member["band_years"],
        "mbti": member["mbti"],
        "classLateWeekdays": weekdays_from_text(row_value(member, "class_late_weekdays")),
        "duty": row_value(member, "club_duty"),
        "hasSeenGuide": bool(row_value(member, "has_seen_guide")),
        "hasSeenPrivacy": bool(row_value(member, "has_seen_privacy")),
        "readOnly": read_only,
        "joinDate": member["join_date"],
        "permissions": permissions_for_role(role),
    }
    if read_only:
        user["permissions"].update({
            "canEditEvents": False,
            "canPublishAnnouncements": False,
            "canViewStudentIds": False,
            "canSubmitAttendance": False,
        })
    if can_view_student_id:
        user["studentId"] = member["student_id"]
    return user


def get_current_member(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    member_id = read_token(authorization.removeprefix("Bearer ").strip())
    conn = get_connection()
    ensure_members_optional_columns(conn)
    member = conn.execute(
        """
        SELECT
            id,
            student_id,
            name,
            grade,
            birthday,
            part,
            role,
            status,
            email,
            phone,
            hometown,
            band_years,
            mbti,
            class_late_weekdays,
            club_duty,
            has_seen_guide,
            has_seen_privacy,
            read_only,
            join_date
        FROM members
        WHERE id = ?
        AND status IN ('在籍', '閲覧専用')
        """,
        (member_id,),
    ).fetchone()
    if member is None:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Member not found",
        )

    if member["role"] != "管理者" and maintenance_mode_enabled(conn):
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="現在メンテナンス中です。しばらくしてからもう一度お試しください。",
        )

    conn.close()
    return member
