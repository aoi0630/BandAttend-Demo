import pandas as pd
from database import get_connection


def create_notification(target_member_id, notification_type, title, message, related_attendance_id=None):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO notifications
        (target_member_id, notification_type, title, message, related_attendance_id)
        VALUES (?, ?, ?, ?, ?)
    """, (
        target_member_id,
        notification_type,
        title,
        message,
        related_attendance_id
    ))

    conn.commit()
    conn.close()


def get_notifications(member_id, unread_only=False):
    conn = get_connection()

    if unread_only:
        query = """
            SELECT *
            FROM notifications
            WHERE target_member_id = ?
            AND is_read = 0
            ORDER BY created_at DESC
        """
    else:
        query = """
            SELECT *
            FROM notifications
            WHERE target_member_id = ?
            ORDER BY created_at DESC
        """

    df = pd.read_sql_query(query, conn, params=(member_id,))
    conn.close()
    return df


def mark_notification_as_read(notification_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE notifications
        SET is_read = 1
        WHERE id = ?
    """, (notification_id,))

    conn.commit()
    conn.close()


def get_unread_count(member_id):
    conn = get_connection()

    df = pd.read_sql_query("""
        SELECT COUNT(*) AS count
        FROM notifications
        WHERE target_member_id = ?
        AND is_read = 0
    """, conn, params=(member_id,))

    conn.close()
    return int(df.iloc[0]["count"])