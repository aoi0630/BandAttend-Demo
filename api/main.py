from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
import json
import os
import runpy
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.schemas import (
    AbsenceReportShareRequest,
    AnnouncementCreateRequest,
    AttendanceConfirmRequest,
    AttendanceSubmitRequest,
    ApprovalRequest,
    BirthdayMessageRequest,
    EventUpsertRequest,
    ExternalSystemLinkRequest,
    FeatureToggleRequest,
    LoginRequest,
    LoginResponse,
    PinSetupRequest,
    LeaveRequestCreate,
    MemberRegistrationRequest,
    MemberRegistrationReviewRequest,
    MemberUpsertRequest,
    PartMemoCreateRequest,
    PracticeReflectionRequest,
    ProfileUpdateRequest,
    PublicationCreateRequest,
    TodoCreateRequest,
)
from api.security import EVENT_EDITORS, get_current_member, hash_pin, make_token, member_to_user, read_token, verify_pin
from config import ADMIN_PART, PARTS, ROLES
from database import (
    ensure_announcement_teacher_column,
    ensure_event_teacher_visit_column,
    ensure_maintenance_flag,
    ensure_members_optional_columns,
    ensure_todo_notification_columns,
    get_connection,
    maintenance_mode_enabled,
)
from utils.registration_utils import ensure_registration_requests_table


app = FastAPI(title="BandAttend API", version="0.1.0")

default_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
]
configured_origins = [
    origin.strip().rstrip("/")
    for origin in os.getenv("FRONTEND_ORIGINS", "").split(",")
    if origin.strip()
]
if os.getenv("BANDATTEND_DEMO_DATABASE") == "1":
    configured_origins.append("https://bandattend-portfolio-demo.vercel.app")

app.add_middleware(
    CORSMiddleware,
    allow_origins=configured_origins or default_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _bootstrap_portfolio_demo() -> None:
    """Create an isolated, disposable demo DB on each new server instance."""
    if os.getenv("BANDATTEND_DEMO_DATABASE") != "1":
        return
    root = Path(__file__).resolve().parents[1]
    runpy.run_path(str(root / "database" / "init_db.py"), run_name="__bandattend_demo_init__")
    from scripts.setup_portfolio_demo import seed

    seed()


_bootstrap_portfolio_demo()


@app.middleware("http")
async def block_read_only_mutations(request: Request, call_next):
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return await call_next(request)

    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        return await call_next(request)

    try:
        member_id = read_token(authorization.removeprefix("Bearer ").strip())
    except HTTPException:
        return await call_next(request)

    conn = get_connection()
    ensure_members_optional_columns(conn)
    member = conn.execute(
        "SELECT read_only FROM members WHERE id = ? AND status IN ('在籍', '閲覧専用')",
        (member_id,),
    ).fetchone()
    conn.close()
    if member and bool(member["read_only"]):
        return JSONResponse(
            status_code=403,
            content={"detail": "このアカウントは閲覧専用です。更新操作はできません。"},
        )
    return await call_next(request)

EVENT_TYPES = {
    "通常練習",
    "合奏",
    "分奏",
    "パート練習",
    "本番",
    "コンクール",
    "定期演奏会",
    "依頼演奏",
    "その他",
}

_birthday_messages_schema_ready = False
_login_events_schema_ready = False
_system_lifecycle_schema_ready = False
_practice_reflections_schema_ready = False

WEEKDAYS = {"月", "火", "水", "木", "金", "土", "日"}
WOODWIND_PARTS = {"フルート", "クラリネット", "サックス"}
BRASS_PARTS = {"トランペット", "ホルン", "トロンボーン", "ユーフォニアム", "バスパート"}


def _instrument_group_scopes(part):
    scopes = []
    if part in WOODWIND_PARTS:
        scopes.append("木管")
    if part in BRASS_PARTS:
        scopes.append("金管")
    return scopes


def _ensure_practice_reflections_schema(conn):
    global _practice_reflections_schema_ready
    if _practice_reflections_schema_ready:
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS practice_reflections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            target_scope TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(event_id) REFERENCES events(id),
            FOREIGN KEY(created_by) REFERENCES members(id)
        )
        """
    )
    conn.commit()
    _practice_reflections_schema_ready = True


@app.get("/api/health")
def health_check():
    return {"ok": True}


@app.get("/api/maintenance-status")
def maintenance_status():
    conn = get_connection()
    enabled = maintenance_mode_enabled(conn)
    conn.close()
    return {"enabled": enabled}


def _compact_login_text(value: str | None) -> str:
    return "".join((value or "").split())


def _validate_pin(pin: str) -> str:
    cleaned = str(pin or "").strip()
    if len(cleaned) != 4 or not cleaned.isdigit():
        raise HTTPException(status_code=400, detail="暗証番号は4桁の数字で入力してください")
    return cleaned


def _login_member(conn, student_id):
    return conn.execute(
        """
        SELECT id, student_id, name, grade, birthday, part, role, status, email, phone,
               hometown, band_years, mbti, class_late_weekdays, club_duty,
               has_seen_guide, has_seen_privacy, read_only, birthday_celebrated_on,
               pin_hash, pin_salt, pin_failed_attempts, pin_locked_until,
               last_login_at, join_date
        FROM members
        WHERE student_id = ? AND status IN ('在籍', '閲覧専用')
        """,
        (student_id,),
    ).fetchone()


def _ensure_role_preview_accounts(conn):
    preview_accounts = (
        ("0", "部長視点（閲覧専用）", 3, "ホルン", "部長", "0"),
        ("1", "副部長視点（閲覧専用）", 3, "ホルン", "副部長", "1"),
        ("2", "パートリーダー視点（閲覧専用）", 2, "ホルン", "パートリーダー", "2"),
        ("3", "先生視点（閲覧専用）", 0, "未設定", "顧問", "3"),
    )
    existing_rows = conn.execute(
        "SELECT student_id, status FROM members WHERE student_id IN ('0', '1', '2', '3')"
    ).fetchall()
    existing = {str(row["student_id"]): row["status"] for row in existing_rows}
    changed = False
    for student_id, name, grade, part, role, pin in preview_accounts:
        if student_id in existing and existing[student_id] != "閲覧専用":
            continue
        if student_id not in existing:
            pin_hash, pin_salt = hash_pin(pin)
            conn.execute(
                """
                INSERT INTO members
                    (student_id, name, grade, part, role, status, has_seen_guide,
                     has_seen_privacy, read_only, pin_hash, pin_salt)
                VALUES (?, ?, ?, ?, ?, '閲覧専用', 1, 1, 1, ?, ?)
                """,
                (student_id, name, grade, part, role, pin_hash, pin_salt),
            )
        else:
            conn.execute(
                """
                UPDATE members
                SET name = ?, grade = ?, part = ?, role = ?, read_only = 1,
                    has_seen_guide = 1, has_seen_privacy = 1, updated_at = CURRENT_TIMESTAMP
                WHERE student_id = ? AND status = '閲覧専用'
                """,
                (name, grade, part, role, student_id),
            )
        changed = True
    if changed:
        conn.commit()


def _ensure_login_events_table(conn):
    global _login_events_schema_ready
    if _login_events_schema_ready:
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS login_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            logged_in_at TEXT NOT NULL,
            FOREIGN KEY(member_id) REFERENCES members(id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_login_events_logged_in_at ON login_events(logged_in_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_login_events_member_id ON login_events(member_id)"
    )
    conn.commit()
    _login_events_schema_ready = True


def _record_login_event(conn, member_id, logged_in_at):
    try:
        conn.execute(
            "INSERT INTO login_events (member_id, logged_in_at) VALUES (?, ?)",
            (member_id, logged_in_at),
        )
    except Exception:
        _ensure_login_events_table(conn)
        conn.execute(
            "INSERT INTO login_events (member_id, logged_in_at) VALUES (?, ?)",
            (member_id, logged_in_at),
        )


def _ensure_system_lifecycle_table(conn):
    global _system_lifecycle_schema_ready
    if _system_lifecycle_schema_ready:
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS system_lifecycle (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            current_phase TEXT,
            phase_started_on TEXT,
            trial_started_on TEXT,
            release_started_on TEXT,
            updated_by INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute("INSERT OR IGNORE INTO system_lifecycle (id) VALUES (1)")
    conn.commit()
    _system_lifecycle_schema_ready = True


def _complete_login(conn, member):
    japan_now = datetime.now(ZoneInfo("Asia/Tokyo"))
    japan_today = japan_now.date().isoformat()
    birthday_today = bool(member["birthday"] and str(member["birthday"])[5:10] == japan_today[5:10])
    show_birthday_celebration = birthday_today and member["birthday_celebrated_on"] != japan_today
    # 閲覧専用アカウントは利用状況の記録対象外。
    # TursoへのUPDATE/INSERTを省くことで、公開デモのログイン応答を短縮する。
    if member["status"] == "閲覧専用" or bool(member["read_only"]):
        conn.close()
        user = member_to_user(member)
        user["showBirthdayCelebration"] = False
        return {"token": make_token(int(member["id"])), "user": user}
    conn.execute(
        """
        UPDATE members SET last_login_at = CURRENT_TIMESTAMP,
            birthday_celebrated_on = CASE WHEN ? THEN ? ELSE birthday_celebrated_on END,
            pin_failed_attempts = 0, pin_locked_until = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (1 if show_birthday_celebration else 0, japan_today, member["id"]),
    )
    _record_login_event(conn, member["id"], japan_now.strftime("%Y-%m-%d %H:%M:%S"))
    conn.commit()
    conn.close()
    user = member_to_user(member)
    user["showBirthdayCelebration"] = show_birthday_celebration
    return {"token": make_token(int(member["id"])), "user": user}


def _clean_weekdays(values):
    cleaned = []
    for value in values or []:
        weekday = str(value).strip()
        if not weekday:
            continue
        if weekday not in WEEKDAYS:
            raise HTTPException(status_code=400, detail="授業遅刻の曜日が正しくありません")
        if weekday not in cleaned:
            cleaned.append(weekday)
    return cleaned


def _weekdays_to_text(values):
    return ",".join(_clean_weekdays(values))


def _weekdays_from_text(value):
    return [weekday for weekday in str(value or "").split(",") if weekday in WEEKDAYS]


@app.post("/api/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest):
    student_id = _compact_login_text(payload.student_id)
    pin = str(payload.pin or "").strip()
    if pin not in {"0", "1", "2", "3"}:
        pin = _validate_pin(pin)
    if not student_id:
        raise HTTPException(status_code=400, detail="学籍番号を入力してください")

    conn = get_connection()
    ensure_members_optional_columns(conn)
    member = _login_member(conn, student_id)

    # 通常ログインのたびに閲覧用4アカウントを更新・commitしていた処理を廃止。
    # 未作成の場合だけ補完して再検索する。
    if member is None and student_id in {"0", "1", "2", "3"}:
        _ensure_role_preview_accounts(conn)
        member = _login_member(conn, student_id)

    if member is None:
        conn.close()
        raise HTTPException(status_code=401, detail="学籍番号または暗証番号が違います")

    if member["role"] != "管理者" and maintenance_mode_enabled(conn):
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="現在メンテナンス中です。管理者が終了するまでログインできません。",
        )

    if not member["pin_hash"]:
        conn.close()
        if pin == "0":
            raise HTTPException(status_code=409, detail="初回暗証番号設定が必要です")
        raise HTTPException(status_code=401, detail="学籍番号または暗証番号が違います")
    now_utc = datetime.now(timezone.utc)
    if member["pin_locked_until"]:
        locked_until = datetime.fromisoformat(str(member["pin_locked_until"]))
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if locked_until > now_utc:
            conn.close()
            raise HTTPException(status_code=429, detail="ログイン試行回数が上限に達しました。15分後に再度お試しください")
    demo_credentials = {
        "portfolio-demo": "2580",
        "portfolio-ops": "2580",
        "0": "0",
        "1": "1",
        "2": "2",
        "3": "3",
    }
    is_demo_preview = (
        os.getenv("BANDATTEND_DEMO_DATABASE") == "1"
        and bool(member["read_only"])
        and demo_credentials.get(student_id) == pin
    )
    if not is_demo_preview and not verify_pin(pin, member["pin_hash"], member["pin_salt"]):
        attempts = int(member["pin_failed_attempts"] or 0) + 1
        locked_until = (now_utc + timedelta(minutes=15)).isoformat() if attempts >= 5 else None
        conn.execute(
            "UPDATE members SET pin_failed_attempts = ?, pin_locked_until = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (0 if locked_until else attempts, locked_until, member["id"]),
        )
        conn.commit()
        conn.close()
        if locked_until:
            raise HTTPException(status_code=429, detail="ログイン試行回数が上限に達しました。15分後に再度お試しください")
        raise HTTPException(status_code=401, detail=f"学籍番号または暗証番号が違います（あと{5 - attempts}回）")
    return _complete_login(conn, member)


@app.post("/api/auth/setup-pin", response_model=LoginResponse)
def setup_pin(payload: PinSetupRequest):
    student_id = _compact_login_text(payload.student_id)
    name = _compact_login_text(payload.name)
    pin = _validate_pin(payload.pin)
    if not student_id or not name:
        raise HTTPException(status_code=400, detail="学籍番号と氏名を入力してください")
    conn = get_connection()
    ensure_members_optional_columns(conn)
    member = _login_member(conn, student_id)
    if member is None:
        conn.close()
        raise HTTPException(status_code=401, detail="学籍番号または氏名が違います")
    if member["role"] != "管理者" and maintenance_mode_enabled(conn):
        conn.close()
        raise HTTPException(status_code=503, detail="現在メンテナンス中です。管理者が終了するまでログインできません。")
    now_utc = datetime.now(timezone.utc)
    if member["pin_locked_until"]:
        locked_until = datetime.fromisoformat(str(member["pin_locked_until"]))
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if locked_until > now_utc:
            conn.close()
            raise HTTPException(status_code=429, detail="設定試行回数が上限に達しました。15分後に再度お試しください")
    if _compact_login_text(member["name"]) != name:
        attempts = int(member["pin_failed_attempts"] or 0) + 1
        locked_until = (now_utc + timedelta(minutes=15)).isoformat() if attempts >= 5 else None
        conn.execute(
            "UPDATE members SET pin_failed_attempts = ?, pin_locked_until = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (0 if locked_until else attempts, locked_until, member["id"]),
        )
        conn.commit()
        conn.close()
        if locked_until:
            raise HTTPException(status_code=429, detail="設定試行回数が上限に達しました。15分後に再度お試しください")
        raise HTTPException(status_code=401, detail=f"学籍番号または氏名が違います（あと{5 - attempts}回）")
    if member["pin_hash"]:
        conn.close()
        raise HTTPException(status_code=409, detail="暗証番号は設定済みです。通常ログインを利用してください")
    pin_hash, pin_salt = hash_pin(pin)
    conn.execute(
        "UPDATE members SET pin_hash = ?, pin_salt = ?, pin_failed_attempts = 0, pin_locked_until = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (pin_hash, pin_salt, member["id"]),
    )
    conn.commit()
    member = _login_member(conn, student_id)
    return _complete_login(conn, member)


@app.post("/api/member-registration-requests", status_code=201)
def create_member_registration_request(payload: MemberRegistrationRequest):
    student_id = _compact_login_text(payload.student_id)
    name = (payload.name or "").strip()
    pin = _validate_pin(payload.pin)
    if not student_id or not name:
        raise HTTPException(status_code=400, detail="学籍番号と名前は必須です")
    conn = get_connection()
    ensure_registration_requests_table(conn)
    try:
        if conn.execute("SELECT 1 FROM members WHERE student_id = ?", (student_id,)).fetchone():
            raise HTTPException(status_code=409, detail="この学籍番号はすでに部員登録されています")
        if conn.execute(
            "SELECT 1 FROM member_registration_requests WHERE student_id = ? AND status = '申請中'",
            (student_id,),
        ).fetchone():
            raise HTTPException(status_code=409, detail="この学籍番号の申請はすでに受け付けています")
        pin_hash, pin_salt = hash_pin(pin)
        cur = conn.execute(
            """
            INSERT INTO member_registration_requests
            (student_id, name, grade, birthday, part, email, phone, pin_hash, pin_salt, join_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (student_id, name, 1, None, "未設定", None, None, pin_hash, pin_salt, None),
        )
        conn.commit()
        return {"requestId": int(cur.lastrowid), "status": "申請中"}
    finally:
        conn.close()


@app.get("/api/me")
def me(member=Depends(get_current_member)):
    return {"user": member_to_user(member)}


@app.post("/api/profile/guide-seen")
def mark_guide_seen(member=Depends(get_current_member)):
    conn = get_connection()
    ensure_members_optional_columns(conn)
    conn.execute(
        "UPDATE members SET has_seen_guide = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (member["id"],),
    )
    conn.commit()
    conn.close()
    return {"hasSeenGuide": True}


@app.post("/api/profile/privacy-seen")
def mark_privacy_seen(member=Depends(get_current_member)):
    conn = get_connection()
    ensure_members_optional_columns(conn)
    conn.execute(
        "UPDATE members SET has_seen_privacy = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (member["id"],),
    )
    conn.commit()
    conn.close()
    return {"hasSeenPrivacy": True}


@app.patch("/api/profile")
def update_profile(payload: ProfileUpdateRequest, member=Depends(get_current_member)):
    birthday = _clean_optional_date(payload.birthday, "birthday")
    hometown = (payload.hometown or "").strip() or None
    band_years = payload.band_years
    mbti = (payload.mbti or "").strip().upper() or None
    class_late_weekdays = _weekdays_to_text(payload.class_late_weekdays)
    duty = (payload.duty or "").strip() or None
    if band_years is not None and band_years < 0:
        raise HTTPException(status_code=400, detail="吹奏楽年数は0以上で入力してください")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE members
        SET birthday = ?,
            hometown = ?,
            band_years = ?,
            mbti = ?,
            class_late_weekdays = ?,
            club_duty = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (birthday, hometown, band_years, mbti, class_late_weekdays, duty, member["id"]),
    )
    updated = cur.execute(
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
            join_date
        FROM members
        WHERE id = ?
        """,
        (member["id"],),
    ).fetchone()
    conn.commit()
    conn.close()

    return {"user": member_to_user(updated)}


def _time_text(start_time, end_time):
    start = str(start_time or "")[:5]
    end = str(end_time or "")[:5]
    if start and end:
        return f"{start} - {end}"
    return start or end or "時間未定"


def _event_to_home_item(row):
    return {
        "id": row["id"],
        "date": row["date"],
        "day": int(str(row["date"])[8:10]),
        "type": row["event_type"],
        "title": row["title"] or row["event_type"],
        "time": _time_text(row["start_time"], row["end_time"]),
        "startTime": str(row["start_time"] or "")[:5] or None,
        "endTime": str(row["end_time"] or "")[:5] or None,
        "place": row["location"] or "場所未設定",
        "location": row["location"],
        "description": row["memo"] or "練習内容が登録されるとここに表示されます。",
        "teacherVisit": bool(row["teacher_visit"]) if "teacher_visit" in row.keys() else False,
    }


def _event_to_calendar_item(row):
    item = _event_to_home_item(row)
    item.update(
        {
            "attendanceCount": int(row["attendance_count"] or 0),
            "approvedAbsences": row.get("approved_absences", []),
            "isPastUnanswered": bool(row.get("is_past_unanswered", False)),
            "canSelectAttendance": bool(row.get("can_select_attendance", False)),
            "myAttendance": None
            if row["my_status"] is None
            else {
                "id": row["my_attendance_id"] if "my_attendance_id" in row.keys() else None,
                "status": row["my_status"],
                "approvalStatus": row["my_approval_status"],
            },
            "canAttendToday": bool(row["can_attend_today"]),
        }
    )
    return item


def _can_review_attendance(reviewer, requester) -> bool:
    """Return whether reviewer is responsible for requester's attendance request."""
    requester_keys = requester.keys() if hasattr(requester, "keys") else ()
    requester_id = requester["member_id"] if "member_id" in requester_keys else requester["id"]
    if int(reviewer["id"]) == int(requester_id):
        return False
    reviewer_role = reviewer["role"]
    requester_role = requester["role"]
    if reviewer_role == "管理者":
        return True
    if reviewer_role == "パートリーダー":
        return requester_role == "一般部員" and reviewer["part"] == requester["part"]
    if reviewer_role == "部長":
        return requester_role in {"パートリーダー", "副部長"}
    if reviewer_role == "副部長":
        return requester_role in {"パートリーダー", "部長"}
    return False


def _notify_part_leaders(conn, member, attendance_id):
    conn.execute(
        """
        DELETE FROM notifications
        WHERE related_attendance_id = ?
        AND notification_type = 'approval_request'
        """,
        (attendance_id,),
    )
    if member["role"] == "パートリーダー":
        leaders = conn.execute(
            """
            SELECT id
            FROM members
            WHERE role IN ('部長', '副部長')
            AND status = '在籍'
            AND id != ?
            """,
            (member["id"],),
        ).fetchall()
    elif member["role"] == "部長":
        leaders = conn.execute(
            "SELECT id FROM members WHERE role = '副部長' AND status = '在籍' AND id != ?",
            (member["id"],),
        ).fetchall()
    elif member["role"] == "副部長":
        leaders = conn.execute(
            "SELECT id FROM members WHERE role = '部長' AND status = '在籍' AND id != ?",
            (member["id"],),
        ).fetchall()
    else:
        leaders = conn.execute(
            """
            SELECT id
            FROM members
            WHERE part = ?
            AND role = 'パートリーダー'
            AND status = '在籍'
            AND id != ?
            """,
            (member["part"], member["id"]),
        ).fetchall()

    for leader in leaders:
        conn.execute(
            """
            INSERT INTO notifications
            (target_member_id, notification_type, title, message, related_attendance_id)
            VALUES (?, 'approval_request', '承認待ちがあります', ?, ?)
            """,
            (
                leader["id"],
                f"{member['name']} さんの出席申請があります。",
                attendance_id,
            ),
        )


def _announcement_target_label(row):
    if row["target_type"] == "パート":
        return f"{row['target_part']}向け"
    if row["target_type"] == "学年":
        return f"{row['target_grade']}年向け"
    if row["target_type"] in {"金管", "木管"}:
        return f"{row['target_type']}向け"
    return "全体"


def _announcement_to_item(row):
    return {
        "id": row["id"],
        "targetType": row["target_type"],
        "targetPart": row["target_part"],
        "targetGrade": row["target_grade"],
        "targetLabel": _announcement_target_label(row),
        "title": row["title"],
        "message": row["message"],
        "isImportant": bool(row["is_important"]),
        "sendToTeacher": bool(row["send_to_teacher"]),
        "isRead": bool(row["is_read"]),
        "createdBy": row["creator_name"],
        "createdByMe": bool(row["created_by_me"]),
        "readCount": int(row["read_count"] or 0),
        "createdAt": row["created_at"],
    }


def _can_publish_announcements(role):
    return role in {"部長", "副部長", "顧問", "管理者"}


def _can_delete_announcements(role):
    return role in {"部長", "副部長", "管理者"}


def _announcement_target_types(role):
    if role == "顧問":
        return ["全体", "パート"]
    return ["全体", "パート", "学年"]


def _announcement_targets(conn, target_type, target_part=None, target_grade=None):
    conditions = ["status = '在籍'", "role != '顧問'"]
    params = []

    if target_type == "パート":
        conditions.append("part = ?")
        params.append(target_part)
    elif target_type == "学年":
        conditions.append("grade = ?")
        params.append(target_grade)
    elif target_type in {"金管", "木管"}:
        target_parts = sorted(BRASS_PARTS if target_type == "金管" else WOODWIND_PARTS)
        conditions.append(f"part IN ({','.join('?' for _ in target_parts)})")
        params.extend(target_parts)

    return conn.execute(
        f"""
        SELECT id
        FROM members
        WHERE {' AND '.join(conditions)}
        """,
        params,
    ).fetchall()


def _part_memo_to_item(row, member):
    return {
        "id": row["id"],
        "part": row["part"],
        "title": row["title"],
        "memo": row["memo"],
        "createdBy": row["creator_name"],
        "createdById": row["created_by"],
        "createdAt": row["created_at"],
        "canDelete": _can_delete_part_memo(member, row),
    }


def _manageable_parts(member):
    if member["role"] in {"部長", "副部長", "管理者"}:
        return PARTS
    if member["role"] == "顧問":
        return PARTS
    return [member["part"]]


def _can_write_part_memo(member, part):
    if member["role"] in {"部長", "副部長", "管理者"}:
        return True
    return part == member["part"]


def _can_delete_part_memo(member, memo):
    if member["role"] in {"部長", "副部長", "管理者"}:
        return True
    if member["role"] == "パートリーダー" and memo["part"] == member["part"]:
        return True
    return int(memo["created_by"]) == int(member["id"])


def _clean_optional_date(value, field_name):
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        datetime.strptime(cleaned, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} must be YYYY-MM-DD",
        ) from exc
    return cleaned


def _today_events(conn, target_date, member_id):
    return conn.execute(
        """
        SELECT e.id, e.date, e.start_time, e.end_time, e.event_type, e.title, e.location, e.memo,
               mine.status AS my_status,
               mine.approval_status AS my_approval_status
        FROM events e
        LEFT JOIN attendance mine
            ON mine.event_id = e.id
            AND mine.member_id = ?
        WHERE e.date = ?
        ORDER BY e.start_time, e.id
        """,
        (member_id, target_date),
    ).fetchall()


def _visible_unread_notifications(conn, member_id, target_date, has_today_events):
    rows = conn.execute(
        """
        SELECT id, notification_type, title, message, related_attendance_id, is_read, created_at
        FROM notifications
        WHERE target_member_id = ?
        AND is_read = 0
        ORDER BY created_at DESC
        """,
        (member_id,),
    ).fetchall()

    visible = []
    for row in rows:
        if row["title"] == "出席確認のお願い" and (not has_today_events or target_date not in str(row["message"])):
            continue
        visible.append(
            {
                "id": row["id"],
                "type": row["notification_type"],
                "title": row["title"],
                "message": row["message"],
                "relatedAttendanceId": row["related_attendance_id"],
                "isRead": bool(row["is_read"]),
                "createdAt": row["created_at"],
            }
        )
    return visible


def _birthdays(conn, target_date):
    rows = conn.execute(
        """
        SELECT id, name, grade, part, role, birthday
        FROM members
        WHERE status = '在籍'
        AND birthday IS NOT NULL
        ORDER BY part, grade, name
        """
    ).fetchall()
    today = datetime.strptime(target_date, "%Y-%m-%d").date()
    candidates = []
    for row in rows:
        try:
            birthday = datetime.strptime(row["birthday"], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            continue
        next_birthday = None
        for year in range(today.year, today.year + 5):
            try:
                candidate = date(year, birthday.month, birthday.day)
            except ValueError:
                continue
            if candidate >= today:
                next_birthday = candidate
                break
        if next_birthday:
            candidates.append((next_birthday, row))

    if not candidates:
        return {"items": [], "date": None, "isToday": False}

    nearest_date = min(candidate for candidate, _ in candidates)
    nearest_rows = [row for candidate, row in candidates if candidate == nearest_date]
    items = [
        {
            "id": row["id"],
            "name": row["name"],
            "grade": row["grade"],
            "part": row["part"],
            "role": row["role"],
            "birthday": row["birthday"],
        }
        for row in nearest_rows
    ]
    return {
        "items": items,
        "date": nearest_date.isoformat(),
        "isToday": nearest_date == today,
    }


def _ensure_birthday_messages_table(conn):
    global _birthday_messages_schema_ready
    if _birthday_messages_schema_ready:
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS birthday_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            recipient_id INTEGER NOT NULL,
            celebration_year INTEGER NOT NULL,
            message TEXT NOT NULL,
            reacted_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(sender_id, recipient_id, celebration_year),
            FOREIGN KEY(sender_id) REFERENCES members(id),
            FOREIGN KEY(recipient_id) REFERENCES members(id)
        )
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(birthday_messages)").fetchall()}
    if "reacted_at" not in columns:
        conn.execute("ALTER TABLE birthday_messages ADD COLUMN reacted_at TEXT")
    conn.commit()
    _birthday_messages_schema_ready = True


def _birthday_messages_for_member(conn, member_id, target_date):
    member_row = conn.execute("SELECT birthday FROM members WHERE id = ?", (member_id,)).fetchone()
    if not member_row or not member_row["birthday"] or str(member_row["birthday"])[5:10] != target_date[5:10]:
        return []
    _ensure_birthday_messages_table(conn)
    rows = conn.execute(
        """
        SELECT bm.id, bm.message, bm.reacted_at, bm.created_at,
               sender.name AS sender_name, sender.part AS sender_part
        FROM birthday_messages bm
        JOIN members sender ON sender.id = bm.sender_id
        WHERE bm.recipient_id = ? AND bm.celebration_year = ?
        ORDER BY bm.updated_at, bm.id
        """,
        (member_id, int(target_date[:4])),
    ).fetchall()
    return [
        {"id": row["id"], "message": row["message"], "senderName": row["sender_name"], "senderPart": row["sender_part"], "reacted": bool(row["reacted_at"]), "createdAt": row["created_at"]}
        for row in rows
    ]


def _sent_birthday_messages(conn, sender_id, target_date):
    _ensure_birthday_messages_table(conn)
    rows = conn.execute(
        """
        SELECT recipient_id, reacted_at
        FROM birthday_messages
        WHERE sender_id = ? AND celebration_year = ?
        """,
        (sender_id, int(target_date[:4])),
    ).fetchall()
    return [
        {"recipientId": int(row["recipient_id"]), "reacted": bool(row["reacted_at"])}
        for row in rows
    ]


def _next_performance(conn, target_date):
    row = conn.execute(
        """
        SELECT id, date, start_time, event_type, title, location, memo
        FROM events
        WHERE event_type IN ('本番', 'コンクール', '定期演奏会', '依頼演奏')
        AND date >= ?
        ORDER BY date, start_time, id
        LIMIT 1
        """,
        (target_date,),
    ).fetchone()
    if row is None:
        return None

    performance_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
    today_date = datetime.strptime(target_date, "%Y-%m-%d").date()
    days_left = (performance_date - today_date).days
    return {
        "id": row["id"],
        "title": row["title"] or row["event_type"],
        "date": row["date"],
        "eventType": row["event_type"],
        "location": row["location"] or "場所未設定",
        "startTime": str(row["start_time"] or "")[:5] or None,
        "daysLeft": days_left,
        "label": "本日" if days_left == 0 else f"あと{days_left}日",
    }


def _ensure_external_system_links_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS external_system_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            url TEXT NOT NULL,
            icon_url TEXT,
            created_by INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(external_system_links)").fetchall()}
    if "icon_url" not in columns:
        conn.execute("ALTER TABLE external_system_links ADD COLUMN icon_url TEXT")
    conn.commit()


def _external_system_links(conn):
    _ensure_external_system_links_table(conn)
    rows = conn.execute(
        """
        SELECT id, name, description, url, icon_url, created_at, updated_at
        FROM external_system_links
        ORDER BY updated_at DESC, id DESC
        """
    ).fetchall()
    return [
        {
            "id": row["id"], "name": row["name"], "description": row["description"],
            "url": row["url"], "iconUrl": row["icon_url"] or _default_external_system_icon(row["url"]),
            "createdAt": row["created_at"], "updatedAt": row["updated_at"],
        }
        for row in rows
    ]


def _default_external_system_icon(url):
    try:
        parsed = urlparse(url)
    except (TypeError, ValueError):
        return None
    if parsed.hostname == "playful-centaur-45662c.netlify.app":
        return "https://playful-centaur-45662c.netlify.app/icon-180.png"
    return None


def _clean_external_system_link(payload):
    name = payload.name.strip()
    description = payload.description.strip()
    url = payload.url.strip()
    icon_url = (payload.icon_url or "").strip() or _default_external_system_icon(url)
    parsed = urlparse(url)
    if not name or not description or not url:
        raise HTTPException(status_code=400, detail="システム名・内容・URLを入力してください")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="URLはhttp://またはhttps://から入力してください")
    if icon_url:
        parsed_icon = urlparse(icon_url)
        if parsed_icon.scheme not in {"http", "https"} or not parsed_icon.netloc:
            raise HTTPException(status_code=400, detail="アイコン画像URLはhttp://またはhttps://から入力してください")
    return name, description, url, icon_url


def _show_next_performance(conn):
    row = conn.execute(
        """
        SELECT show_next_performance_home
        FROM settings
        WHERE id = 1
        """
    ).fetchone()
    return True if row is None else bool(row["show_next_performance_home"])


def _leave_credit_available(conn, member_id, target_date, feature_enabled=None):
    if feature_enabled is None:
        feature_enabled = _leave_feature_enabled(conn)
    if not feature_enabled:
        return 0
    _grant_monthly_leave_credits(conn, datetime.strptime(target_date, "%Y-%m-%d").date())
    row = conn.execute(
        """
        SELECT COALESCE(SUM(credits_granted - credits_used), 0) AS available
        FROM leave_credits
        WHERE member_id = ?
        AND expires_on >= ?
        AND credits_granted > credits_used
        """,
        (member_id, target_date),
    ).fetchone()
    return int(row["available"] or 0)


def _leave_month_bounds(target):
    first_day = target.replace(day=1)
    last_day = target.replace(day=calendar.monthrange(target.year, target.month)[1])
    return first_day, last_day


def _previous_month(target):
    return date(target.year - 1, 12, 1) if target.month == 1 else date(target.year, target.month - 1, 1)


def _ensure_leave_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS feature_flags (
            feature_key TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1,
            updated_by INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO feature_flags (feature_key, enabled)
        VALUES ('leave_credit', 1)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS feature_metadata (
            feature_key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    flag = conn.execute(
        "SELECT enabled FROM feature_flags WHERE feature_key = 'leave_credit'"
    ).fetchone()
    if flag is not None and bool(flag["enabled"]):
        conn.execute(
            """
            INSERT OR IGNORE INTO feature_metadata (feature_key, value)
            VALUES ('leave_credit_started_on', ?)
            """,
            (date.today().isoformat(),),
        )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_credits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            grant_month TEXT NOT NULL,
            eligible_month TEXT NOT NULL,
            expires_on TEXT NOT NULL,
            credits_granted INTEGER DEFAULT 1,
            credits_used INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(member_id, grant_month)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            event_id INTEGER NOT NULL,
            attendance_id INTEGER NOT NULL,
            credit_id INTEGER NOT NULL,
            status TEXT DEFAULT '申請中',
            requested_at TEXT DEFAULT CURRENT_TIMESTAMP,
            reviewed_by INTEGER,
            reviewed_at TEXT,
            UNIQUE(member_id, event_id)
        )
        """
    )


def _leave_feature_enabled(conn):
    _ensure_leave_schema(conn)
    row = conn.execute(
        "SELECT enabled FROM feature_flags WHERE feature_key = 'leave_credit'"
    ).fetchone()
    return True if row is None else bool(row["enabled"])


def _leave_feature_started_on(conn):
    _ensure_leave_schema(conn)
    row = conn.execute(
        "SELECT value FROM feature_metadata WHERE feature_key = 'leave_credit_started_on'"
    ).fetchone()
    if row is None or not row["value"]:
        return None
    try:
        return datetime.strptime(row["value"], "%Y-%m-%d").date()
    except ValueError:
        return None


def _grant_monthly_leave_credits(conn, today):
    _ensure_leave_schema(conn)
    eligible_start, eligible_end = _leave_month_bounds(_previous_month(today))
    started_on = _leave_feature_started_on(conn)
    if started_on is None or started_on > eligible_end:
        return
    if started_on > eligible_start:
        eligible_start = started_on
    grant_start, grant_end = _leave_month_bounds(today)
    event_rows = conn.execute(
        """
        SELECT id FROM events
        WHERE date BETWEEN ? AND ?
        """,
        (eligible_start.isoformat(), eligible_end.isoformat()),
    ).fetchall()
    event_ids = [int(row["id"]) for row in event_rows]
    if not event_ids:
        return

    placeholders = ",".join("?" for _ in event_ids)
    members = conn.execute(
        """
        SELECT id FROM members
        WHERE status = '在籍' AND role NOT IN ('管理者', '顧問', '先生')
        """
    ).fetchall()
    for member in members:
        attended = conn.execute(
            f"""
            SELECT COUNT(DISTINCT event_id) AS count
            FROM attendance
            WHERE member_id = ? AND event_id IN ({placeholders})
              AND status = '出席' AND approval_status = '承認済み'
            """,
            [int(member["id"])] + event_ids,
        ).fetchone()
        if int(attended["count"] or 0) == len(event_ids):
            conn.execute(
                """
                INSERT OR IGNORE INTO leave_credits
                (member_id, grant_month, eligible_month, expires_on, credits_granted, credits_used)
                VALUES (?, ?, ?, ?, 1, 0)
                """,
                (
                    int(member["id"]),
                    grant_start.strftime("%Y-%m"),
                    eligible_start.strftime("%Y-%m"),
                    grant_end.isoformat(),
                ),
            )
    conn.commit()


def _has_attendance_for_today(conn, member_id, events):
    if not events:
        return True
    event_ids = [int(row["id"]) for row in events]
    placeholders = ",".join("?" for _ in event_ids)
    row = conn.execute(
        f"""
        SELECT COUNT(DISTINCT event_id) AS count
        FROM attendance
        WHERE member_id = ?
        AND event_id IN ({placeholders})
        """,
        [member_id] + event_ids,
    ).fetchone()
    return int(row["count"] or 0) >= len(event_ids)


def _unread_announcement_count(conn, member):
    ensure_announcement_teacher_column(conn)
    if member["role"] == "顧問":
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM announcements a
            LEFT JOIN announcement_reads ar
              ON ar.announcement_id = a.id AND ar.member_id = ?
            WHERE ar.member_id IS NULL AND (a.send_to_teacher = 1 OR a.created_by = ?)
            """,
            (int(member["id"]), int(member["id"])),
        ).fetchone()
        return int(row["count"] or 0)
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM announcements a
        LEFT JOIN announcement_reads ar
          ON ar.announcement_id = a.id AND ar.member_id = ?
        WHERE ar.member_id IS NULL
          AND (
            a.target_type = '全体'
            OR (a.target_type = 'パート' AND a.target_part = ?)
            OR (a.target_type = '学年' AND a.target_grade = ?)
            OR (a.target_type = '木管' AND ? IN ('フルート', 'クラリネット', 'サックス'))
            OR (a.target_type = '金管' AND ? IN ('トランペット', 'ホルン', 'トロンボーン', 'ユーフォニアム', 'バスパート'))
          )
        """,
        (int(member["id"]), member["part"], member["grade"], member["part"], member["part"]),
    ).fetchone()
    return int(row["count"] or 0)


def _home_tasks(conn, member, target_date, events, unread_announcement_count):
    role = member["role"]
    member_id = int(member["id"])
    has_events = bool(events)
    tasks = [{"key": "check_schedule", "label": "今日の予定を確認", "completed": True, "note": "ホームで確認できます"}]

    if role in {"一般部員", "パートリーダー", "部長", "副部長"} and has_events:
        answered = _has_attendance_for_today(conn, member_id, events)
        tasks.append(
            {
                "key": "register_attendance",
                "label": "出席登録をする",
                "completed": answered,
                "note": "今日の予定に回答済み" if answered else "今日の予定に回答してください",
            }
        )

    tasks.append(
        {
            "key": "check_notifications",
            "label": "お知らせを確認",
            "completed": unread_announcement_count == 0,
            "note": "未読なし" if unread_announcement_count == 0 else f"未読 {unread_announcement_count}件",
        }
    )
    return {
        "date": target_date,
        "hasEvents": has_events,
        "items": tasks,
    }


def _attendance_stats(conn, member_id: int, today: str):
    today_date = datetime.strptime(today, "%Y-%m-%d").date()
    month_keys = []
    cursor = today_date.replace(day=1)
    for _ in range(6):
        month_keys.append(cursor.strftime("%Y-%m"))
        if cursor.month == 1:
            cursor = cursor.replace(year=cursor.year - 1, month=12)
        else:
            cursor = cursor.replace(month=cursor.month - 1)
    month_keys.reverse()

    rows = conn.execute(
        """
        SELECT
            substr(e.date, 1, 7) AS month,
            COUNT(e.id) AS scheduled,
            COUNT(CASE
                WHEN a.approval_status = '承認済み'
                AND a.status IN ('出席', '遅刻', '早退')
                THEN 1
            END) AS attended,
            COUNT(CASE
                WHEN a.approval_status = '承認済み'
                AND a.status = '欠席'
                THEN 1
            END) AS absent,
            COUNT(CASE
                WHEN a.id IS NOT NULL
                AND a.approval_status != '承認済み'
                THEN 1
            END) AS pending
        FROM events e
        LEFT JOIN attendance a
            ON a.event_id = e.id
            AND a.member_id = ?
        WHERE e.date BETWEEN ? AND ?
        GROUP BY substr(e.date, 1, 7)
        ORDER BY month
        """,
        (member_id, f"{month_keys[0]}-01", today),
    ).fetchall()

    by_month = {row["month"]: row for row in rows}
    monthly = []
    for month in month_keys:
        row = by_month.get(month)
        scheduled = int(row["scheduled"] if row else 0)
        attended = int(row["attended"] if row else 0)
        absent = int(row["absent"] if row else 0)
        pending = int(row["pending"] if row else 0)
        unanswered = max(scheduled - attended - absent - pending, 0)
        answered = max(scheduled - unanswered, 0)
        monthly.append(
            {
                "month": month,
                "label": f"{int(month[5:])}月",
                "scheduled": scheduled,
                "attended": attended,
                "absent": absent,
                "pending": pending,
                "unanswered": unanswered,
                "answered": answered,
                "rate": round(attended * 100 / answered, 1) if answered else None,
            }
        )

    current = monthly[-1]
    return {
        "period": current["month"],
        "throughDate": today,
        "rate": current["rate"],
        "scheduled": current["scheduled"],
        "attended": current["attended"],
        "absent": current["absent"],
        "pending": current["pending"],
        "unanswered": current["unanswered"],
        "answered": current["answered"],
        "monthly": monthly,
    }


@app.get("/api/home")
def home(target_date: str | None = None, member=Depends(get_current_member)):
    today = target_date or datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
    member_id = int(member["id"])

    conn = get_connection()
    events = _today_events(conn, today, member_id)
    unread_notifications = _visible_unread_notifications(conn, member_id, today, bool(events))
    show_next_performance = _show_next_performance(conn)
    next_performance = _next_performance(conn, today) if show_next_performance else None
    birthday_highlight = _birthdays(conn, today)
    leave_feature_enabled = _leave_feature_enabled(conn)
    leave_credit_available = _leave_credit_available(conn, member_id, today, leave_feature_enabled)
    external_system_links = _external_system_links(conn)
    unread_announcement_count = _unread_announcement_count(conn, member)
    task_data = _home_tasks(conn, member, today, events, unread_announcement_count)
    attendance_stats = _attendance_stats(conn, member_id, today)
    birthday_messages = _birthday_messages_for_member(conn, member_id, today)
    sent_birthday_messages = (
        _sent_birthday_messages(conn, member_id, today)
        if birthday_highlight["isToday"]
        else []
    )
    conn.close()

    return {
        "today": today,
        "showNextPerformance": show_next_performance,
        "nextPerformance": next_performance,
        "todayEvents": [
            {
                **_event_to_home_item(row),
                "myAttendance": None
                if row["my_status"] is None
                else {
                    "status": row["my_status"],
                    "approvalStatus": row["my_approval_status"],
                },
            }
            for row in events
        ],
        "unreadNotifications": unread_notifications,
        "birthdays": birthday_highlight["items"],
        "birthdayDate": birthday_highlight["date"],
        "birthdaysAreToday": birthday_highlight["isToday"],
        "myBirthdayToday": bool(member["birthday"] and str(member["birthday"])[5:10] == today[5:10]),
        "birthdayMessages": birthday_messages,
        "sentBirthdayMessageRecipientIds": [item["recipientId"] for item in sent_birthday_messages],
        "sentBirthdayMessages": sent_birthday_messages,
        "leaveCredits": {"enabled": leave_feature_enabled, "available": leave_credit_available},
        "externalSystemLinks": external_system_links,
        "taskDate": task_data["date"],
        "taskHasEvents": task_data["hasEvents"],
        "tasks": task_data["items"],
        "attendanceStats": attendance_stats,
    }


@app.post("/api/birthday-messages")
def send_birthday_message(payload: BirthdayMessageRequest, member=Depends(get_current_member)):
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="お祝いメッセージを入力してください")
    if len(message) > 80:
        raise HTTPException(status_code=400, detail="お祝いメッセージは80文字以内にしてください")
    if int(payload.recipient_id) == int(member["id"]):
        raise HTTPException(status_code=400, detail="自分には送信できません")

    today = datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
    conn = get_connection()
    _ensure_birthday_messages_table(conn)
    recipient = conn.execute(
        "SELECT id, name, birthday FROM members WHERE id = ? AND status = '在籍'",
        (payload.recipient_id,),
    ).fetchone()
    if recipient is None:
        conn.close()
        raise HTTPException(status_code=404, detail="送信先の部員が見つかりません")
    if not recipient["birthday"] or str(recipient["birthday"])[5:10] != today[5:10]:
        conn.close()
        raise HTTPException(status_code=400, detail="お祝いメッセージは誕生日当日だけ送れます")

    existing_message = conn.execute(
        "SELECT id FROM birthday_messages WHERE sender_id = ? AND recipient_id = ? AND celebration_year = ?",
        (member["id"], recipient["id"], int(today[:4])),
    ).fetchone()
    conn.execute(
        """
        INSERT INTO birthday_messages (sender_id, recipient_id, celebration_year, message)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(sender_id, recipient_id, celebration_year)
        DO UPDATE SET message = excluded.message, updated_at = CURRENT_TIMESTAMP
        """,
        (member["id"], recipient["id"], int(today[:4]), message),
    )
    if existing_message is None:
        conn.execute(
            """
            INSERT INTO notifications (target_member_id, notification_type, title, message)
            VALUES (?, 'birthday_message', 'お祝いメッセージが届きました', ?)
            """,
            (recipient["id"], f"{member['name']}さんから誕生日メッセージが届きました。"),
        )
    conn.commit()
    conn.close()
    return {"sent": True, "message": "お祝いメッセージを送りました。"}


@app.post("/api/birthday-messages/{message_id}/reaction")
def react_to_birthday_message(message_id: int, member=Depends(get_current_member)):
    conn = get_connection()
    _ensure_birthday_messages_table(conn)
    birthday_message = conn.execute(
        """
        SELECT id, sender_id, reacted_at
        FROM birthday_messages
        WHERE id = ? AND recipient_id = ?
        """,
        (message_id, member["id"]),
    ).fetchone()
    if birthday_message is None:
        conn.close()
        raise HTTPException(status_code=404, detail="お祝いメッセージが見つかりません")

    if not birthday_message["reacted_at"]:
        conn.execute(
            "UPDATE birthday_messages SET reacted_at = CURRENT_TIMESTAMP WHERE id = ?",
            (message_id,),
        )
        conn.execute(
            """
            INSERT INTO notifications (target_member_id, notification_type, title, message)
            VALUES (?, 'birthday_reaction', '誕生日メッセージに星が届きました', ?)
            """,
            (birthday_message["sender_id"], f"{member['name']}さんから星が届きました。"),
        )
        conn.commit()
    conn.close()
    return {"messageId": message_id, "reacted": True}


@app.get("/api/home/next-performance")
def home_next_performance(target_date: str | None = None, member=Depends(get_current_member)):
    today = target_date or date.today().isoformat()
    conn = get_connection()
    show_next_performance = _show_next_performance(conn)
    next_performance = _next_performance(conn, today) if show_next_performance else None
    conn.close()
    return {
        "today": today,
        "showNextPerformance": show_next_performance,
        "nextPerformance": next_performance,
    }


@app.post("/api/admin/external-system-links")
def create_external_system_link(payload: ExternalSystemLinkRequest, member=Depends(get_current_member)):
    _require_admin(member)
    name, description, url, icon_url = _clean_external_system_link(payload)
    conn = get_connection()
    _ensure_external_system_links_table(conn)
    cursor = conn.execute(
        """
        INSERT INTO external_system_links (name, description, url, icon_url, created_by)
        VALUES (?, ?, ?, ?, ?)
        """,
        (name, description, url, icon_url, int(member["id"])),
    )
    conn.commit()
    link_id = int(cursor.lastrowid)
    conn.close()
    return {"linkId": link_id, "created": True}


@app.patch("/api/admin/external-system-links/{link_id}")
def update_external_system_link(link_id: int, payload: ExternalSystemLinkRequest, member=Depends(get_current_member)):
    _require_admin(member)
    name, description, url, icon_url = _clean_external_system_link(payload)
    conn = get_connection()
    _ensure_external_system_links_table(conn)
    existing = conn.execute("SELECT id FROM external_system_links WHERE id = ?", (link_id,)).fetchone()
    if existing is None:
        conn.close()
        raise HTTPException(status_code=404, detail="関連システムが見つかりません")
    conn.execute(
        """
        UPDATE external_system_links
        SET name = ?, description = ?, url = ?, icon_url = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (name, description, url, icon_url, link_id),
    )
    conn.commit()
    conn.close()
    return {"linkId": link_id, "updated": True}


@app.delete("/api/admin/external-system-links/{link_id}")
def delete_external_system_link(link_id: int, member=Depends(get_current_member)):
    _require_admin(member)
    conn = get_connection()
    _ensure_external_system_links_table(conn)
    existing = conn.execute("SELECT id FROM external_system_links WHERE id = ?", (link_id,)).fetchone()
    if existing is None:
        conn.close()
        raise HTTPException(status_code=404, detail="関連システムが見つかりません")
    conn.execute("DELETE FROM external_system_links WHERE id = ?", (link_id,))
    conn.commit()
    conn.close()
    return {"linkId": link_id, "deleted": True}


@app.post("/api/notifications/read-visible")
def mark_visible_notifications_read(member=Depends(get_current_member)):
    member_id = int(member["id"])
    today = date.today().isoformat()
    conn = get_connection()
    events = _today_events(conn, today, member_id)
    visible_notifications = _visible_unread_notifications(conn, member_id, today, bool(events))
    notification_ids = [int(item["id"]) for item in visible_notifications]
    updated = 0
    if notification_ids:
        placeholders = ",".join("?" for _ in notification_ids)
        updated = conn.execute(
            f"""
            UPDATE notifications
            SET is_read = 1
            WHERE target_member_id = ?
            AND id IN ({placeholders})
            """,
            [member_id] + notification_ids,
        ).rowcount
        conn.commit()
    conn.close()
    return {"updated": int(updated or 0)}


@app.get("/api/notifications")
def notifications(filter: str = "unread", member=Depends(get_current_member)):
    if filter not in {"unread", "all"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="filter must be unread or all",
        )

    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, notification_type, title, message, related_attendance_id, is_read, created_at
        FROM notifications
        WHERE target_member_id = ?
        AND notification_type = 'approval_request'
        ORDER BY is_read ASC, created_at DESC, id DESC
        """,
        (member["id"],),
    ).fetchall()
    conn.close()

    items = [
        {
            "id": int(row["id"]),
            "type": row["notification_type"],
            "title": row["title"],
            "message": row["message"],
            "relatedAttendanceId": row["related_attendance_id"],
            "isRead": bool(row["is_read"]),
            "createdAt": row["created_at"],
        }
        for row in rows
        if filter == "all" or not bool(row["is_read"])
    ]
    return {"filter": filter, "notifications": items}


@app.post("/api/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, member=Depends(get_current_member)):
    conn = get_connection()
    updated = conn.execute(
        """
        UPDATE notifications
        SET is_read = 1
        WHERE id = ?
        AND target_member_id = ?
        """,
        (notification_id, member["id"]),
    ).rowcount
    conn.commit()
    conn.close()
    if not updated:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"notificationId": notification_id, "isRead": True}


@app.get("/api/attendance/stats")
def attendance_stats(member=Depends(get_current_member)):
    conn = get_connection()
    stats = _attendance_stats(conn, int(member["id"]), date.today().isoformat())
    conn.close()
    return stats


def _attendance_submission_dates(conn, today):
    row = conn.execute(
        """
        SELECT
            (SELECT MAX(date) FROM events WHERE date < ?) AS previous_date,
            (SELECT MIN(date) FROM events WHERE date >= ?) AS next_date
        """,
        (today, today),
    ).fetchone()
    return {value for value in (row["previous_date"], row["next_date"]) if value}


@app.get("/api/attendance/targets")
def attendance_targets(member=Depends(get_current_member)):
    attend_roles = {"一般部員", "パートリーダー", "部長", "副部長"}
    if member["role"] not in attend_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This role cannot submit attendance",
        )

    today = date.today().isoformat()
    member_id = int(member["id"])
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT
            e.id,
            e.date,
            e.start_time,
            e.end_time,
            e.event_type,
            e.title,
            e.location,
            e.memo,
            COUNT(CASE WHEN ac.status = '出席' AND ac.approval_status = '承認済み' THEN 1 END) AS attendance_count,
            mine.status AS my_status,
            mine.approval_status AS my_approval_status,
            mine.id AS my_attendance_id
        FROM events e
        LEFT JOIN attendance ac
            ON ac.event_id = e.id
        LEFT JOIN attendance mine
            ON mine.event_id = e.id
            AND mine.member_id = ?
        WHERE e.date = (SELECT MAX(date) FROM events WHERE date < ?)
        OR e.date >= ?
        GROUP BY e.id, mine.id, mine.status, mine.approval_status
        ORDER BY
            CASE WHEN e.date < ? THEN 0 ELSE 1 END,
            e.date ASC,
            e.start_time,
            e.id
        """,
        (member_id, today, today, today),
    ).fetchall()
    attendance_submission_dates = _attendance_submission_dates(conn, today)
    conn.close()

    items = []
    for row in rows:
        item = dict(row)
        item["can_attend_today"] = item["date"] == today
        item["is_past_unanswered"] = item["date"] < today and item["my_status"] is None
        item["can_select_attendance"] = item["date"] in attendance_submission_dates
        items.append(_event_to_calendar_item(item))

    return {"events": items}


def _require_event_editor(member):
    if member["role"] not in EVENT_EDITORS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This role cannot edit events",
        )


def _clean_event_payload(payload: EventUpsertRequest):
    try:
        datetime.strptime(payload.date, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date must be YYYY-MM-DD",
        ) from exc

    event_type = payload.event_type.strip()
    title = payload.title.strip()
    if event_type not in EVENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid event type",
        )
    if not title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Title is required",
        )

    return {
        "date": payload.date,
        "start_time": (payload.start_time or "").strip() or None,
        "end_time": (payload.end_time or "").strip() or None,
        "event_type": event_type,
        "title": title,
        "location": (payload.location or "").strip() or None,
        "memo": (payload.memo or "").strip() or None,
        "teacher_visit": bool(payload.teacher_visit),
    }


@app.post("/api/events")
def create_event(payload: EventUpsertRequest, member=Depends(get_current_member)):
    _require_event_editor(member)
    item = _clean_event_payload(payload)
    conn = get_connection()
    ensure_event_teacher_visit_column(conn)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO events
        (date, start_time, end_time, event_type, title, location, memo, teacher_visit, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item["date"],
            item["start_time"],
            item["end_time"],
            item["event_type"],
            item["title"],
            item["location"],
            item["memo"],
            int(item["teacher_visit"]),
            member["id"],
        ),
    )
    event_id = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return {"eventId": event_id, "created": True}


@app.patch("/api/events/{event_id}")
def update_event(event_id: int, payload: EventUpsertRequest, member=Depends(get_current_member)):
    _require_event_editor(member)
    item = _clean_event_payload(payload)
    conn = get_connection()
    ensure_event_teacher_visit_column(conn)
    cur = conn.cursor()
    existing = cur.execute("SELECT id FROM events WHERE id = ?", (event_id,)).fetchone()
    if existing is None:
        conn.close()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    cur.execute(
        """
        UPDATE events
        SET date = ?, start_time = ?, end_time = ?, event_type = ?,
            title = ?, location = ?, memo = ?, teacher_visit = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            item["date"],
            item["start_time"],
            item["end_time"],
            item["event_type"],
            item["title"],
            item["location"],
            item["memo"],
            int(item["teacher_visit"]),
            event_id,
        ),
    )
    conn.commit()
    conn.close()
    return {"eventId": event_id, "updated": True}


@app.delete("/api/events/{event_id}")
def delete_event(event_id: int, member=Depends(get_current_member)):
    _require_event_editor(member)
    conn = get_connection()
    cur = conn.cursor()
    existing = cur.execute("SELECT id FROM events WHERE id = ?", (event_id,)).fetchone()
    if existing is None:
        conn.close()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    attendance_count = cur.execute(
        "SELECT COUNT(*) AS count FROM attendance WHERE event_id = ?",
        (event_id,),
    ).fetchone()["count"]
    if attendance_count:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="出席記録がある予定は削除できません",
        )
    cur.execute("DELETE FROM events WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()
    return {"eventId": event_id, "deleted": True}


@app.get("/api/events")
def events(month: str | None = None, member=Depends(get_current_member)):
    selected_month = month or date.today().strftime("%Y-%m")
    try:
        month_start = datetime.strptime(f"{selected_month}-01", "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="month must be YYYY-MM",
        ) from exc

    if month_start.month == 12:
        next_month = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month = month_start.replace(month=month_start.month + 1)

    month_end = (next_month - date.resolution).isoformat()
    today = date.today().isoformat()
    member_id = int(member["id"])
    attend_roles = {"一般部員", "パートリーダー", "部長", "副部長"}

    conn = get_connection()
    ensure_event_teacher_visit_column(conn)
    rows = conn.execute(
        """
        SELECT
            e.id,
            e.date,
            e.start_time,
            e.end_time,
            e.event_type,
            e.title,
            e.location,
            e.memo,
            e.teacher_visit,
            COUNT(CASE WHEN ac.status = '出席' AND ac.approval_status = '承認済み' THEN 1 END) AS attendance_count,
            mine.id AS my_attendance_id,
            mine.status AS my_status,
            mine.approval_status AS my_approval_status
        FROM events e
        LEFT JOIN attendance ac
            ON ac.event_id = e.id
        LEFT JOIN attendance mine
            ON mine.event_id = e.id
            AND mine.member_id = ?
        WHERE e.date BETWEEN ? AND ?
        GROUP BY e.id, mine.id, mine.status, mine.approval_status
        ORDER BY e.date, e.start_time, e.id
        """,
        (member_id, month_start.isoformat(), month_end),
    ).fetchall()
    approved_absence_rows = conn.execute(
        """
        SELECT a.event_id, a.status, m.name, m.part
        FROM attendance a
        JOIN members m ON m.id = a.member_id
        JOIN events e ON e.id = a.event_id
        WHERE e.date BETWEEN ? AND ?
          AND a.approval_status = '承認済み'
          AND a.status IN ('欠席', '遅刻', '早退')
          AND m.status = '在籍'
        ORDER BY e.date, e.start_time, m.part, m.grade DESC, m.name
        """,
        (month_start.isoformat(), month_end),
    ).fetchall()
    conn.close()

    approved_absences_by_event = {}
    for absence in approved_absence_rows:
        approved_absences_by_event.setdefault(int(absence["event_id"]), []).append({
            "name": absence["name"],
            "part": absence["part"],
            "status": absence["status"],
        })

    enriched = []
    for row in rows:
        item = dict(row)
        item["can_attend_today"] = item["date"] == today and member["role"] in attend_roles
        item["approved_absences"] = approved_absences_by_event.get(int(item["id"]), [])
        enriched.append(_event_to_calendar_item(item))

    return {
        "month": selected_month,
        "events": enriched,
    }


def _reflection_event(conn, event_id: int):
    event = conn.execute(
        "SELECT id, date, title, event_type, end_time FROM events WHERE id = ?",
        (event_id,),
    ).fetchone()
    if event is None:
        raise HTTPException(status_code=404, detail="予定が見つかりません")
    now = datetime.now(ZoneInfo("Asia/Tokyo"))
    if event["date"] > now.date().isoformat() or (
        event["date"] == now.date().isoformat()
        and event["end_time"]
        and str(event["end_time"])[:5] > now.strftime("%H:%M")
    ):
        raise HTTPException(status_code=400, detail="終了した練習にだけ振り返りを投稿できます")
    return event


def _reflection_scopes(member):
    return ["全体", *_instrument_group_scopes(member["part"]), member["part"]]


def _reflection_item(row, member):
    return {
        "id": int(row["id"]), "eventId": int(row["event_id"]),
        "targetScope": row["target_scope"], "title": row["title"], "content": row["content"],
        "createdBy": row["creator_name"], "createdById": int(row["created_by"]),
        "createdAt": row["created_at"], "updatedAt": row["updated_at"],
        "canEdit": int(row["created_by"]) == int(member["id"]),
    }


@app.get("/api/events/{event_id}/reflections")
def practice_reflections(event_id: int, member=Depends(get_current_member)):
    conn = get_connection()
    _ensure_practice_reflections_schema(conn)
    event = _reflection_event(conn, event_id)
    if member["role"] == "管理者":
        rows = conn.execute(
            """
            SELECT pr.*, creator.name creator_name FROM practice_reflections pr
            JOIN members creator ON creator.id=pr.created_by
            WHERE pr.event_id=? ORDER BY pr.created_at DESC, pr.id DESC
            """, (event_id,),
        ).fetchall()
    else:
        scopes = list(dict.fromkeys(_reflection_scopes(member)))
        placeholders = ",".join("?" for _ in scopes)
        rows = conn.execute(
            f"""
            SELECT pr.*, creator.name creator_name FROM practice_reflections pr
            JOIN members creator ON creator.id=pr.created_by
            WHERE pr.event_id=? AND (pr.target_scope IN ({placeholders}) OR pr.created_by=?)
            ORDER BY pr.created_at DESC, pr.id DESC
            """, [event_id, *scopes, member["id"]],
        ).fetchall()
    conn.close()
    return {
        "event": {"id": int(event["id"]), "date": event["date"], "title": event["title"], "type": event["event_type"]},
        "items": [_reflection_item(row, member) for row in rows],
        "availableScopes": ["全体", "金管", "木管", *PARTS],
    }


@app.post("/api/events/{event_id}/reflections")
def create_practice_reflection(event_id: int, payload: PracticeReflectionRequest, member=Depends(get_current_member)):
    title, content = payload.title.strip(), payload.content.strip()
    allowed_scopes = {"全体", "金管", "木管", *PARTS}
    if payload.target_scope not in allowed_scopes:
        raise HTTPException(status_code=400, detail="公開範囲が正しくありません")
    if not title or not content:
        raise HTTPException(status_code=400, detail="タイトルと振り返り内容を入力してください")
    conn = get_connection()
    _ensure_practice_reflections_schema(conn)
    _reflection_event(conn, event_id)
    cur = conn.execute(
        "INSERT INTO practice_reflections (event_id,target_scope,title,content,created_by) VALUES (?,?,?,?,?)",
        (event_id, payload.target_scope, title, content, member["id"]),
    )
    conn.commit()
    reflection_id = int(cur.lastrowid)
    conn.close()
    return {"reflectionId": reflection_id, "created": True}


@app.patch("/api/events/{event_id}/reflections/{reflection_id}")
def update_practice_reflection(event_id: int, reflection_id: int, payload: PracticeReflectionRequest, member=Depends(get_current_member)):
    title, content = payload.title.strip(), payload.content.strip()
    allowed_scopes = {"全体", "金管", "木管", *PARTS}
    if payload.target_scope not in allowed_scopes or not title or not content:
        raise HTTPException(status_code=400, detail="公開範囲・タイトル・内容を確認してください")
    conn = get_connection()
    _ensure_practice_reflections_schema(conn)
    row = conn.execute("SELECT created_by FROM practice_reflections WHERE id=? AND event_id=?", (reflection_id, event_id)).fetchone()
    if row is None:
        conn.close(); raise HTTPException(status_code=404, detail="振り返りが見つかりません")
    if int(row["created_by"]) != int(member["id"]):
        conn.close(); raise HTTPException(status_code=403, detail="投稿者本人だけが編集できます")
    conn.execute(
        "UPDATE practice_reflections SET target_scope=?,title=?,content=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (payload.target_scope, title, content, reflection_id),
    )
    conn.commit(); conn.close()
    return {"reflectionId": reflection_id, "updated": True}


@app.delete("/api/events/{event_id}/reflections/{reflection_id}")
def delete_practice_reflection(event_id: int, reflection_id: int, member=Depends(get_current_member)):
    conn = get_connection(); _ensure_practice_reflections_schema(conn)
    row = conn.execute("SELECT created_by FROM practice_reflections WHERE id=? AND event_id=?", (reflection_id, event_id)).fetchone()
    if row is None:
        conn.close(); raise HTTPException(status_code=404, detail="振り返りが見つかりません")
    if int(row["created_by"]) != int(member["id"]):
        conn.close(); raise HTTPException(status_code=403, detail="投稿者本人だけが削除できます")
    conn.execute("DELETE FROM practice_reflections WHERE id=?", (reflection_id,))
    conn.commit(); conn.close()
    return {"reflectionId": reflection_id, "deleted": True}


@app.post("/api/attendance/confirm")
def confirm_attendance(payload: AttendanceConfirmRequest, member=Depends(get_current_member)):
    attend_roles = {"一般部員", "パートリーダー", "部長", "副部長"}
    if member["role"] not in attend_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This role cannot confirm attendance",
        )

    member_id = int(member["id"])
    today = date.today().isoformat()
    conn = get_connection()
    cur = conn.cursor()

    event = cur.execute(
        """
        SELECT id, date, title, event_type
        FROM events
        WHERE id = ?
        """,
        (payload.event_id,),
    ).fetchone()

    if event is None:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    if event["date"] != today:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Attendance can only be confirmed for today's events",
        )

    existing = cur.execute(
        """
        SELECT id
        FROM attendance
        WHERE member_id = ?
        AND event_id = ?
        """,
        (member_id, payload.event_id),
    ).fetchone()

    if existing:
        attendance_id = int(existing["id"])
        cur.execute(
            """
            UPDATE attendance
            SET status = '出席',
                reason = 'カレンダーの出席ボタンから参加確認',
                approval_status = '承認済み',
                absence_type = 'なし',
                approved_by = ?,
                approved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (member_id, attendance_id),
        )
    else:
        cur.execute(
            """
            INSERT INTO attendance
            (member_id, event_id, status, reason, approval_status, absence_type, approved_by, approved_at)
            VALUES (?, ?, '出席', 'カレンダーの出席ボタンから参加確認', '承認済み', 'なし', ?, CURRENT_TIMESTAMP)
            """,
            (member_id, payload.event_id, member_id),
        )
        attendance_id = int(cur.lastrowid)

    conn.commit()
    conn.close()

    return {
        "attendanceId": attendance_id,
        "eventId": payload.event_id,
        "status": "出席",
        "approvalStatus": "承認済み",
    }


@app.post("/api/attendance")
def submit_attendance(payload: AttendanceSubmitRequest, member=Depends(get_current_member)):
    attend_roles = {"一般部員", "パートリーダー", "部長", "副部長"}
    if member["role"] not in attend_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This role cannot submit attendance",
        )

    allowed_statuses = {"出席", "欠席", "遅刻", "早退"}
    if payload.status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid attendance status",
        )

    member_id = int(member["id"])
    today = date.today().isoformat()
    reason = (payload.reason or "").strip()
    conn = get_connection()
    cur = conn.cursor()

    event = cur.execute(
        """
        SELECT id, date, title, event_type
        FROM events
        WHERE id = ?
        """,
        (payload.event_id,),
    ).fetchone()

    if event is None:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )

    attendance_submission_dates = _attendance_submission_dates(conn, today)
    if payload.status == "出席" and event["date"] not in attendance_submission_dates:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="出席を選べるのは直前または直近の予定だけです",
        )
    if payload.status != "出席" and event["date"] < today and event["date"] not in attendance_submission_dates:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="過去の欠席・遅刻・早退申請は直前の予定にのみ行えます",
        )

    existing = cur.execute(
        """
        SELECT id
        FROM attendance
        WHERE member_id = ?
        AND event_id = ?
        """,
        (member_id, payload.event_id),
    ).fetchone()

    if event["date"] < today and existing:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="過去の回答済み予定は変更できません",
        )

    approval_status = "承認済み" if payload.status == "出席" else "未承認"
    approved_by = member_id if payload.status == "出席" else None

    if existing:
        attendance_id = int(existing["id"])
        cur.execute(
            """
            UPDATE attendance
            SET status = ?,
                reason = ?,
                approval_status = ?,
                absence_type = 'なし',
                approved_by = ?,
                approved_at = CASE WHEN ? = '承認済み' THEN CURRENT_TIMESTAMP ELSE NULL END,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (payload.status, reason, approval_status, approved_by, approval_status, attendance_id),
        )
    else:
        cur.execute(
            """
            INSERT INTO attendance
            (member_id, event_id, status, reason, approval_status, absence_type, approved_by, approved_at)
            VALUES (?, ?, ?, ?, ?, 'なし', ?, CASE WHEN ? = '承認済み' THEN CURRENT_TIMESTAMP ELSE NULL END)
            """,
            (member_id, payload.event_id, payload.status, reason, approval_status, approved_by, approval_status),
        )
        attendance_id = int(cur.lastrowid)

    if payload.status != "出席":
        _notify_part_leaders(conn, member, attendance_id)
    else:
        conn.execute(
            """
            DELETE FROM notifications
            WHERE related_attendance_id = ?
            AND notification_type = 'approval_request'
            """,
            (attendance_id,),
        )
    _ensure_leave_schema(conn)
    conn.execute(
        """
        UPDATE leave_requests SET status = '取消', reviewed_at = CURRENT_TIMESTAMP
        WHERE member_id = ? AND event_id = ? AND status = '申請中'
        """,
        (member_id, payload.event_id),
    )
    conn.commit()
    conn.close()

    return {
        "attendanceId": attendance_id,
        "eventId": payload.event_id,
        "status": payload.status,
        "approvalStatus": approval_status,
    }


def _cancel_own_attendance(attendance_id, member_id, today):
    conn = get_connection()
    row = conn.execute(
        """
        SELECT a.id, a.status, a.approval_status, a.absence_type, e.date
        FROM attendance a
        JOIN events e ON e.id = a.event_id
        WHERE a.id = ? AND a.member_id = ?
        """,
        (attendance_id, member_id),
    ).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="申請が見つかりません")
    if row["date"] < today:
        conn.close()
        raise HTTPException(status_code=400, detail="終了した予定の申請はキャンセルできません")
    if row["status"] not in {"欠席", "遅刻", "早退"}:
        conn.close()
        raise HTTPException(status_code=400, detail="欠席・遅刻・早退申請だけキャンセルできます")

    if row["absence_type"] == "休暇申請":
        _ensure_leave_schema(conn)
        leave_request = conn.execute(
            """
            SELECT credit_id, status
            FROM leave_requests
            WHERE attendance_id = ?
            """,
            (attendance_id,),
        ).fetchone()
        if leave_request and leave_request["status"] == "承認済み":
            conn.execute(
                """
                UPDATE leave_credits
                SET credits_used = CASE WHEN credits_used > 0 THEN credits_used - 1 ELSE 0 END
                WHERE id = ?
                """,
                (leave_request["credit_id"],),
            )
        conn.execute("DELETE FROM leave_requests WHERE attendance_id = ?", (attendance_id,))

    conn.execute("DELETE FROM notifications WHERE related_attendance_id = ?", (attendance_id,))
    conn.execute("DELETE FROM attendance WHERE id = ?", (attendance_id,))
    conn.commit()
    conn.close()
    return {"attendanceId": attendance_id, "canceled": True, "message": "出欠申請をキャンセルしました。"}


@app.delete("/api/attendance/event/{event_id}")
def cancel_own_attendance_request_by_event(event_id: int, member=Depends(get_current_member)):
    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM attendance WHERE event_id = ? AND member_id = ?",
        (event_id, member["id"]),
    ).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="この予定の申請が見つかりません")
    today = datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
    return _cancel_own_attendance(int(row["id"]), int(member["id"]), today)


@app.delete("/api/attendance/{attendance_id}")
def cancel_own_attendance_request(attendance_id: int, member=Depends(get_current_member)):
    today = datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
    return _cancel_own_attendance(attendance_id, int(member["id"]), today)


@app.get("/api/leave-credits")
def leave_credits(member=Depends(get_current_member)):
    member_id = int(member["id"])
    today = date.today()
    conn = get_connection()
    enabled = _leave_feature_enabled(conn)
    if not enabled and member["role"] != "管理者":
        conn.close()
        return {"enabled": False, "available": 0, "credits": []}
    if enabled:
        _grant_monthly_leave_credits(conn, today)
    rows = conn.execute(
        """
        SELECT grant_month, eligible_month, expires_on, credits_granted, credits_used
        FROM leave_credits
        WHERE member_id = ?
        AND expires_on >= ?
        AND credits_granted > credits_used
        ORDER BY grant_month DESC
        """,
        (member_id, today.isoformat()),
    ).fetchall()
    conn.close()
    items = [
        {
            "grantMonth": row["grant_month"],
            "eligibleMonth": row["eligible_month"],
            "expiresOn": row["expires_on"],
            "granted": int(row["credits_granted"] or 0),
            "used": int(row["credits_used"] or 0),
            "remaining": max(0, int(row["credits_granted"] or 0) - int(row["credits_used"] or 0)),
        }
        for row in rows
    ]
    available = sum(item["remaining"] for item in items if item["expiresOn"] >= today.isoformat()) if enabled else 0
    return {"enabled": enabled, "available": available, "credits": items}


@app.post("/api/leave-requests")
def create_leave_request(payload: LeaveRequestCreate, member=Depends(get_current_member)):
    attend_roles = {"一般部員", "パートリーダー", "部長", "副部長"}
    if member["role"] not in attend_roles:
        raise HTTPException(status_code=403, detail="This role cannot request leave")

    member_id = int(member["id"])
    today = date.today()
    conn = get_connection()
    if not _leave_feature_enabled(conn):
        conn.close()
        raise HTTPException(status_code=400, detail="休暇権利機能は現在停止中です")
    _grant_monthly_leave_credits(conn, today)
    event = conn.execute(
        "SELECT id, date, event_type FROM events WHERE id = ?",
        (payload.event_id,),
    ).fetchone()
    if event is None:
        conn.close()
        raise HTTPException(status_code=404, detail="予定が見つかりません")
    if event["event_type"] != "通常練習":
        conn.close()
        raise HTTPException(status_code=400, detail="休暇権利は通常練習にだけ使用できます")
    if event["date"] < today.isoformat():
        conn.close()
        raise HTTPException(status_code=400, detail="過去の予定には休暇権利を使用できません")

    credit = conn.execute(
        """
        SELECT id FROM leave_credits
        WHERE member_id = ? AND expires_on >= ? AND credits_granted > credits_used
        ORDER BY expires_on, grant_month LIMIT 1
        """,
        (member_id, event["date"]),
    ).fetchone()
    if credit is None:
        conn.close()
        raise HTTPException(status_code=400, detail="この予定に使用できる休暇権利がありません")

    existing = conn.execute(
        "SELECT id FROM attendance WHERE member_id = ? AND event_id = ?",
        (member_id, payload.event_id),
    ).fetchone()
    request_reason = f"休暇権利申請：{payload.reason.strip()}" if payload.reason and payload.reason.strip() else "休暇権利申請"
    if existing:
        attendance_id = int(existing["id"])
        conn.execute(
            """
            UPDATE attendance SET status = '欠席', reason = ?, approval_status = '未承認',
                absence_type = '休暇申請', approved_by = NULL, approved_at = NULL,
                updated_at = CURRENT_TIMESTAMP WHERE id = ?
            """,
            (request_reason, attendance_id),
        )
    else:
        cursor = conn.execute(
            """
            INSERT INTO attendance
            (member_id, event_id, status, reason, approval_status, absence_type)
            VALUES (?, ?, '欠席', ?, '未承認', '休暇申請')
            """,
            (member_id, payload.event_id, request_reason),
        )
        attendance_id = int(cursor.lastrowid)

    existing_request = conn.execute(
        "SELECT id FROM leave_requests WHERE member_id = ? AND event_id = ?",
        (member_id, payload.event_id),
    ).fetchone()
    if existing_request:
        conn.execute(
            """
            UPDATE leave_requests SET attendance_id = ?, credit_id = ?, status = '申請中',
                requested_at = CURRENT_TIMESTAMP, reviewed_by = NULL, reviewed_at = NULL
            WHERE id = ?
            """,
            (attendance_id, int(credit["id"]), int(existing_request["id"])),
        )
    else:
        conn.execute(
            """
            INSERT INTO leave_requests (member_id, event_id, attendance_id, credit_id, status)
            VALUES (?, ?, ?, ?, '申請中')
            """,
            (member_id, payload.event_id, attendance_id, int(credit["id"])),
        )
    _notify_part_leaders(conn, member, attendance_id)
    conn.commit()
    conn.close()
    return {"attendanceId": attendance_id, "status": "申請中", "message": "休暇権利の利用を申請しました。"}


@app.get("/api/announcements")
def announcements(filter: str = "unread", member=Depends(get_current_member)):
    if filter not in {"unread", "all"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="filter must be unread or all",
        )

    member_id = int(member["id"])
    conn = get_connection()
    ensure_announcement_teacher_column(conn)
    visibility_sql = "(a.send_to_teacher = 1 OR a.created_by = ?)" if member["role"] == "顧問" else """
        (a.created_by = ? OR
            a.target_type = '全体'
            OR (a.target_type = 'パート' AND a.target_part = ?)
            OR (a.target_type = '学年' AND a.target_grade = ?)
            OR (a.target_type = '木管' AND ? IN ('フルート', 'クラリネット', 'サックス'))
            OR (a.target_type = '金管' AND ? IN ('トランペット', 'ホルン', 'トロンボーン', 'ユーフォニアム', 'バスパート'))
        )
    """
    visibility_params = [member_id] if member["role"] == "顧問" else [member_id, member["part"], member["grade"], member["part"], member["part"]]
    rows = conn.execute(
        f"""
        SELECT
            a.id,
            a.target_type,
            a.target_part,
            a.target_grade,
            a.title,
            a.message,
            a.is_important,
            a.send_to_teacher,
            a.created_at,
            a.created_by,
            creator.name AS creator_name,
            CASE WHEN ar.member_id IS NULL THEN 0 ELSE 1 END AS is_read,
            CASE WHEN a.created_by = ? THEN 1 ELSE 0 END AS created_by_me,
            (SELECT COUNT(*) FROM announcement_reads reads WHERE reads.announcement_id = a.id) AS read_count
        FROM announcements a
        JOIN members creator ON a.created_by = creator.id
        LEFT JOIN announcement_reads ar
            ON a.id = ar.announcement_id
            AND ar.member_id = ?
        WHERE {visibility_sql}
        ORDER BY a.is_important DESC, a.created_at DESC
        """,
        [member_id, member_id] + visibility_params,
    ).fetchall()
    conn.close()

    items = [_announcement_to_item(row) for row in rows]
    if filter == "unread":
        items = [item for item in items if not item["isRead"] and not item["createdByMe"]]

    return {
        "filter": filter,
        "canPublish": _can_publish_announcements(member["role"]) and not bool(member["read_only"]),
        "canDelete": _can_delete_announcements(member["role"]) and not bool(member["read_only"]),
        "targetTypes": _announcement_target_types(member["role"]),
        "parts": PARTS,
        "announcements": items,
    }


@app.post("/api/announcements")
def create_announcement(payload: AnnouncementCreateRequest, member=Depends(get_current_member)):
    if not _can_publish_announcements(member["role"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This role cannot publish announcements",
        )

    target_type = payload.target_type
    if target_type not in _announcement_target_types(member["role"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid target type",
        )
    if target_type == "パート" and not payload.target_part:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="targetPart is required",
        )
    if target_type == "パート" and payload.target_part not in PARTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid target part",
        )
    if target_type == "学年" and payload.target_grade is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="targetGrade is required",
        )

    title = payload.title.strip()
    message = payload.message.strip()
    if not title or not message:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Title and message are required",
        )

    conn = get_connection()
    ensure_announcement_teacher_column(conn)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO announcements
        (target_type, target_part, target_grade, title, message, is_important, send_to_teacher, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            target_type,
            payload.target_part if target_type == "パート" else None,
            payload.target_grade if target_type == "学年" else None,
            title,
            message,
            1 if payload.is_important else 0,
            1 if payload.send_to_teacher and member["role"] != "顧問" else 0,
            member["id"],
        ),
    )
    announcement_id = int(cur.lastrowid)
    targets = _announcement_targets(conn, target_type, payload.target_part, payload.target_grade)
    if payload.send_to_teacher and member["role"] != "顧問":
        teacher_targets = conn.execute(
            "SELECT id FROM members WHERE status = '在籍' AND role = '顧問'"
        ).fetchall()
        target_ids = {int(target["id"]) for target in targets}
        targets = list(targets) + [target for target in teacher_targets if int(target["id"]) not in target_ids]
    for target in targets:
        cur.execute(
            """
            INSERT INTO notifications
            (target_member_id, notification_type, title, message)
            VALUES (?, 'announcement', ?, ?)
            """,
            (target["id"], title, message),
        )

    conn.commit()
    conn.close()

    return {
        "announcementId": announcement_id,
        "targetCount": len(targets),
    }


@app.get("/api/announcements/{announcement_id}/reads")
def announcement_reads(announcement_id: int, member=Depends(get_current_member)):
    conn = get_connection()
    announcement = conn.execute(
        "SELECT id, created_by FROM announcements WHERE id = ?",
        (announcement_id,),
    ).fetchone()
    if announcement is None:
        conn.close()
        raise HTTPException(status_code=404, detail="お知らせが見つかりません")
    if int(announcement["created_by"]) != int(member["id"]) and member["role"] != "管理者":
        conn.close()
        raise HTTPException(status_code=403, detail="既読者を見る権限がありません")
    rows = conn.execute(
        """
        SELECT m.id, m.name, m.part, m.grade, m.role, ar.read_at
        FROM announcement_reads ar
        JOIN members m ON m.id = ar.member_id
        WHERE ar.announcement_id = ? AND m.status = '在籍'
        ORDER BY CASE WHEN m.role = '顧問' THEN 1 ELSE 0 END, m.part, m.grade, m.name
        """,
        (announcement_id,),
    ).fetchall()
    conn.close()
    return {"announcementId": announcement_id, "readers": [{
        "id": int(row["id"]), "name": row["name"], "part": row["part"],
        "grade": row["grade"], "role": row["role"], "readAt": row["read_at"],
    } for row in rows]}


@app.post("/api/announcements/{announcement_id}/read")
def mark_announcement_read(announcement_id: int, member=Depends(get_current_member)):
    conn = get_connection()
    ensure_announcement_teacher_column(conn)
    announcement = conn.execute(
        "SELECT id, title, message, send_to_teacher, created_by FROM announcements WHERE id = ?",
        (announcement_id,),
    ).fetchone()
    if announcement is None:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Announcement not found",
        )
    if member["role"] == "顧問" and not bool(announcement["send_to_teacher"]) and int(announcement["created_by"]) != int(member["id"]):
        conn.close()
        raise HTTPException(status_code=403, detail="このお知らせを見る権限がありません")

    conn.execute(
        """
        INSERT OR IGNORE INTO announcement_reads
        (announcement_id, member_id)
        VALUES (?, ?)
        """,
        (announcement_id, member["id"]),
    )
    conn.execute(
        """
        UPDATE notifications
        SET is_read = 1
        WHERE target_member_id = ?
        AND notification_type = 'announcement'
        AND title = ?
        AND message = ?
        """,
        (member["id"], announcement["title"], announcement["message"]),
    )
    conn.commit()
    conn.close()

    return {"announcementId": announcement_id, "isRead": True}


@app.delete("/api/announcements/{announcement_id}")
def delete_announcement(announcement_id: int, member=Depends(get_current_member)):
    if not _can_delete_announcements(member["role"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This role cannot delete announcements",
        )

    conn = get_connection()
    announcement = conn.execute(
        "SELECT id, title, message FROM announcements WHERE id = ?",
        (announcement_id,),
    ).fetchone()
    if announcement is None:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Announcement not found",
        )

    conn.execute("DELETE FROM announcement_reads WHERE announcement_id = ?", (announcement_id,))
    conn.execute("DELETE FROM announcements WHERE id = ?", (announcement_id,))
    conn.execute(
        """
        DELETE FROM notifications
        WHERE notification_type = 'announcement'
        AND title = ?
        AND message = ?
        """,
        (announcement["title"], announcement["message"]),
    )
    conn.commit()
    conn.close()

    return {"announcementId": announcement_id, "deleted": True}


@app.get("/api/part-memos")
def part_memos(part: str | None = None, member=Depends(get_current_member)):
    available_parts = _manageable_parts(member)
    selected_part = part or available_parts[0]
    if selected_part not in available_parts:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This role cannot view that part",
        )

    conn = get_connection()
    rows = conn.execute(
        """
        SELECT
            pm.id,
            pm.part,
            pm.title,
            pm.memo,
            pm.created_by,
            pm.created_at,
            creator.name AS creator_name
        FROM part_memos pm
        JOIN members creator ON pm.created_by = creator.id
        WHERE pm.part = ?
        ORDER BY pm.created_at DESC, pm.id DESC
        """,
        (selected_part,),
    ).fetchall()
    conn.close()

    return {
        "part": selected_part,
        "availableParts": available_parts,
        "canWrite": _can_write_part_memo(member, selected_part),
        "memos": [_part_memo_to_item(row, member) for row in rows],
    }


@app.post("/api/part-memos")
def create_part_memo(payload: PartMemoCreateRequest, member=Depends(get_current_member)):
    part = payload.part or member["part"]
    if part not in _manageable_parts(member):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This role cannot write to that part",
        )
    if not _can_write_part_memo(member, part):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This role cannot write part memos",
        )

    title = payload.title.strip()
    memo = payload.memo.strip()
    if not title or not memo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Title and memo are required",
        )

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO part_memos
        (part, title, memo, created_by)
        VALUES (?, ?, ?, ?)
        """,
        (part, title, memo, member["id"]),
    )
    memo_id = int(cur.lastrowid)
    conn.commit()
    conn.close()

    return {"memoId": memo_id, "part": part}


@app.delete("/api/part-memos/{memo_id}")
def delete_part_memo(memo_id: int, member=Depends(get_current_member)):
    conn = get_connection()
    memo = conn.execute(
        """
        SELECT id, part, created_by
        FROM part_memos
        WHERE id = ?
        """,
        (memo_id,),
    ).fetchone()
    if memo is None:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Part memo not found",
        )
    if not _can_delete_part_memo(member, memo):
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This role cannot delete that memo",
        )

    conn.execute("DELETE FROM part_memos WHERE id = ?", (memo_id,))
    conn.commit()
    conn.close()

    return {"memoId": memo_id, "deleted": True}


@app.get("/api/approvals")
def approvals(member=Depends(get_current_member)):
    allowed = {"パートリーダー", "部長", "副部長", "管理者"}
    if member["role"] not in allowed:
        raise HTTPException(status_code=403, detail="This role cannot approve attendance")
    conn = get_connection()
    pending_rows = conn.execute(
        """
        SELECT a.id, a.status, a.reason, a.absence_type, a.created_at,
               m.id AS member_id, m.name, m.part, m.role, e.date, e.title, e.event_type, a.approval_status,
               approver.name AS approved_by_name, a.approved_at
        FROM attendance a
        JOIN members m ON m.id = a.member_id
        JOIN events e ON e.id = a.event_id
        LEFT JOIN members approver ON approver.id = a.approved_by
        WHERE a.approval_status = '未承認'
        ORDER BY e.date DESC, a.id DESC
        """,
    ).fetchall()
    history_rows = conn.execute(
        """
        SELECT a.id, a.status, a.reason, a.absence_type, a.created_at,
               m.id AS member_id, m.name, m.part, m.role, e.date, e.title, e.event_type, a.approval_status,
               approver.name AS approved_by_name, a.approved_at
        FROM attendance a
        JOIN members m ON m.id = a.member_id
        JOIN events e ON e.id = a.event_id
        LEFT JOIN members approver ON approver.id = a.approved_by
        WHERE a.approval_status IN ('承認済み', '拒否')
        ORDER BY a.approved_at DESC, e.date DESC, a.id DESC
        LIMIT 100
        """,
    ).fetchall()
    pending_rows = [row for row in pending_rows if _can_review_attendance(member, row)]
    history_rows = [row for row in history_rows if _can_review_attendance(member, row)][:30]
    show_leave_items = member["role"] == "管理者" or _leave_feature_enabled(conn)
    conn.close()
    if not show_leave_items:
        pending_rows = [row for row in pending_rows if not str(row["reason"] or "").startswith("休暇権利申請")]
        history_rows = [row for row in history_rows if not str(row["reason"] or "").startswith("休暇権利申請")]

    def approval_item(row):
        return {
            "id": row["id"],
            "status": row["status"],
            "reason": row["reason"],
            "absenceType": row["absence_type"],
            "memberName": row["name"],
            "part": row["part"],
            "memberRole": row["role"],
            "date": row["date"],
            "title": row["title"],
            "eventType": row["event_type"],
            "approvalStatus": row["approval_status"],
            "approvedBy": row["approved_by_name"],
            "approvedAt": row["approved_at"],
        }

    return {
        "items": [approval_item(row) for row in pending_rows],
        "approvedItems": [approval_item(row) for row in history_rows],
    }


@app.post("/api/approvals/{attendance_id}/approve")
def approve_attendance(attendance_id: int, payload: ApprovalRequest, member=Depends(get_current_member)):
    allowed = {"パートリーダー", "部長", "副部長", "管理者"}
    if member["role"] not in allowed:
        raise HTTPException(status_code=403, detail="This role cannot approve attendance")
    if payload.absence_type not in {"なし", "正当", "不当"}:
        raise HTTPException(status_code=400, detail="Invalid absence type")
    conn = get_connection()
    row = conn.execute(
        """
        SELECT a.id, a.absence_type, m.id AS member_id, m.part, m.role FROM attendance a
        JOIN members m ON m.id = a.member_id
        WHERE a.id = ? AND a.approval_status = '未承認'
        """,
        (attendance_id,),
    ).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Approval request not found")
    if not _can_review_attendance(member, row):
        conn.close()
        raise HTTPException(status_code=403, detail="この申請を承認する権限がありません")
    absence_type = payload.absence_type
    if row["absence_type"] == "休暇申請":
        _ensure_leave_schema(conn)
        leave_request = conn.execute(
            """
            SELECT lr.id, lr.credit_id, lc.credits_granted, lc.credits_used
            FROM leave_requests lr
            JOIN leave_credits lc ON lc.id = lr.credit_id
            WHERE lr.attendance_id = ? AND lr.status = '申請中'
            """,
            (attendance_id,),
        ).fetchone()
        if leave_request is None or int(leave_request["credits_granted"] or 0) <= int(leave_request["credits_used"] or 0):
            conn.close()
            raise HTTPException(status_code=400, detail="使用できる休暇権利が残っていません")
        absence_type = "正当"
        conn.execute(
            """
            UPDATE leave_credits SET credits_used = credits_used + 1
            WHERE id = ? AND credits_granted > credits_used
            """,
            (int(leave_request["credit_id"]),),
        )
        conn.execute(
            """
            UPDATE leave_requests SET status = '承認済み', reviewed_by = ?,
                reviewed_at = CURRENT_TIMESTAMP WHERE id = ?
            """,
            (member["id"], int(leave_request["id"])),
        )
    conn.execute(
        """
        UPDATE attendance SET approval_status = '承認済み', absence_type = ?,
            approved_by = ?, approved_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (absence_type, member["id"], attendance_id),
    )
    conn.commit()
    conn.close()
    return {"attendanceId": attendance_id, "approved": True}


@app.post("/api/approvals/{attendance_id}/reject")
def reject_attendance(attendance_id: int, member=Depends(get_current_member)):
    allowed = {"パートリーダー", "部長", "副部長", "管理者"}
    if member["role"] not in allowed:
        raise HTTPException(status_code=403, detail="This role cannot reject attendance")
    conn = get_connection()
    row = conn.execute(
        """
        SELECT a.id, a.absence_type, m.id AS member_id, m.part, m.role
        FROM attendance a
        JOIN members m ON m.id = a.member_id
        WHERE a.id = ? AND a.approval_status = '未承認'
        """,
        (attendance_id,),
    ).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Approval request not found")
    if not _can_review_attendance(member, row):
        conn.close()
        raise HTTPException(status_code=403, detail="この申請を拒否する権限がありません")
    if row["absence_type"] == "休暇申請":
        _ensure_leave_schema(conn)
        conn.execute(
            """
            UPDATE leave_requests SET status = '拒否', reviewed_by = ?,
                reviewed_at = CURRENT_TIMESTAMP
            WHERE attendance_id = ? AND status = '申請中'
            """,
            (member["id"], attendance_id),
        )
    conn.execute(
        """
        UPDATE attendance SET approval_status = '拒否', approved_by = ?,
            approved_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (member["id"], attendance_id),
    )
    conn.execute("DELETE FROM notifications WHERE related_attendance_id = ?", (attendance_id,))
    conn.commit()
    conn.close()
    return {"attendanceId": attendance_id, "rejected": True}


@app.delete("/api/approvals/{attendance_id}/attendance")
def cancel_approved_attendance(attendance_id: int, member=Depends(get_current_member)):
    allowed = {"パートリーダー", "部長", "副部長", "管理者"}
    if member["role"] not in allowed:
        raise HTTPException(status_code=403, detail="This role cannot cancel attendance")
    conn = get_connection()
    row = conn.execute(
        """
        SELECT a.id, a.status, a.approval_status, m.id AS member_id, m.part, m.role
        FROM attendance a
        JOIN members m ON m.id = a.member_id
        WHERE a.id = ?
        """,
        (attendance_id,),
    ).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Attendance not found")
    if row["status"] != "出席" or row["approval_status"] != "承認済み":
        conn.close()
        raise HTTPException(status_code=400, detail="Only approved attendance can be canceled")
    if not _can_review_attendance(member, row):
        conn.close()
        raise HTTPException(status_code=403, detail="この出席を取り消す権限がありません")
    conn.execute("DELETE FROM notifications WHERE related_attendance_id = ?", (attendance_id,))
    conn.execute("DELETE FROM attendance WHERE id = ?", (attendance_id,))
    conn.commit()
    conn.close()
    return {"attendanceId": attendance_id, "canceled": True}


@app.get("/api/operations/summary")
def operations_summary(member=Depends(get_current_member)):
    if not member_to_user(member)["permissions"]["canViewOperations"]:
        raise HTTPException(status_code=403, detail="This role cannot view operations")

    conn = get_connection()
    member_filter = ""
    member_params = []
    if member["role"] == "パートリーダー":
        member_filter = "AND part = ?"
        member_params.append(member["part"])
    member_count = conn.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM members
        WHERE status = '在籍'
        AND role NOT IN ('管理者', '顧問', '先生')
        {member_filter}
        """,
        member_params,
    ).fetchone()

    pending_approval_rows = conn.execute(
        """
        SELECT m.id, m.part, m.role
        FROM attendance a
        JOIN members m ON m.id = a.member_id
        WHERE a.approval_status = '未承認'
        """,
    ).fetchall()
    pending_approval_count = sum(
        1 for requester in pending_approval_rows if _can_review_attendance(member, requester)
    )

    row = conn.execute(
        "SELECT id, date, title FROM events WHERE date >= ? ORDER BY date, start_time LIMIT 1",
        (date.today().isoformat(),),
    ).fetchone()
    reminder_count = 0
    reminder_event = None
    if row is not None:
        reminder_event = dict(row)
        reminder_params = [row["id"]]
        reminder_part_filter = ""
        if member["role"] == "パートリーダー":
            reminder_part_filter = "AND m.part = ?"
            reminder_params.append(member["part"])
        reminder_row = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM members m
            LEFT JOIN attendance a ON a.member_id = m.id AND a.event_id = ?
            WHERE m.status = '在籍'
            AND m.role NOT IN ('管理者', '顧問', '先生')
            {reminder_part_filter}
            AND a.id IS NULL
            """,
            reminder_params,
        ).fetchone()
        reminder_count = int(reminder_row["count"] or 0)

    conn.close()
    return {
        "pendingApprovals": pending_approval_count,
        "unanswered": reminder_count,
        "memberCount": int(member_count["count"] or 0),
        "reminderEvent": reminder_event,
    }


@app.get("/api/operations/leadership-stats")
def operations_leadership_stats(member=Depends(get_current_member)):
    if member["role"] not in ("部長", "副部長", "管理者"):
        raise HTTPException(status_code=403, detail="この分析を見る権限がありません")

    today = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    start = today - timedelta(days=29)
    conn = get_connection()
    eligible_roles = "('一般部員', 'パートリーダー', '部長', '副部長')"

    totals = conn.execute(
        f"""
        SELECT COUNT(DISTINCT e.id) AS events,
               COUNT(*) AS opportunities,
               COUNT(a.id) AS responses,
               COUNT(CASE WHEN a.approval_status = '承認済み' AND a.status IN ('出席', '遅刻', '早退') THEN 1 END) AS attended,
               COUNT(CASE WHEN a.approval_status = '承認済み' AND a.status = '欠席' THEN 1 END) AS absent,
               COUNT(CASE WHEN a.approval_status = '未承認' THEN 1 END) AS pending
        FROM events e
        JOIN members m ON m.status = '在籍' AND m.role IN {eligible_roles}
          AND (m.join_date IS NULL OR m.join_date <= e.date)
          AND (m.leave_date IS NULL OR m.leave_date >= e.date)
        LEFT JOIN attendance a ON a.event_id = e.id AND a.member_id = m.id
        WHERE e.date BETWEEN ? AND ?
        """,
        (start.isoformat(), today.isoformat()),
    ).fetchone()
    part_rows = conn.execute(
        f"""
        SELECT m.part, COUNT(DISTINCT m.id) AS members,
               COUNT(*) AS opportunities,
               COUNT(a.id) AS responses,
               COUNT(CASE WHEN a.approval_status = '承認済み' AND a.status IN ('出席', '遅刻', '早退') THEN 1 END) AS attended
        FROM members m
        JOIN events e ON e.date BETWEEN ? AND ?
          AND (m.join_date IS NULL OR m.join_date <= e.date)
          AND (m.leave_date IS NULL OR m.leave_date >= e.date)
        LEFT JOIN attendance a ON a.member_id = m.id AND a.event_id = e.id
        WHERE m.status = '在籍' AND m.role IN {eligible_roles}
        GROUP BY m.part ORDER BY m.part
        """,
        (start.isoformat(), today.isoformat()),
    ).fetchall()
    attention_rows = conn.execute(
        f"""
        SELECT m.id, m.name, m.part, COUNT(DISTINCT e.id) AS opportunities, COUNT(a.id) AS responses
        FROM members m
        JOIN events e ON e.date BETWEEN ? AND ?
          AND (m.join_date IS NULL OR m.join_date <= e.date)
          AND (m.leave_date IS NULL OR m.leave_date >= e.date)
        LEFT JOIN attendance a ON a.member_id = m.id AND a.event_id = e.id
        WHERE m.status = '在籍' AND m.role IN {eligible_roles}
        GROUP BY m.id HAVING COUNT(DISTINCT e.id) > COUNT(a.id)
        ORDER BY (COUNT(DISTINCT e.id) - COUNT(a.id)) DESC, m.name LIMIT 8
        """,
        (start.isoformat(), today.isoformat()),
    ).fetchall()
    upcoming_rows = conn.execute(
        f"""
        SELECT e.id, e.date, e.start_time, COALESCE(e.title, e.event_type) AS title,
               COUNT(DISTINCT m.id) AS opportunities, COUNT(a.id) AS responses,
               COUNT(CASE WHEN a.approval_status = '承認済み' AND a.status = '欠席' THEN 1 END) AS absent,
               COUNT(CASE WHEN a.approval_status = '承認済み' AND a.status IN ('遅刻', '早退') THEN 1 END) AS late_early,
               COUNT(CASE WHEN a.approval_status = '未承認' THEN 1 END) AS pending
        FROM events e
        JOIN members m ON m.status = '在籍' AND m.role IN {eligible_roles}
          AND (m.join_date IS NULL OR m.join_date <= e.date)
          AND (m.leave_date IS NULL OR m.leave_date >= e.date)
        LEFT JOIN attendance a ON a.event_id = e.id AND a.member_id = m.id
        WHERE e.date >= ?
        GROUP BY e.id ORDER BY e.date, e.start_time LIMIT 6
        """,
        (today.isoformat(),),
    ).fetchall()
    conn.close()

    opportunities = int(totals["opportunities"] or 0)
    responses = int(totals["responses"] or 0)
    attended = int(totals["attended"] or 0)
    return {
        "startDate": start.isoformat(),
        "endDate": today.isoformat(),
        "summary": {
            "events": int(totals["events"] or 0),
            "responses": responses,
            "opportunities": opportunities,
            "responseRate": round(responses * 100 / opportunities, 1) if opportunities else None,
            "attendanceRate": round(attended * 100 / responses, 1) if responses else None,
            "absent": int(totals["absent"] or 0),
            "pending": int(totals["pending"] or 0),
        },
        "parts": [{
            "part": row["part"], "members": int(row["members"] or 0),
            "responses": int(row["responses"] or 0), "opportunities": int(row["opportunities"] or 0),
            "responseRate": round(int(row["responses"] or 0) * 100 / int(row["opportunities"] or 1), 1),
            "attendanceRate": round(int(row["attended"] or 0) * 100 / int(row["responses"] or 1), 1),
        } for row in part_rows],
        "memberAttention": [{
            "id": int(row["id"]), "name": row["name"], "part": row["part"],
            "unanswered": int(row["opportunities"] or 0) - int(row["responses"] or 0),
            "responseRate": round(int(row["responses"] or 0) * 100 / int(row["opportunities"] or 1), 1),
        } for row in attention_rows],
        "upcomingEvents": [{
            "id": int(row["id"]), "date": row["date"], "title": row["title"],
            "responses": int(row["responses"] or 0), "opportunities": int(row["opportunities"] or 0),
            "unanswered": max(int(row["opportunities"] or 0) - int(row["responses"] or 0), 0),
            "absent": int(row["absent"] or 0), "lateEarly": int(row["late_early"] or 0),
            "pending": int(row["pending"] or 0),
        } for row in upcoming_rows],
    }


def _system_started_on(conn, fallback_date):
    _ensure_system_lifecycle_table(conn)
    lifecycle = conn.execute(
        "SELECT phase_started_on FROM system_lifecycle WHERE id = 1"
    ).fetchone()
    if lifecycle and lifecycle["phase_started_on"]:
        return lifecycle["phase_started_on"]
    attendance_row = conn.execute(
        "SELECT MIN(date(datetime(created_at, '+9 hours'))) AS started_on FROM attendance"
    ).fetchone()
    if attendance_row and attendance_row["started_on"]:
        return attendance_row["started_on"]
    login_row = conn.execute(
        "SELECT MIN(date(datetime(last_login_at, '+9 hours'))) AS started_on FROM members WHERE last_login_at IS NOT NULL"
    ).fetchone()
    if login_row and login_row["started_on"]:
        return login_row["started_on"]
    event_row = conn.execute(
        "SELECT MIN(date(datetime(created_at, '+9 hours'))) AS started_on FROM events"
    ).fetchone()
    return event_row["started_on"] if event_row and event_row["started_on"] else fallback_date


@app.get("/api/admin/usage-stats")
def admin_usage_stats(start_date: str | None = None, end_date: str | None = None, member=Depends(get_current_member)):
    _require_admin(member)
    today = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    conn = get_connection()
    _ensure_login_events_table(conn)
    _ensure_birthday_messages_table(conn)
    system_started_on = _system_started_on(conn, today.isoformat())
    try:
        start = datetime.strptime(start_date or system_started_on, "%Y-%m-%d").date()
        end = datetime.strptime(end_date or today.isoformat(), "%Y-%m-%d").date()
    except ValueError as exc:
        conn.close()
        raise HTTPException(status_code=400, detail="日付を正しく入力してください") from exc
    if start > end:
        conn.close()
        raise HTTPException(status_code=400, detail="開始日は終了日以前にしてください")
    eligible_roles = "('一般部員', 'パートリーダー', '部長', '副部長')"
    response_row = conn.execute(
        f"""
        SELECT COUNT(a.id) AS count
        FROM attendance a
        JOIN events e ON e.id = a.event_id
        JOIN members m ON m.id = a.member_id
        WHERE e.date BETWEEN ? AND ?
          AND m.role IN {eligible_roles}
          AND (m.join_date IS NULL OR m.join_date <= e.date)
          AND (m.leave_date IS NULL OR m.leave_date >= e.date)
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchone()
    opportunity_row = conn.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM events e
        JOIN members m ON 1 = 1
        WHERE e.date BETWEEN ? AND ?
          AND m.role IN {eligible_roles}
          AND (m.join_date IS NULL OR m.join_date <= e.date)
          AND (m.leave_date IS NULL OR m.leave_date >= e.date)
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchone()
    event_row = conn.execute(
        "SELECT COUNT(*) AS count FROM events WHERE date BETWEEN ? AND ?",
        (start.isoformat(), end.isoformat()),
    ).fetchone()
    login_row = conn.execute(
        """
        SELECT COUNT(*) AS login_count,
               COUNT(DISTINCT member_id) AS active_user_count
        FROM login_events
        WHERE substr(logged_in_at, 1, 10) BETWEEN ? AND ?
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchone()
    current_member_row = conn.execute(
        f"SELECT COUNT(*) AS count FROM members WHERE status = '在籍' AND role IN {eligible_roles}"
    ).fetchone()
    workflow_row = conn.execute(
        """
        SELECT COUNT(*) AS request_count,
               COUNT(CASE WHEN a.approval_status IN ('承認済み', '拒否') THEN 1 END) AS processed_count,
               AVG(CASE
                   WHEN a.approved_at IS NOT NULL
                   THEN (julianday(a.approved_at) - julianday(a.created_at)) * 24
               END) AS average_approval_hours
        FROM attendance a
        JOIN events e ON e.id = a.event_id
        WHERE e.date BETWEEN ? AND ?
          AND a.status IN ('欠席', '遅刻', '早退')
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchone()
    announcement_row = conn.execute(
        "SELECT COUNT(*) AS count FROM announcements WHERE date(datetime(created_at, '+9 hours')) BETWEEN ? AND ?",
        (start.isoformat(), end.isoformat()),
    ).fetchone()
    todo_row = conn.execute(
        """
        SELECT COUNT(*) AS count,
               COUNT(CASE WHEN completed = 1 THEN 1 END) AS completed_count
        FROM todos
        WHERE date(datetime(created_at, '+9 hours')) BETWEEN ? AND ?
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchone()
    collaboration_row = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM part_memos WHERE date(datetime(created_at, '+9 hours')) BETWEEN ? AND ?) AS part_memos,
            (SELECT COUNT(*) FROM birthday_messages WHERE date(datetime(created_at, '+9 hours')) BETWEEN ? AND ?) AS birthday_messages,
            (SELECT COUNT(*) FROM birthday_messages WHERE reacted_at IS NOT NULL AND date(datetime(created_at, '+9 hours')) BETWEEN ? AND ?) AS birthday_reactions
        """,
        (
            start.isoformat(), end.isoformat(),
            start.isoformat(), end.isoformat(),
            start.isoformat(), end.isoformat(),
        ),
    ).fetchone()
    tracking_row = conn.execute(
        "SELECT MIN(substr(logged_in_at, 1, 10)) AS started_on FROM login_events"
    ).fetchone()
    lifecycle_row = conn.execute(
        "SELECT current_phase, trial_started_on, release_started_on FROM system_lifecycle WHERE id = 1"
    ).fetchone()
    attendance_breakdown_row = conn.execute(
        """
        SELECT
            COUNT(CASE WHEN a.approval_status = '承認済み' AND a.status = '出席' THEN 1 END) AS present,
            COUNT(CASE WHEN a.approval_status = '承認済み' AND a.status = '欠席' THEN 1 END) AS absent,
            COUNT(CASE WHEN a.approval_status = '承認済み' AND a.status = '遅刻' THEN 1 END) AS late,
            COUNT(CASE WHEN a.approval_status = '承認済み' AND a.status = '早退' THEN 1 END) AS early,
            COUNT(CASE WHEN a.approval_status = '未承認' THEN 1 END) AS pending,
            COUNT(CASE WHEN a.approval_status = '拒否' THEN 1 END) AS rejected
        FROM attendance a
        JOIN events e ON e.id = a.event_id
        JOIN members m ON m.id = a.member_id
        WHERE e.date BETWEEN ? AND ? AND m.role IN ('一般部員', 'パートリーダー', '部長', '副部長')
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchone()
    daily_rows = conn.execute(
        """
        SELECT e.date AS day,
               COUNT(DISTINCT e.id) AS events,
               COUNT(a.id) AS responses,
               COUNT(CASE WHEN a.approval_status = '承認済み' AND a.status IN ('出席', '遅刻', '早退') THEN 1 END) AS attended
        FROM events e
        LEFT JOIN attendance a ON a.event_id = e.id
        LEFT JOIN members m ON m.id = a.member_id
        WHERE e.date BETWEEN ? AND ?
          AND (m.id IS NULL OR m.role IN ('一般部員', 'パートリーダー', '部長', '副部長'))
        GROUP BY e.date ORDER BY e.date
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    daily_login_rows = conn.execute(
        """
        SELECT substr(logged_in_at, 1, 10) AS day, COUNT(*) AS logins, COUNT(DISTINCT member_id) AS users
        FROM login_events
        WHERE substr(logged_in_at, 1, 10) BETWEEN ? AND ?
        GROUP BY substr(logged_in_at, 1, 10) ORDER BY day
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    part_rows = conn.execute(
        """
        SELECT m.part, COUNT(DISTINCT m.id) AS members,
               COUNT(DISTINCT e.id) * COUNT(DISTINCT m.id) AS opportunities,
               COUNT(a.id) AS responses,
               COUNT(CASE WHEN a.approval_status = '承認済み' AND a.status IN ('出席', '遅刻', '早退') THEN 1 END) AS attended
        FROM members m
        JOIN events e ON e.date BETWEEN ? AND ?
          AND (m.join_date IS NULL OR m.join_date <= e.date)
          AND (m.leave_date IS NULL OR m.leave_date >= e.date)
        LEFT JOIN attendance a ON a.member_id = m.id AND a.event_id = e.id
        WHERE m.role IN ('一般部員', 'パートリーダー', '部長', '副部長')
        GROUP BY m.part ORDER BY m.part
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    event_performance_rows = conn.execute(
        """
        SELECT e.id, e.date, COALESCE(e.title, e.event_type) AS title,
               COUNT(DISTINCT m.id) AS opportunities, COUNT(a.id) AS responses,
               COUNT(CASE WHEN a.approval_status = '承認済み' AND a.status IN ('出席', '遅刻', '早退') THEN 1 END) AS attended
        FROM events e
        JOIN members m ON m.role IN ('一般部員', 'パートリーダー', '部長', '副部長')
          AND (m.join_date IS NULL OR m.join_date <= e.date)
          AND (m.leave_date IS NULL OR m.leave_date >= e.date)
        LEFT JOIN attendance a ON a.member_id = m.id AND a.event_id = e.id
        WHERE e.date BETWEEN ? AND ?
        GROUP BY e.id ORDER BY e.date DESC, e.start_time
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    member_attention_rows = conn.execute(
        """
        SELECT m.id, m.name, m.part, m.grade, COUNT(DISTINCT e.id) AS opportunities,
               COUNT(a.id) AS responses,
               COUNT(CASE WHEN a.approval_status = '承認済み' AND a.status IN ('出席', '遅刻', '早退') THEN 1 END) AS attended,
               COUNT(CASE WHEN a.approval_status = '承認済み' AND a.status = '出席' THEN 1 END) AS present,
               COUNT(CASE WHEN a.approval_status = '承認済み' AND a.status = '欠席' THEN 1 END) AS absent,
               COUNT(CASE WHEN a.approval_status = '承認済み' AND a.status = '遅刻' THEN 1 END) AS late,
               COUNT(CASE WHEN a.approval_status = '承認済み' AND a.status = '早退' THEN 1 END) AS early,
               COUNT(CASE WHEN a.approval_status = '未承認' THEN 1 END) AS pending
        FROM members m
        JOIN events e ON e.date BETWEEN ? AND ?
          AND (m.join_date IS NULL OR m.join_date <= e.date)
          AND (m.leave_date IS NULL OR m.leave_date >= e.date)
        LEFT JOIN attendance a ON a.member_id = m.id AND a.event_id = e.id
        WHERE m.status = '在籍' AND m.role IN ('一般部員', 'パートリーダー', '部長', '副部長')
        GROUP BY m.id
        HAVING COUNT(DISTINCT e.id) > 0
        ORDER BY (COUNT(a.id) * 1.0 / COUNT(DISTINCT e.id)) ASC, pending DESC, m.name
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    conn.close()

    responses = int(response_row["count"] or 0)
    opportunities = int(opportunity_row["count"] or 0)
    active_users = int(login_row["active_user_count"] or 0)
    current_members = int(current_member_row["count"] or 0)
    requests = int(workflow_row["request_count"] or 0)
    processed = int(workflow_row["processed_count"] or 0)
    average_approval_hours = workflow_row["average_approval_hours"]
    login_by_day = {row["day"]: {"logins": int(row["logins"] or 0), "users": int(row["users"] or 0)} for row in daily_login_rows}
    trends = [{
        "date": row["day"], "events": int(row["events"] or 0),
        "responses": int(row["responses"] or 0), "attended": int(row["attended"] or 0),
        **login_by_day.get(row["day"], {"logins": 0, "users": 0}),
    } for row in daily_rows]
    event_performance = [{
        "id": int(row["id"]), "date": row["date"], "title": row["title"],
        "responses": int(row["responses"] or 0), "opportunities": int(row["opportunities"] or 0),
        "responseRate": round(int(row["responses"] or 0) * 100 / int(row["opportunities"] or 1), 1),
        "attendanceRate": round(int(row["attended"] or 0) * 100 / int(row["opportunities"] or 1), 1),
    } for row in event_performance_rows]
    member_analytics = [{
        "id": int(row["id"]), "name": row["name"], "part": row["part"], "grade": int(row["grade"] or 0),
        "responses": int(row["responses"] or 0), "opportunities": int(row["opportunities"] or 0),
        "unanswered": max(int(row["opportunities"] or 0) - int(row["responses"] or 0), 0),
        "pending": int(row["pending"] or 0), "present": int(row["present"] or 0),
        "absent": int(row["absent"] or 0), "late": int(row["late"] or 0), "early": int(row["early"] or 0),
        "responseRate": round(int(row["responses"] or 0) * 100 / int(row["opportunities"] or 1), 1),
        "attendanceRate": round(int(row["attended"] or 0) * 100 / int(row["opportunities"] or 1), 1),
    } for row in member_attention_rows]
    return {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "systemStartedOn": system_started_on,
        "loginTrackingStartedOn": tracking_row["started_on"] if tracking_row else None,
        "lifecycle": {
            "phase": lifecycle_row["current_phase"] if lifecycle_row else None,
            "trialStartedOn": lifecycle_row["trial_started_on"] if lifecycle_row else None,
            "releaseStartedOn": lifecycle_row["release_started_on"] if lifecycle_row else None,
        },
        "daysInOperation": max((min(end, today) - datetime.strptime(system_started_on, "%Y-%m-%d").date()).days + 1, 0),
        "attendance": {
            "rate": round(responses * 100 / opportunities, 1) if opportunities else None,
            "responses": responses,
            "opportunities": opportunities,
            "events": int(event_row["count"] or 0),
            "breakdown": {key: int(attendance_breakdown_row[key] or 0) for key in ("present", "absent", "late", "early", "pending", "rejected")},
        },
        "usage": {
            "activeUsers": active_users,
            "logins": int(login_row["login_count"] or 0),
            "currentMembers": current_members,
            "activeUserRate": round(active_users * 100 / current_members, 1) if current_members else None,
        },
        "workflow": {
            "requests": requests,
            "processed": processed,
            "processingRate": round(processed * 100 / requests, 1) if requests else None,
            "averageApprovalHours": round(float(average_approval_hours), 1) if average_approval_hours is not None else None,
        },
        "engagement": {
            "announcements": int(announcement_row["count"] or 0),
            "todos": int(todo_row["count"] or 0),
            "completedTodos": int(todo_row["completed_count"] or 0),
            "partMemos": int(collaboration_row["part_memos"] or 0),
            "birthdayMessages": int(collaboration_row["birthday_messages"] or 0),
            "birthdayReactions": int(collaboration_row["birthday_reactions"] or 0),
        },
        "trends": trends[-31:],
        "parts": [{
            "part": row["part"], "members": int(row["members"] or 0),
            "responses": int(row["responses"] or 0), "opportunities": int(row["opportunities"] or 0),
            "responseRate": round(int(row["responses"] or 0) * 100 / int(row["opportunities"] or 1), 1),
            "attendanceRate": round(int(row["attended"] or 0) * 100 / int(row["opportunities"] or 1), 1),
        } for row in part_rows],
        "eventPerformance": sorted(event_performance, key=lambda item: (item["responseRate"], item["date"]))[:8],
        "memberAttention": member_analytics[:8],
        "memberAnalytics": sorted(member_analytics, key=lambda item: (item["part"], -item["grade"], item["name"])),
    }


def _require_admin(member):
    if member["role"] != "管理者":
        raise HTTPException(status_code=403, detail="Administrator only")


def _ensure_absence_report_shares_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS absence_report_shares (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_roles TEXT NOT NULL,
            part_filter TEXT,
            payload_json TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _absence_report_rows(conn, part=None, start_date=None, end_date=None):
    start_date = start_date or date.today().isoformat()
    params = [start_date]
    part_filter = ""
    end_filter = ""
    if part:
        part_filter = "AND m.part = ?"
        params.append(part)
    if end_date:
        end_filter = "AND e.date <= ?"
        params.append(end_date)
    rows = conn.execute(
        f"""
        SELECT a.id, e.date, e.title, e.event_type, m.name, m.part, m.grade,
               m.role, a.status, a.reason, a.absence_type, a.approval_status,
               approver.name AS approved_by_name, a.approved_at
        FROM attendance a
        JOIN members m ON m.id = a.member_id
        JOIN events e ON e.id = a.event_id
        LEFT JOIN members approver ON approver.id = a.approved_by
        WHERE e.date >= ?
          AND a.status IN ('欠席', '遅刻', '早退')
          {part_filter}
          {end_filter}
        ORDER BY e.date, e.start_time, m.part, m.grade, m.name
        """,
        params,
    ).fetchall()
    return [
        {
            "id": row["id"], "date": row["date"], "title": row["title"],
            "eventType": row["event_type"], "memberName": row["name"],
            "part": row["part"], "grade": row["grade"], "role": row["role"],
            "status": row["status"], "reason": row["reason"],
            "absenceType": row["absence_type"], "approvalStatus": row["approval_status"],
            "approvedBy": row["approved_by_name"], "approvedAt": row["approved_at"],
        }
        for row in rows
    ]


@app.get("/api/admin/absence-report")
def admin_absence_report(member=Depends(get_current_member)):
    _require_admin(member)
    conn = get_connection()
    rows = _absence_report_rows(conn)
    conn.close()
    return {"items": rows, "parts": PARTS, "roles": ROLES}


@app.post("/api/admin/absence-report/shares")
def share_admin_absence_report(payload: AbsenceReportShareRequest, member=Depends(get_current_member)):
    _require_admin(member)
    target_roles = list(dict.fromkeys(payload.target_roles))
    if not target_roles or any(role not in ROLES for role in target_roles):
        raise HTTPException(status_code=400, detail="共有先の役職を1つ以上選択してください")
    if payload.part and payload.part not in PARTS:
        raise HTTPException(status_code=400, detail="パートが正しくありません")
    start_date = payload.start_date or date.today().isoformat()
    end_date = payload.end_date
    try:
        datetime.strptime(start_date, "%Y-%m-%d")
        if end_date:
            datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="公開期間の日付が正しくありません") from exc
    if end_date and end_date < start_date:
        raise HTTPException(status_code=400, detail="公開期間が正しくありません")
    conn = get_connection()
    _ensure_absence_report_shares_table(conn)
    rows = _absence_report_rows(conn, payload.part, start_date, end_date)
    snapshot = {"rows": rows, "startDate": start_date, "endDate": end_date}
    conn.execute(
        """
        INSERT INTO absence_report_shares
        (target_roles, part_filter, payload_json, created_by)
        VALUES (?, ?, ?, ?)
        """,
        (json.dumps(target_roles, ensure_ascii=False), payload.part, json.dumps(snapshot, ensure_ascii=False), int(member["id"])),
    )
    placeholders = ",".join("?" for _ in target_roles)
    target_members = conn.execute(
        f"SELECT id FROM members WHERE status = '在籍' AND role IN ({placeholders})",
        target_roles,
    ).fetchall()
    for target in target_members:
        conn.execute(
            """
            INSERT INTO notifications
            (target_member_id, notification_type, title, message)
            VALUES (?, 'absence_report_shared', '欠席・遅刻情報が共有されました', 'お知らせ画面から共有表を確認してください。')
            """,
            (int(target["id"]),),
        )
    conn.commit()
    conn.close()
    return {"shared": True, "targetCount": len(target_members), "itemCount": len(rows)}


@app.get("/api/absence-report/shares")
def visible_absence_report_shares(member=Depends(get_current_member)):
    conn = get_connection()
    _ensure_absence_report_shares_table(conn)
    show_leave_items = member["role"] == "管理者" or _leave_feature_enabled(conn)
    rows = conn.execute(
        """
        SELECT s.id, s.target_roles, s.part_filter, s.payload_json, s.created_at,
               m.name AS created_by_name
        FROM absence_report_shares s
        JOIN members m ON m.id = s.created_by
        ORDER BY s.created_at DESC, s.id DESC
        LIMIT 20
        """
    ).fetchall()
    conn.close()
    items = []
    for row in rows:
        target_roles = json.loads(row["target_roles"] or "[]")
        if member["role"] != "管理者" and member["role"] not in target_roles:
            continue
        payload = json.loads(row["payload_json"] or "[]")
        if isinstance(payload, list):
            report_rows, start_date, end_date = payload, None, None
        else:
            report_rows = payload.get("rows", [])
            start_date, end_date = payload.get("startDate"), payload.get("endDate")
        if not show_leave_items:
            report_rows = [item for item in report_rows if not str(item.get("reason") or "").startswith("休暇権利申請")]
        items.append({
            "id": row["id"], "targetRoles": target_roles,
            "part": row["part_filter"], "rows": report_rows,
            "startDate": start_date, "endDate": end_date,
            "createdAt": row["created_at"], "createdBy": row["created_by_name"],
            "canDelete": member["role"] == "管理者",
        })
    return {"items": items}


@app.delete("/api/admin/absence-report/shares/{share_id}")
def delete_admin_absence_report_share(share_id: int, member=Depends(get_current_member)):
    _require_admin(member)
    conn = get_connection()
    _ensure_absence_report_shares_table(conn)
    existing = conn.execute(
        "SELECT id FROM absence_report_shares WHERE id = ?",
        (share_id,),
    ).fetchone()
    if existing is None:
        conn.close()
        raise HTTPException(status_code=404, detail="共有済みリストが見つかりません")
    conn.execute("DELETE FROM absence_report_shares WHERE id = ?", (share_id,))
    conn.commit()
    conn.close()
    return {"deleted": True, "shareId": share_id}


@app.get("/api/admin/leave-feature")
def admin_leave_feature(member=Depends(get_current_member)):
    _require_admin(member)
    conn = get_connection()
    enabled = _leave_feature_enabled(conn)
    started_on = _leave_feature_started_on(conn)
    conn.close()
    return {"enabled": enabled, "startedOn": started_on.isoformat() if started_on else None}


@app.get("/api/admin/maintenance")
def admin_maintenance(member=Depends(get_current_member)):
    _require_admin(member)
    conn = get_connection()
    enabled = maintenance_mode_enabled(conn)
    conn.close()
    return {"enabled": enabled}


@app.patch("/api/admin/maintenance")
def update_admin_maintenance(payload: FeatureToggleRequest, member=Depends(get_current_member)):
    _require_admin(member)
    conn = get_connection()
    ensure_maintenance_flag(conn)
    conn.execute(
        """
        UPDATE feature_flags SET enabled = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP
        WHERE feature_key = 'maintenance_mode'
        """,
        (1 if payload.enabled else 0, member["id"]),
    )
    conn.commit()
    conn.close()
    return {
        "enabled": payload.enabled,
        "message": "メンテナンスモードを開始しました。" if payload.enabled else "メンテナンスモードを終了しました。",
    }


@app.patch("/api/admin/leave-feature")
def update_admin_leave_feature(payload: FeatureToggleRequest, member=Depends(get_current_member)):
    _require_admin(member)
    conn = get_connection()
    _ensure_leave_schema(conn)
    current_enabled = _leave_feature_enabled(conn)
    conn.execute(
        """
        UPDATE feature_flags SET enabled = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP
        WHERE feature_key = 'leave_credit'
        """,
        (1 if payload.enabled else 0, int(member["id"])),
    )
    if payload.enabled and not current_enabled:
        conn.execute(
            """
            INSERT INTO feature_metadata (feature_key, value, updated_at)
            VALUES ('leave_credit_started_on', ?, CURRENT_TIMESTAMP)
            ON CONFLICT(feature_key) DO UPDATE SET
                value = excluded.value, updated_at = CURRENT_TIMESTAMP
            """,
            (date.today().isoformat(),),
        )
    conn.commit()
    conn.close()
    return {
        "enabled": payload.enabled,
        "startedOn": date.today().isoformat() if payload.enabled else None,
        "message": "休暇権利機能を開始しました。" if payload.enabled else "休暇権利機能を停止しました。",
    }


def _registration_request_item(row):
    return {
        "id": row["id"], "studentId": row["student_id"], "name": row["name"],
        "grade": row["grade"], "birthday": row["birthday"], "part": row["part"],
        "email": row["email"], "phone": row["phone"], "joinDate": row["join_date"],
        "status": row["status"], "reviewNote": row["review_note"],
        "createdAt": row["created_at"], "reviewedAt": row["reviewed_at"],
    }


@app.get("/api/member-registration-requests")
def member_registration_requests(member=Depends(get_current_member)):
    _require_admin(member)
    conn = get_connection()
    ensure_registration_requests_table(conn)
    rows = conn.execute(
        "SELECT * FROM member_registration_requests ORDER BY CASE status WHEN '申請中' THEN 0 ELSE 1 END, created_at DESC, id DESC"
    ).fetchall()
    conn.close()
    return {"items": [_registration_request_item(row) for row in rows]}


def _review_member_registration(request_id, payload, member, approved):
    _require_admin(member)
    if payload.grade < 1 or payload.grade > 6:
        raise HTTPException(status_code=400, detail="学年は1〜6で入力してください")
    if payload.part not in PARTS:
        raise HTTPException(status_code=400, detail="パートが正しくありません")
    conn = get_connection()
    ensure_registration_requests_table(conn)
    try:
        request = conn.execute(
            "SELECT * FROM member_registration_requests WHERE id = ? AND status = '申請中'",
            (request_id,),
        ).fetchone()
        if request is None:
            raise HTTPException(status_code=404, detail="申請がないか、すでに処理済みです")
        if approved:
            if conn.execute("SELECT 1 FROM members WHERE student_id = ?", (request["student_id"],)).fetchone():
                raise HTTPException(status_code=409, detail="同じ学籍番号の部員がすでに登録されています")
            conn.execute(
                """
                INSERT INTO members
                (student_id, name, grade, birthday, part, role, status, email, phone, pin_hash, pin_salt, join_date)
                VALUES (?, ?, ?, ?, ?, '一般部員', '在籍', ?, ?, ?, ?, ?)
                """,
                (request["student_id"], request["name"], payload.grade, request["birthday"],
                 payload.part, request["email"], request["phone"], request["pin_hash"], request["pin_salt"], request["join_date"]),
            )
        new_status = "承認" if approved else "拒否"
        conn.execute(
            """
            UPDATE member_registration_requests
            SET status = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP,
                review_note = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?
            """,
            (new_status, member["id"], (payload.note or "").strip() or None, request_id),
        )
        conn.commit()
        return {"requestId": request_id, "status": new_status, "memberCreated": approved}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=409, detail="申請を処理できませんでした") from exc
    finally:
        conn.close()


@app.post("/api/member-registration-requests/{request_id}/approve")
def approve_member_registration(request_id: int, payload: MemberRegistrationReviewRequest, member=Depends(get_current_member)):
    return _review_member_registration(request_id, payload, member, True)


@app.post("/api/member-registration-requests/{request_id}/reject")
def reject_member_registration(request_id: int, payload: MemberRegistrationReviewRequest, member=Depends(get_current_member)):
    return _review_member_registration(request_id, payload, member, False)


@app.get("/api/members")
def members(member=Depends(get_current_member)):
    can_manage = member["role"] == "管理者"
    can_view_full = member["role"] in {"管理者", "部長", "副部長"}
    conn = get_connection()
    ensure_members_optional_columns(conn)
    rows = conn.execute(
        """
        SELECT id, student_id, name, grade, birthday, part, role, status,
               email, phone, hometown, band_years, mbti, class_late_weekdays, club_duty,
               pin_hash, last_login_at, join_date, leave_date
        FROM members
        WHERE status = '在籍' AND role != '管理者'
        """
    ).fetchall()
    part_order = {part: index for index, part in enumerate(PARTS)}
    rows = sorted(
        rows,
        key=lambda row: (
            1 if row["role"] == "顧問" else 0,
            part_order.get(row["part"], len(PARTS)),
            0 if row["role"] == "パートリーダー" else 1,
            int(row["grade"] or 0),
            row["name"],
        ),
    )
    member_ids = [int(row["id"]) for row in rows]
    summary_by_member = {member_id: {"records": 0, "attended": 0} for member_id in member_ids}
    plans_by_member = {member_id: [] for member_id in member_ids}
    today = date.today().isoformat()
    if member_ids:
        placeholders = ",".join("?" for _ in member_ids)
        summary_rows = conn.execute(
            f"""
            SELECT
                m.id AS member_id,
                COUNT(CASE WHEN e.date <= ? AND a.approval_status = '承認済み' THEN 1 END) AS records,
                COUNT(CASE WHEN e.date <= ? AND a.approval_status = '承認済み' AND a.status IN ('出席', '遅刻', '早退') THEN 1 END) AS attended
            FROM members m
            LEFT JOIN attendance a ON a.member_id = m.id
            LEFT JOIN events e ON e.id = a.event_id
            WHERE m.id IN ({placeholders})
            GROUP BY m.id
            """,
            [today, today] + member_ids,
        ).fetchall()
        for summary in summary_rows:
            summary_by_member[int(summary["member_id"])] = {
                "records": int(summary["records"] or 0),
                "attended": int(summary["attended"] or 0),
            }
        plan_rows = conn.execute(
            f"""
            SELECT
                a.member_id AS member_id,
                a.status AS status,
                a.reason AS reason,
                a.approval_status AS approval_status,
                a.absence_type AS absence_type,
                e.date AS date,
                e.title AS title,
                e.event_type AS event_type
            FROM attendance a
            JOIN events e ON e.id = a.event_id
            WHERE a.member_id IN ({placeholders})
              AND e.date >= ?
              AND a.status IN ('欠席', '遅刻', '早退')
            ORDER BY e.date, e.start_time, e.id
            """,
            member_ids + [today],
        ).fetchall()
        for plan in plan_rows:
            plans_by_member.setdefault(int(plan["member_id"]), []).append({
                "date": plan["date"],
                "title": plan["title"],
                "eventType": plan["event_type"],
                "status": plan["status"],
                "reason": plan["reason"],
                "approvalStatus": plan["approval_status"],
                "absenceType": plan["absence_type"],
            })
    conn.close()
    items = []
    for row in rows:
        item = dict(row)
        if not can_view_full:
            item = {
                "id": row["id"],
                "name": row["name"],
                "grade": row["grade"],
                "birthday": row["birthday"],
                "part": row["part"],
                "role": row["role"],
                "status": row["status"],
                "hometown": row["hometown"],
                "band_years": row["band_years"],
                "mbti": row["mbti"],
                "duty": row["club_duty"],
                "classLateWeekdays": _weekdays_from_text(row["class_late_weekdays"]),
            }
        else:
            item["classLateWeekdays"] = _weekdays_from_text(row["class_late_weekdays"])
            item["duty"] = row["club_duty"]
        if can_manage:
            item["lastLoginAt"] = row["last_login_at"]
            item["pinStatus"] = "設定済み" if row["pin_hash"] else "未設定"
        summary = summary_by_member.get(int(row["id"]), {"records": 0, "attended": 0})
        records = summary["records"]
        item["attendanceRate"] = round(summary["attended"] * 100 / records, 1) if records else None
        item["attendanceRecords"] = records
        item["knownPlans"] = plans_by_member.get(int(row["id"]), [])
        items.append(item)
    return {
        "members": items,
        "parts": PARTS,
        "roles": ROLES,
        "canManage": can_manage,
        "canViewFull": can_view_full,
    }


def _member_values(payload: MemberUpsertRequest):
    if not payload.student_id.strip() or not payload.name.strip():
        raise HTTPException(status_code=400, detail="学籍番号と名前は必須です")
    if payload.role not in ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    part = ADMIN_PART if payload.role in {"管理者", "顧問"} else payload.part
    if payload.role not in {"管理者", "顧問"} and part not in PARTS:
        raise HTTPException(status_code=400, detail="Invalid part")
    if payload.band_years is not None and payload.band_years < 0:
        raise HTTPException(status_code=400, detail="吹奏楽年数は0以上で入力してください")
    class_late_weekdays = _weekdays_to_text(payload.class_late_weekdays)
    duty = (payload.duty or "").strip() or None
    return (
        payload.student_id.strip(), payload.name.strip(),
        0 if payload.role in {"管理者", "顧問"} else payload.grade,
        None if payload.role == "顧問" else payload.birthday,
        part, payload.role, payload.status,
        payload.email,
        payload.phone,
        None if payload.role == "顧問" else (payload.hometown or "").strip() or None,
        None if payload.role == "顧問" else payload.band_years,
        None if payload.role == "顧問" else (payload.mbti or "").strip().upper() or None,
        None if payload.role == "顧問" else class_late_weekdays,
        None if payload.role == "顧問" else duty,
        payload.join_date,
        payload.leave_date,
    )


@app.post("/api/members")
def create_member(payload: MemberUpsertRequest, member=Depends(get_current_member)):
    _require_admin(member)
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO members
            (student_id, name, grade, birthday, part, role, status, email, phone, hometown, band_years, mbti, class_late_weekdays, club_duty, join_date, leave_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            _member_values(payload),
        )
        conn.commit()
    except Exception as exc:
        conn.close()
        raise HTTPException(status_code=409, detail="同じ学籍番号が登録されています") from exc
    member_id = int(cur.lastrowid)
    conn.close()
    return {"memberId": member_id, "created": True}


@app.patch("/api/members/{member_id}")
def update_member(member_id: int, payload: MemberUpsertRequest, member=Depends(get_current_member)):
    _require_admin(member)
    conn = get_connection()
    if conn.execute("SELECT id FROM members WHERE id = ?", (member_id,)).fetchone() is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Member not found")
    values = _member_values(payload)
    conn.execute(
        """
        UPDATE members SET student_id=?, name=?, grade=?, birthday=?, part=?, role=?,
            status=?, email=?, phone=?, hometown=?, band_years=?, mbti=?, class_late_weekdays=?, club_duty=?,
            join_date=?, leave_date=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        values + (member_id,),
    )
    conn.commit()
    conn.close()
    return {"memberId": member_id, "updated": True}


@app.post("/api/admin/members/{member_id}/reset-pin")
def reset_member_pin(member_id: int, member=Depends(get_current_member)):
    _require_admin(member)
    if member_id == int(member["id"]):
        raise HTTPException(status_code=400, detail="自分の暗証番号はこの画面からリセットできません")
    conn = get_connection()
    ensure_members_optional_columns(conn)
    target = conn.execute("SELECT id, name FROM members WHERE id = ? AND status = '在籍'", (member_id,)).fetchone()
    if target is None:
        conn.close()
        raise HTTPException(status_code=404, detail="部員が見つかりません")
    conn.execute(
        "UPDATE members SET pin_hash = NULL, pin_salt = NULL, pin_failed_attempts = 0, pin_locked_until = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (member_id,),
    )
    conn.commit()
    conn.close()
    return {
        "memberId": member_id,
        "reset": True,
        "message": f"{target['name']}さんの暗証番号をリセットしました。次回は学籍番号と初期暗証番号0で設定できます。",
    }


@app.delete("/api/members/{member_id}")
def delete_member(member_id: int, member=Depends(get_current_member)):
    _require_admin(member)
    if member_id == int(member["id"]):
        raise HTTPException(status_code=400, detail="自分自身は削除できません")
    conn = get_connection()
    target = conn.execute(
        "SELECT id, name, role FROM members WHERE id = ?",
        (member_id,),
    ).fetchone()
    if target is None:
        conn.close()
        raise HTTPException(status_code=404, detail="部員が見つかりません")
    if target["role"] == "管理者":
        conn.close()
        raise HTTPException(status_code=400, detail="管理者アカウントは削除できません")

    _ensure_leave_schema(conn)
    conn.execute(
        "DELETE FROM notifications WHERE related_attendance_id IN (SELECT id FROM attendance WHERE member_id = ?)",
        (member_id,),
    )
    conn.execute("DELETE FROM leave_requests WHERE member_id = ?", (member_id,))
    conn.execute("UPDATE leave_requests SET reviewed_by = NULL WHERE reviewed_by = ?", (member_id,))
    conn.execute("DELETE FROM attendance WHERE member_id = ?", (member_id,))
    conn.execute("UPDATE attendance SET approved_by = NULL WHERE approved_by = ?", (member_id,))
    conn.execute("DELETE FROM leave_credits WHERE member_id = ?", (member_id,))
    conn.execute("DELETE FROM notifications WHERE target_member_id = ?", (member_id,))
    conn.execute("DELETE FROM announcement_reads WHERE member_id = ?", (member_id,))
    conn.execute("DELETE FROM daily_task_checks WHERE member_id = ?", (member_id,))
    _ensure_birthday_messages_table(conn)
    conn.execute("DELETE FROM birthday_messages WHERE sender_id = ? OR recipient_id = ?", (member_id, member_id))
    conn.execute("UPDATE member_registration_requests SET reviewed_by = NULL WHERE reviewed_by = ?", (member_id,))
    conn.execute("UPDATE todos SET completed_by = NULL WHERE completed_by = ?", (member_id,))
    conn.execute("UPDATE backup_history SET created_by = NULL WHERE created_by = ?", (member_id,))

    replacement_id = int(member["id"])
    for table in (
        "events",
        "external_system_links",
        "announcements",
        "absence_report_shares",
        "part_memos",
        "todos",
        "publications",
    ):
        conn.execute(f"UPDATE {table} SET created_by = ? WHERE created_by = ?", (replacement_id, member_id))
    conn.execute("UPDATE feature_flags SET updated_by = ? WHERE updated_by = ?", (replacement_id, member_id))
    conn.execute("DELETE FROM members WHERE id = ?", (member_id,))
    conn.commit()
    conn.close()
    return {"memberId": member_id, "memberName": target["name"], "deleted": True}


@app.post("/api/admin/advance-year")
def advance_school_year(member=Depends(get_current_member)):
    _require_admin(member)
    conn = get_connection()
    graduating_rows = conn.execute(
        "SELECT id FROM members WHERE grade >= 4 AND role NOT IN ('管理者', '顧問')"
    ).fetchall()
    graduating_ids = [int(row["id"]) for row in graduating_rows]

    if graduating_ids:
        placeholders = ",".join("?" for _ in graduating_ids)
        attendance_rows = conn.execute(
            f"SELECT id FROM attendance WHERE member_id IN ({placeholders})",
            graduating_ids,
        ).fetchall()
        attendance_ids = [int(row["id"]) for row in attendance_rows]
        if attendance_ids:
            attendance_placeholders = ",".join("?" for _ in attendance_ids)
            conn.execute(
                f"DELETE FROM notifications WHERE related_attendance_id IN ({attendance_placeholders})",
                attendance_ids,
            )
            conn.execute(
                f"DELETE FROM leave_requests WHERE attendance_id IN ({attendance_placeholders})",
                attendance_ids,
            )
        conn.execute(f"DELETE FROM attendance WHERE member_id IN ({placeholders})", graduating_ids)
        conn.execute(f"UPDATE attendance SET approved_by = NULL WHERE approved_by IN ({placeholders})", graduating_ids)
        conn.execute(f"DELETE FROM notifications WHERE target_member_id IN ({placeholders})", graduating_ids)
        conn.execute(f"DELETE FROM announcement_reads WHERE member_id IN ({placeholders})", graduating_ids)
        conn.execute(f"DELETE FROM daily_task_checks WHERE member_id IN ({placeholders})", graduating_ids)
        conn.execute(f"DELETE FROM login_events WHERE member_id IN ({placeholders})", graduating_ids)
        conn.execute(f"DELETE FROM leave_requests WHERE member_id IN ({placeholders})", graduating_ids)
        conn.execute(f"DELETE FROM leave_credits WHERE member_id IN ({placeholders})", graduating_ids)
        conn.execute(f"DELETE FROM birthday_messages WHERE sender_id IN ({placeholders}) OR recipient_id IN ({placeholders})", graduating_ids + graduating_ids)
        conn.execute(f"DELETE FROM todos WHERE created_by IN ({placeholders})", graduating_ids)
        conn.execute(f"DELETE FROM part_memos WHERE created_by IN ({placeholders})", graduating_ids)
        conn.execute(f"DELETE FROM publications WHERE created_by IN ({placeholders})", graduating_ids)
        conn.execute(f"UPDATE member_registration_requests SET reviewed_by = NULL WHERE reviewed_by IN ({placeholders})", graduating_ids)
        conn.execute(f"DELETE FROM members WHERE id IN ({placeholders})", graduating_ids)

    promoted = conn.execute(
        """
        UPDATE members
        SET grade = grade + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE grade BETWEEN 1 AND 3
        AND role NOT IN ('管理者', '顧問')
        """
    ).rowcount
    conn.commit()
    conn.close()
    return {
        "deletedGraduates": len(graduating_ids),
        "promotedMembers": int(promoted or 0),
    }


@app.post("/api/admin/reset-attendance-data")
def reset_attendance_data(member=Depends(get_current_member)):
    _require_admin(member)
    conn = get_connection()
    attendance_count = conn.execute("SELECT COUNT(*) AS count FROM attendance").fetchone()
    notification_count = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM notifications
        WHERE related_attendance_id IS NOT NULL
           OR notification_type = 'approval_request'
        """
    ).fetchone()
    conn.execute(
        """
        DELETE FROM notifications
        WHERE related_attendance_id IS NOT NULL
           OR notification_type = 'approval_request'
        """
    )
    conn.execute("DELETE FROM attendance")
    conn.commit()
    conn.close()
    return {
        "reset": True,
        "deletedAttendance": int(attendance_count["count"] or 0),
        "deletedNotifications": int(notification_count["count"] or 0),
    }


@app.post("/api/admin/start-operation-phase/{phase}")
def start_operation_phase(phase: str, member=Depends(get_current_member)):
    _require_admin(member)
    if phase not in {"trial", "release"}:
        raise HTTPException(status_code=400, detail="開始区分が正しくありません")

    today = datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
    conn = get_connection()
    _ensure_login_events_table(conn)
    _ensure_system_lifecycle_table(conn)
    _ensure_leave_schema(conn)
    _ensure_birthday_messages_table(conn)
    _ensure_absence_report_shares_table(conn)
    _ensure_publications_schema(conn)
    ensure_todo_notification_columns(conn)

    reset_tables = [
        "attendance", "notifications", "announcements", "announcement_reads",
        "todos", "part_memos", "absence_report_shares", "daily_task_checks",
        "leave_requests", "leave_credits", "birthday_messages", "publications",
        "login_events",
    ]
    deleted = {}
    for table in reset_tables:
        row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
        deleted[table] = int(row["count"] or 0)

    for table in (
        "announcement_reads", "notifications", "leave_requests", "leave_credits",
        "attendance", "announcements", "todos", "part_memos",
        "absence_report_shares", "daily_task_checks", "birthday_messages",
        "publications", "login_events",
    ):
        conn.execute(f"DELETE FROM {table}")

    if phase == "trial":
        conn.execute(
            """
            UPDATE system_lifecycle
            SET current_phase = 'trial', phase_started_on = ?, trial_started_on = ?,
                release_started_on = NULL, updated_by = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """,
            (today, today, member["id"]),
        )
    else:
        conn.execute(
            """
            UPDATE system_lifecycle
            SET current_phase = 'release', phase_started_on = ?, release_started_on = ?,
                updated_by = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """,
            (today, today, member["id"]),
        )
    conn.commit()
    conn.close()
    label = "試行期間" if phase == "trial" else "本リリース"
    return {
        "phase": phase,
        "startedOn": today,
        "deleted": deleted,
        "message": f"運用データをリセットし、{label}を開始しました。",
    }


def _month_bounds(month: str | None):
    selected = month or date.today().strftime("%Y-%m")
    try:
        year, month_number = (int(value) for value in selected.split("-"))
        start = date(year, month_number, 1)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="対象月が正しくありません") from exc
    end = date(year, month_number, calendar.monthrange(year, month_number)[1])
    today = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    if start <= today <= end:
        end = today
    return selected, start.isoformat(), end.isoformat()


def _detailed_statistics_data(conn, month: str):
    selected, start_date, end_date = _month_bounds(month)
    rows = conn.execute(
        """
        SELECT e.id event_id, e.date, e.title, e.event_type, m.id member_id, m.part,
          a.status, a.reason, a.approval_status, a.absence_type
        FROM events e
        CROSS JOIN members m
        LEFT JOIN attendance a ON a.event_id=e.id AND a.member_id=m.id
        WHERE e.date BETWEEN ? AND ? AND m.status='在籍'
          AND m.role IN ('一般部員','パートリーダー','部長','副部長')
        ORDER BY e.date, e.start_time, e.id, m.part, m.name
        """,
        (start_date, end_date),
    ).fetchall()

    def fresh_counts():
        return {"scheduled": 0, "answered": 0, "approved": 0, "pending": 0, "unanswered": 0,
                "attended": 0, "present": 0, "late": 0, "early": 0, "absent": 0,
                "justified": 0, "unjustified": 0}

    def add(counts, row):
        counts["scheduled"] += 1
        if row["status"] is None:
            counts["unanswered"] += 1
            return
        counts["answered"] += 1
        if row["approval_status"] != "承認済み":
            counts["pending"] += 1
            return
        counts["approved"] += 1
        status_value = row["status"]
        if status_value in {"出席", "遅刻", "早退"}:
            counts["attended"] += 1
        if status_value == "出席": counts["present"] += 1
        elif status_value == "遅刻": counts["late"] += 1
        elif status_value == "早退": counts["early"] += 1
        elif status_value == "欠席": counts["absent"] += 1
        if row["absence_type"] == "正当": counts["justified"] += 1
        elif row["absence_type"] == "不当": counts["unjustified"] += 1

    def finish(label, counts):
        approved_answers = counts["attended"] + counts["absent"]
        return {
            "label": label, **counts,
            "rate": round(counts["attended"] * 100 / approved_answers, 1) if approved_answers else None,
            "answerRate": round(counts["answered"] * 100 / counts["scheduled"], 1) if counts["scheduled"] else None,
        }

    summary_counts = fresh_counts()
    parts, days, event_types = {}, {}, {}
    for row in rows:
        add(summary_counts, row)
        for bucket, key in ((parts, row["part"]), (days, row["date"]), (event_types, row["event_type"])):
            if key not in bucket: bucket[key] = fresh_counts()
            add(bucket[key], row)
    event_count = len({row["event_id"] for row in rows})
    member_count = len({row["member_id"] for row in rows})
    summary = finish("全体", summary_counts)
    summary.update({"records": summary["approved"], "eventCount": event_count, "memberCount": member_count})
    return {
        "month": selected, "throughDate": end_date, "summary": summary,
        "parts": [finish(label, counts) for label, counts in sorted(parts.items())],
        "daily": [finish(label, counts) for label, counts in sorted(days.items())],
        "eventTypes": [finish(label, counts) for label, counts in sorted(event_types.items())],
    }


@app.get("/api/statistics")
def statistics(month: str | None = None, member=Depends(get_current_member)):
    if member["role"] not in {"部長", "副部長", "管理者"}:
        raise HTTPException(status_code=403, detail="This role cannot view statistics")
    conn = get_connection()
    data = _detailed_statistics_data(conn, month or date.today().strftime("%Y-%m"))
    conn.close()
    return data


def _admin_member_detail(conn, member_id: int, month: str):
    selected, start_date, end_date = _month_bounds(month)
    rows = conn.execute(
        """
        SELECT e.id event_id, e.date, e.title, e.event_type, e.start_time, e.end_time,
          a.status, a.reason, a.approval_status, a.absence_type, a.updated_at
        FROM events e LEFT JOIN attendance a
          ON a.event_id=e.id AND a.member_id=?
        WHERE e.date BETWEEN ? AND ?
        ORDER BY e.date, e.start_time, e.id
        """,
        (member_id, start_date, end_date),
    ).fetchall()
    details = []
    counts = {"scheduled": len(rows), "answered": 0, "approved": 0, "pending": 0, "unanswered": 0,
              "attended": 0, "present": 0, "late": 0, "early": 0, "absent": 0,
              "justified": 0, "unjustified": 0}
    event_types = {}
    for row in rows:
        status_value = row["status"] or "未回答"
        if row["status"] is None:
            counts["unanswered"] += 1
        else:
            counts["answered"] += 1
            if row["approval_status"] == "承認済み":
                counts["approved"] += 1
                if status_value in {"出席", "遅刻", "早退"}: counts["attended"] += 1
                if status_value == "出席": counts["present"] += 1
                elif status_value == "遅刻": counts["late"] += 1
                elif status_value == "早退": counts["early"] += 1
                elif status_value == "欠席": counts["absent"] += 1
                if row["absence_type"] == "正当": counts["justified"] += 1
                elif row["absence_type"] == "不当": counts["unjustified"] += 1
            else:
                counts["pending"] += 1
        type_counts = event_types.setdefault(row["event_type"], {"scheduled": 0, "attended": 0, "absent": 0, "unanswered": 0})
        type_counts["scheduled"] += 1
        if row["status"] is None: type_counts["unanswered"] += 1
        elif row["approval_status"] == "承認済み" and status_value in {"出席", "遅刻", "早退"}: type_counts["attended"] += 1
        elif row["approval_status"] == "承認済み" and status_value == "欠席": type_counts["absent"] += 1
        details.append({
            "eventId": row["event_id"], "date": row["date"], "title": row["title"],
            "eventType": row["event_type"], "startTime": row["start_time"], "endTime": row["end_time"],
            "status": status_value, "reason": row["reason"],
            "approvalStatus": row["approval_status"] or "未回答", "absenceType": row["absence_type"] or "なし",
        })
    approved_answers = counts["attended"] + counts["absent"]
    stats = {
        "period": selected, "throughDate": end_date, **counts,
        "rate": round(counts["attended"] * 100 / approved_answers, 1) if approved_answers else None,
        "answerRate": round(counts["answered"] * 100 / counts["scheduled"], 1) if counts["scheduled"] else None,
        "monthly": [],
    }
    return {"stats": stats, "details": details, "eventTypes": [{"label": key, **value} for key, value in sorted(event_types.items())]}


def _admin_member_attendance_items(conn, month, part=None):
    part_filter = "AND part = ?" if part else ""
    params = [part] if part else []
    rows = conn.execute(
        f"""
        SELECT id, name, part, grade, role
        FROM members
        WHERE status = '在籍'
          AND role IN ('一般部員', 'パートリーダー', '部長', '副部長')
          {part_filter}
        ORDER BY part, grade, name
        """,
        params,
    ).fetchall()
    items = []
    for row in rows:
        detail = _admin_member_detail(conn, int(row["id"]), month)
        items.append({
            "id": int(row["id"]),
            "name": row["name"],
            "part": row["part"],
            "grade": row["grade"],
            "role": row["role"],
            **detail,
        })
    return items


@app.get("/api/admin/member-attendance")
def admin_member_attendance(month: str | None = None, member=Depends(get_current_member)):
    _require_admin(member)
    selected, _, through_date = _month_bounds(month)
    conn = get_connection()
    items = _admin_member_attendance_items(conn, selected)
    conn.close()
    return {"month": selected, "throughDate": through_date, "items": items}


@app.get("/api/operations/member-attendance")
def operations_member_attendance(month: str | None = None, member=Depends(get_current_member)):
    if member["role"] not in {"パートリーダー", "部長", "副部長", "管理者"}:
        raise HTTPException(status_code=403, detail="出席情報を見る権限がありません")
    selected, _, through_date = _month_bounds(month)
    visible_part = member["part"] if member["role"] == "パートリーダー" else None
    conn = get_connection()
    items = _admin_member_attendance_items(conn, selected, visible_part)
    conn.close()
    return {
        "month": selected,
        "throughDate": through_date,
        "scope": visible_part or "全部員",
        "items": items,
    }


@app.get("/api/attendance/reminders")
def attendance_reminders(event_id: int | None = None, member=Depends(get_current_member)):
    if member["role"] not in {"パートリーダー", "部長", "副部長", "管理者"}:
        raise HTTPException(status_code=403, detail="This role cannot view reminders")
    conn = get_connection()
    selected_event = event_id
    if selected_event is None:
        row = conn.execute(
            "SELECT id FROM events WHERE date >= ? ORDER BY date, start_time LIMIT 1",
            (date.today().isoformat(),),
        ).fetchone()
        selected_event = int(row["id"]) if row else None
    if selected_event is None:
        conn.close()
        return {"event": None, "members": []}
    event = conn.execute("SELECT id, date, title FROM events WHERE id=?", (selected_event,)).fetchone()
    params = [selected_event]
    part_filter = ""
    if member["role"] == "パートリーダー":
        part_filter = "AND m.part = ?"
        params.append(member["part"])
    rows = conn.execute(
        f"""
        SELECT m.id, m.name, m.part, m.grade FROM members m
        LEFT JOIN attendance a ON a.member_id=m.id AND a.event_id=?
        WHERE m.status='在籍'
        AND m.role NOT IN ('管理者', '顧問', '先生')
        {part_filter}
        AND a.id IS NULL
        ORDER BY m.part, m.grade, m.name
        """,
        params,
    ).fetchall()
    conn.close()
    return {"event": dict(event) if event else None, "members": [dict(row) for row in rows]}


@app.get("/api/todos")
def get_todos(member=Depends(get_current_member)):
    conn = get_connection()
    if member["role"] == "管理者":
        rows = conn.execute(
            """
            SELECT t.id, t.scope, t.part, t.category, t.title, t.detail, t.completed,
                   t.created_by AS created_by_id, creator.name created_by
            FROM todos t JOIN members creator ON creator.id=t.created_by
            WHERE t.scope != 'パート' OR t.part = ? OR t.completed = 1
            ORDER BY t.completed, t.created_at DESC
            """,
            (member["part"],),
        ).fetchall()
    else:
        visible_scopes = ["全体", *_instrument_group_scopes(member["part"])]
        placeholders = ",".join("?" for _ in visible_scopes)
        rows = conn.execute(
            f"""
        SELECT t.id, t.scope, t.part, t.category, t.title, t.detail, t.completed,
               t.created_by AS created_by_id, creator.name created_by
        FROM todos t JOIN members creator ON creator.id=t.created_by
            WHERE t.scope IN ({placeholders}) OR (t.scope = 'パート' AND t.part = ?)
            ORDER BY t.completed, t.created_at DESC
            """,
            visible_scopes + [member["part"]],
        ).fetchall()
    conn.close()
    items = []
    for row in rows:
        item = dict(row)
        item["canDelete"] = member["role"] == "管理者" or int(row["created_by_id"]) == int(member["id"])
        item.pop("created_by_id", None)
        items.append(item)
    return {"items": items}


@app.post("/api/todos")
def create_todo(payload: TodoCreateRequest, member=Depends(get_current_member)):
    if not payload.title.strip() or not payload.category.strip():
        raise HTTPException(status_code=400, detail="タイトルとカテゴリは必須です")
    if payload.scope not in {"全体", "パート", "金管", "木管"}:
        raise HTTPException(status_code=400, detail="公開範囲が正しくありません")
    if payload.scope == "パート" and not payload.part:
        raise HTTPException(status_code=400, detail="パートを選択してください")
    if payload.scope == "パート" and payload.part not in PARTS:
        raise HTTPException(status_code=400, detail="パートが正しくありません")
    if payload.scope == "パート" and payload.part != member["part"]:
        raise HTTPException(status_code=403, detail="パートTo Doは自分のパートにだけ送信できます")
    conn = get_connection()
    ensure_todo_notification_columns(conn)
    cur = conn.execute(
        "INSERT INTO todos (scope, part, category, title, detail, created_by) VALUES (?, ?, ?, ?, ?, ?)",
        (payload.scope, payload.part, payload.category.strip(), payload.title.strip(), payload.detail, member["id"]),
    )
    todo_id = int(cur.lastrowid)
    announcement_title = "新しいTo Doが追加されました"
    announcement_message = f"【{payload.category.strip()}】{payload.title.strip()}"
    announcement = conn.execute(
        """
        INSERT INTO announcements
        (target_type, target_part, target_grade, title, message, is_important, created_by, todo_id)
        VALUES (?, ?, NULL, ?, ?, 0, ?, ?)
        """,
        (
            payload.scope,
            payload.part if payload.scope == "パート" else None,
            announcement_title,
            announcement_message,
            member["id"],
            todo_id,
        ),
    )
    announcement_id = int(announcement.lastrowid)
    targets = _announcement_targets(
        conn,
        payload.scope,
        payload.part if payload.scope == "パート" else None,
    )
    for target in targets:
        conn.execute(
            """
            INSERT INTO notifications
            (target_member_id, notification_type, title, message, related_todo_id)
            VALUES (?, 'announcement', ?, ?, ?)
            """,
            (target["id"], announcement_title, announcement_message, todo_id),
        )
    conn.commit()
    conn.close()
    return {"todoId": todo_id, "announcementId": announcement_id, "targetCount": len(targets), "created": True}


@app.post("/api/todos/{todo_id}/toggle")
def toggle_todo(todo_id: int, member=Depends(get_current_member)):
    conn = get_connection()
    row = conn.execute("SELECT completed FROM todos WHERE id=?", (todo_id,)).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="To Do not found")
    completed = 0 if row["completed"] else 1
    conn.execute(
        """
        UPDATE todos SET completed=?, completed_by=?, completed_at=CASE WHEN ?=1 THEN CURRENT_TIMESTAMP ELSE NULL END,
          updated_at=CURRENT_TIMESTAMP WHERE id=?
        """,
        (completed, member["id"], completed, todo_id),
    )
    conn.commit()
    conn.close()
    return {"todoId": todo_id, "completed": bool(completed)}


@app.delete("/api/todos/{todo_id}")
def delete_todo(todo_id: int, member=Depends(get_current_member)):
    conn = get_connection()
    ensure_todo_notification_columns(conn)
    row = conn.execute(
        "SELECT id, title, category, completed, created_by FROM todos WHERE id = ?",
        (todo_id,),
    ).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="To Doが見つかりません")
    if not bool(row["completed"]):
        conn.close()
        raise HTTPException(status_code=400, detail="完了済みのTo Doだけ削除できます")
    if member["role"] != "管理者" and int(row["created_by"]) != int(member["id"]):
        conn.close()
        raise HTTPException(status_code=403, detail="このTo Doを削除できるのは管理者または投稿者だけです")
    linked_announcements = conn.execute(
        "SELECT id FROM announcements WHERE todo_id = ?",
        (todo_id,),
    ).fetchall()
    if not linked_announcements:
        legacy = conn.execute(
            """
            SELECT id FROM announcements
            WHERE todo_id IS NULL AND created_by = ?
              AND title = '新しいTo Doが追加されました' AND message = ?
            ORDER BY id DESC LIMIT 1
            """,
            (row["created_by"], f"【{row['category']}】{row['title']}"),
        ).fetchone()
        linked_announcements = [legacy] if legacy else []
    for announcement in linked_announcements:
        conn.execute("DELETE FROM announcement_reads WHERE announcement_id = ?", (announcement["id"],))
        conn.execute("DELETE FROM announcements WHERE id = ?", (announcement["id"],))
    conn.execute("DELETE FROM notifications WHERE related_todo_id = ?", (todo_id,))
    conn.execute(
        """
        DELETE FROM notifications
        WHERE related_todo_id IS NULL AND notification_type = 'announcement'
          AND title = '新しいTo Doが追加されました' AND message = ?
        """,
        (f"【{row['category']}】{row['title']}",),
    )
    conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
    conn.commit()
    conn.close()
    return {"todoId": todo_id, "title": row["title"], "deleted": True}


def _ranking_data(conn, month: str):
    rows = conn.execute(
        """
        SELECT m.id, m.name, m.part,
          COALESCE(stats.records, 0) records,
          COALESCE(stats.attended, 0) attended
        FROM members m
        LEFT JOIN (
          SELECT a.member_id,
            COUNT(a.id) records,
            COUNT(CASE WHEN a.status IN ('出席','遅刻','早退') THEN 1 END) attended
          FROM attendance a
          JOIN events e ON e.id = a.event_id
          WHERE a.approval_status = '承認済み' AND substr(e.date,1,7) = ?
          GROUP BY a.member_id
        ) stats ON stats.member_id = m.id
        WHERE m.status='在籍' AND m.role IN ('一般部員','パートリーダー','部長','副部長')
        ORDER BY CASE WHEN COALESCE(stats.records, 0) = 0 THEN 1 ELSE 0 END,
          stats.attended * 1.0 / stats.records DESC, stats.attended DESC, m.name
        """,
        (month,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "part": row["part"],
            "records": int(row["records"] or 0),
            "attended": int(row["attended"] or 0),
            "rate": round(int(row["attended"] or 0) * 100 / int(row["records"]), 1)
            if row["records"] else None,
        }
        for row in rows
    ]


def _part_ranking_data(individual_items):
    parts = {}
    for item in individual_items:
        current = parts.setdefault(item["part"], {"part": item["part"], "records": 0, "attended": 0, "memberCount": 0})
        current["records"] += item["records"]
        current["attended"] += item["attended"]
        current["memberCount"] += 1
    items = []
    for item in parts.values():
        items.append({
            **item,
            "rate": round(item["attended"] * 100 / item["records"], 1) if item["records"] else None,
        })
    return sorted(items, key=lambda item: (item["rate"] is None, -(item["rate"] or 0), -item["attended"], item["part"]))


@app.get("/api/rankings")
def ranking_data(month: str | None = None, member=Depends(get_current_member)):
    selected_month = month or date.today().strftime("%Y-%m")
    conn = get_connection()
    individual_items = _ranking_data(conn, selected_month)
    part_items = _part_ranking_data(individual_items)
    conn.close()
    return {"month": selected_month, "items": individual_items[:10], "individualItems": individual_items, "partItems": part_items}


def _publication_item(row):
    return {
        "id": row["id"],
        "kind": row["kind"],
        "title": row["title"],
        "period": row["period"],
        "payload": json.loads(row["payload_json"]),
        "isPublished": bool(row["is_published"]),
        "audienceType": row["audience_type"] or "all",
        "audienceValue": row["audience_value"],
        "createdAt": row["created_at"],
    }


def _ensure_publications_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS publications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            period TEXT,
            payload_json TEXT NOT NULL,
            is_published INTEGER DEFAULT 1,
            audience_type TEXT DEFAULT 'all',
            audience_value TEXT,
            created_by INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(created_by) REFERENCES members(id)
        )
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(publications)").fetchall()}
    if "audience_type" not in columns:
        conn.execute("ALTER TABLE publications ADD COLUMN audience_type TEXT DEFAULT 'all'")
    if "audience_value" not in columns:
        conn.execute("ALTER TABLE publications ADD COLUMN audience_value TEXT")
    conn.commit()


def _publication_visible_to_member(row, member):
    if not bool(row["is_published"]):
        return False
    audience_type = row["audience_type"] or "all"
    audience_value = str(row["audience_value"] or "")
    if audience_type == "all":
        return True
    if audience_type == "role":
        return member["role"] == audience_value
    if audience_type == "part":
        return member["part"] == audience_value
    if audience_type == "member":
        return str(member["id"]) == audience_value
    return False


def _publication_audience(payload, conn):
    audience_type = payload.audience_type or "all"
    audience_value = (payload.audience_value or "").strip() or None
    if audience_type not in {"all", "role", "part", "member"}:
        raise HTTPException(status_code=400, detail="公開範囲が正しくありません")
    if audience_type == "role" and audience_value not in ROLES:
        raise HTTPException(status_code=400, detail="公開先の役職が正しくありません")
    if audience_type == "part" and audience_value not in PARTS:
        raise HTTPException(status_code=400, detail="公開先のパートが正しくありません")
    if audience_type == "member":
        try:
            audience_member_id = int(audience_value or "")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="公開先の部員が正しくありません") from exc
        if conn.execute("SELECT 1 FROM members WHERE id = ? AND status = '在籍'", (audience_member_id,)).fetchone() is None:
            raise HTTPException(status_code=400, detail="公開先の部員が見つかりません")
        audience_value = str(audience_member_id)
    if audience_type == "all":
        audience_value = None
    return audience_type, audience_value


@app.get("/api/publications")
def publications(member=Depends(get_current_member)):
    conn = get_connection()
    _ensure_publications_schema(conn)
    rows = conn.execute("SELECT * FROM publications ORDER BY created_at DESC, id DESC").fetchall()
    if member["role"] != "管理者":
        rows = [row for row in rows if _publication_visible_to_member(row, member)]
    conn.close()
    return {"items": [_publication_item(row) for row in rows], "canManage": member["role"] == "管理者"}


@app.post("/api/publications")
def create_publication(payload: PublicationCreateRequest, member=Depends(get_current_member)):
    _require_admin(member)
    granular_kinds = {
        "overall_rate", "answer_rate", "attendance_breakdown", "part_rates",
        "daily_rates", "event_type_rates", "ranking", "member_attendance",
        "member_event_types",
    }
    if payload.kind not in granular_kinds:
        raise HTTPException(status_code=400, detail="Invalid publication kind")
    period = payload.period or date.today().strftime("%Y-%m")
    conn = get_connection()
    _ensure_publications_schema(conn)
    audience_type, audience_value = _publication_audience(payload, conn)
    statistics_content = _detailed_statistics_data(conn, period)
    if payload.kind == "ranking":
        content = {"month": period, "items": _ranking_data(conn, period)}
    elif payload.kind in {"member_attendance", "member_event_types"}:
        if payload.member_id is None:
            conn.close()
            raise HTTPException(status_code=400, detail="公開する部員を選択してください")
        target = conn.execute(
            """
            SELECT id, name, part, grade, role FROM members
            WHERE id = ? AND status = '在籍'
              AND role IN ('一般部員', 'パートリーダー', '部長', '副部長')
            """,
            (payload.member_id,),
        ).fetchone()
        if target is None:
            conn.close()
            raise HTTPException(status_code=404, detail="対象の部員が見つかりません")
        detail = _admin_member_detail(conn, int(target["id"]), period)
        content = {
            "member": {
                "id": int(target["id"]), "name": target["name"], "part": target["part"],
                "grade": target["grade"], "role": target["role"],
            },
            # Reasons and event-by-event answers are intentionally kept inside the admin screen.
            "stats": detail["stats"],
            "eventTypes": detail["eventTypes"],
        }
    else:
        summary = statistics_content["summary"]
        if payload.kind == "overall_rate":
            content = {"month": period, "label": "全体出席率", "value": summary["rate"], "unit": "%", "note": f"承認済み・対象予定 {summary['eventCount']}件"}
        elif payload.kind == "answer_rate":
            content = {"month": period, "label": "回答率", "value": summary["answerRate"], "unit": "%", "note": f"回答 {summary['answered']} / 対象 {summary['scheduled']}"}
        elif payload.kind == "attendance_breakdown":
            content = {"month": period, "summary": {key: summary[key] for key in ("present", "late", "early", "absent", "justified", "unjustified", "unanswered", "pending")}}
        elif payload.kind == "part_rates":
            content = {"month": period, "items": statistics_content["parts"]}
        elif payload.kind == "daily_rates":
            content = {"month": period, "items": statistics_content["daily"]}
        else:
            content = {"month": period, "items": statistics_content["eventTypes"]}
    cur = conn.execute(
        """
        INSERT INTO publications
        (kind, title, period, payload_json, is_published, audience_type, audience_value, created_by)
        VALUES (?, ?, ?, ?, 1, ?, ?, ?)
        """,
        (
            payload.kind, payload.title.strip(), period, json.dumps(content, ensure_ascii=False),
            audience_type, audience_value, member["id"],
        ),
    )
    conn.commit()
    publication_id = int(cur.lastrowid)
    conn.close()
    return {"publicationId": publication_id, "created": True}


@app.patch("/api/publications/{publication_id}/visibility")
def toggle_publication(publication_id: int, member=Depends(get_current_member)):
    _require_admin(member)
    conn = get_connection()
    _ensure_publications_schema(conn)
    row = conn.execute("SELECT is_published FROM publications WHERE id=?", (publication_id,)).fetchone()
    if row is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Publication not found")
    visible = 0 if row["is_published"] else 1
    conn.execute(
        "UPDATE publications SET is_published=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (visible, publication_id),
    )
    conn.commit()
    conn.close()
    return {"publicationId": publication_id, "isPublished": bool(visible)}


@app.delete("/api/publications/{publication_id}")
def delete_publication(publication_id: int, member=Depends(get_current_member)):
    _require_admin(member)
    conn = get_connection()
    _ensure_publications_schema(conn)
    deleted = conn.execute("DELETE FROM publications WHERE id=?", (publication_id,)).rowcount
    conn.commit()
    conn.close()
    if not deleted:
        raise HTTPException(status_code=404, detail="Publication not found")
    return {"publicationId": publication_id, "deleted": True}
