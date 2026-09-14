import calendar
from datetime import date

import pandas as pd

from database import get_connection


def ensure_leave_schema():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS leave_credits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            grant_month TEXT NOT NULL,
            eligible_month TEXT NOT NULL,
            expires_on TEXT NOT NULL,
            credits_granted INTEGER DEFAULT 1,
            credits_used INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(member_id, grant_month),
            FOREIGN KEY(member_id) REFERENCES members(id)
        )
    """)

    cur.execute("""
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
            FOREIGN KEY(member_id) REFERENCES members(id),
            FOREIGN KEY(event_id) REFERENCES events(id),
            FOREIGN KEY(attendance_id) REFERENCES attendance(id),
            FOREIGN KEY(credit_id) REFERENCES leave_credits(id),
            UNIQUE(member_id, event_id)
        )
    """)

    conn.commit()
    conn.close()


def month_bounds(target):
    first_day = target.replace(day=1)
    last_day = target.replace(day=calendar.monthrange(target.year, target.month)[1])
    return first_day, last_day


def previous_month(target):
    year = target.year
    month = target.month - 1
    if month == 0:
        year -= 1
        month = 12
    return date(year, month, 1)


def grant_monthly_leave_credits(today=None):
    ensure_leave_schema()

    today = today or date.today()
    eligible_month_date = previous_month(today)
    eligible_start, eligible_end = month_bounds(eligible_month_date)
    grant_start, grant_end = month_bounds(today)

    eligible_month = eligible_start.strftime("%Y-%m")
    grant_month = grant_start.strftime("%Y-%m")

    conn = get_connection()

    normal_events = pd.read_sql_query("""
        SELECT id
        FROM events
        WHERE event_type = '通常練習'
        AND date BETWEEN ? AND ?
    """, conn, params=(eligible_start.isoformat(), eligible_end.isoformat()))

    if normal_events.empty:
        conn.close()
        return 0

    event_ids = set(normal_events["id"].tolist())

    members = pd.read_sql_query("""
        SELECT id
        FROM members
        WHERE status = '在籍'
        AND role != '管理者'
    """, conn)

    granted = 0
    cur = conn.cursor()

    for _, member in members.iterrows():
        attendance = pd.read_sql_query("""
            SELECT event_id
            FROM attendance
            WHERE member_id = ?
            AND status = '出席'
            AND approval_status = '承認済み'
        """, conn, params=(int(member["id"]),))

        attended_ids = set(attendance["event_id"].tolist())

        if event_ids.issubset(attended_ids):
            cur.execute("""
                INSERT OR IGNORE INTO leave_credits
                (member_id, grant_month, eligible_month, expires_on, credits_granted, credits_used)
                VALUES (?, ?, ?, ?, 1, 0)
            """, (
                int(member["id"]),
                grant_month,
                eligible_month,
                grant_end.isoformat(),
            ))
            if cur.rowcount:
                granted += 1

    conn.commit()
    conn.close()
    return granted


def get_leave_credit_summary(member_id):
    ensure_leave_schema()
    grant_monthly_leave_credits()

    conn = get_connection()
    credits = pd.read_sql_query("""
        SELECT *
        FROM leave_credits
        WHERE member_id = ?
        ORDER BY grant_month DESC
    """, conn, params=(member_id,))
    conn.close()

    if credits.empty:
        return credits, 0

    today = date.today().isoformat()
    active = credits[
        (credits["expires_on"] >= today)
        & ((credits["credits_granted"] - credits["credits_used"]) > 0)
    ]
    available_count = int((active["credits_granted"] - active["credits_used"]).sum()) if not active.empty else 0
    return credits, available_count


def get_available_credit(member_id, event_date):
    ensure_leave_schema()
    grant_monthly_leave_credits()

    conn = get_connection()
    credit = conn.execute("""
        SELECT *
        FROM leave_credits
        WHERE member_id = ?
        AND expires_on >= ?
        AND credits_granted > credits_used
        ORDER BY expires_on, grant_month
        LIMIT 1
    """, (member_id, event_date)).fetchone()
    conn.close()
    return credit


def request_leave(member_id, event_id, credit_id, reason):
    conn = get_connection()
    cur = conn.cursor()

    existing = cur.execute("""
        SELECT id
        FROM attendance
        WHERE member_id = ? AND event_id = ?
    """, (member_id, event_id)).fetchone()

    request_reason = f"休暇権利申請：{reason}" if reason else "休暇権利申請"

    if existing:
        attendance_id = existing["id"]
        cur.execute("""
            UPDATE attendance
            SET status = '欠席',
                reason = ?,
                approval_status = '未承認',
                absence_type = '休暇申請',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (request_reason, attendance_id))
    else:
        cur.execute("""
            INSERT INTO attendance
            (member_id, event_id, status, reason, approval_status, absence_type)
            VALUES (?, ?, '欠席', ?, '未承認', '休暇申請')
        """, (member_id, event_id, request_reason))
        attendance_id = cur.lastrowid

    cur.execute("""
        INSERT INTO leave_requests
        (member_id, event_id, attendance_id, credit_id, status)
        VALUES (?, ?, ?, ?, '申請中')
        ON CONFLICT(member_id, event_id)
        DO UPDATE SET
            attendance_id = excluded.attendance_id,
            credit_id = excluded.credit_id,
            status = '申請中',
            requested_at = CURRENT_TIMESTAMP,
            reviewed_by = NULL,
            reviewed_at = NULL
    """, (member_id, event_id, attendance_id, credit_id))

    conn.commit()
    conn.close()
    return attendance_id


def approve_leave_request(attendance_id, reviewer_id):
    conn = get_connection()
    cur = conn.cursor()

    request = cur.execute("""
        SELECT id, credit_id
        FROM leave_requests
        WHERE attendance_id = ?
        AND status = '申請中'
    """, (attendance_id,)).fetchone()

    if request is None:
        conn.close()
        return False

    cur.execute("""
        UPDATE attendance
        SET approval_status = '承認済み',
            absence_type = '正当',
            approved_by = ?,
            approved_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (reviewer_id, attendance_id))

    cur.execute("""
        UPDATE leave_requests
        SET status = '承認済み',
            reviewed_by = ?,
            reviewed_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (reviewer_id, request["id"]))

    cur.execute("""
        UPDATE leave_credits
        SET credits_used = credits_used + 1
        WHERE id = ?
        AND credits_granted > credits_used
    """, (request["credit_id"],))

    conn.commit()
    conn.close()
    return True
