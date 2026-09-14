import pandas as pd

from database import get_connection
from utils.notification_utils import create_notification


def get_today_unanswered_members(today, part=None):
    conditions = ["m.status = '在籍'"]
    params = [today]

    if part:
        conditions.append("m.part = ?")
        params.append(part)

    conn = get_connection()
    data = pd.read_sql_query(f"""
        SELECT
            e.id AS event_id,
            e.date,
            e.start_time,
            e.end_time,
            e.event_type,
            e.title AS event_title,
            m.id AS member_id,
            m.name,
            m.grade,
            m.part,
            m.role
        FROM events e
        CROSS JOIN members m
        LEFT JOIN attendance a
            ON a.event_id = e.id
            AND a.member_id = m.id
        WHERE e.date = ?
            AND a.id IS NULL
            AND {' AND '.join(conditions)}
        ORDER BY e.start_time, e.id, m.part, m.grade, m.name
    """, conn, params=params)
    conn.close()

    return data


def send_attendance_reminders(event_id, member_ids, sender_name):
    if not member_ids:
        return 0

    conn = get_connection()
    event = conn.execute("""
        SELECT date, start_time, event_type, title
        FROM events
        WHERE id = ?
    """, (event_id,)).fetchone()
    conn.close()

    if event is None:
        return 0

    title = "出席確認のお願い"
    time_text = event["start_time"] or "時間未定"
    event_name = event["title"] or event["event_type"]
    message = f"{event['date']} {time_text} の「{event_name}」について、出席登録を確認してください。送信：{sender_name}"

    sent = 0
    for member_id in member_ids:
        create_notification(
            target_member_id=int(member_id),
            notification_type="attendance_reminder",
            title=title,
            message=message,
        )
        sent += 1

    return sent
