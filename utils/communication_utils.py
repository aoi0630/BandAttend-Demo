import pandas as pd

from database import get_connection
from utils.notification_utils import create_notification


def ensure_communication_schema():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_type TEXT NOT NULL,
            target_part TEXT,
            target_grade INTEGER,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            is_important INTEGER DEFAULT 0,
            created_by INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(created_by) REFERENCES members(id)
        )
    """)
    existing_columns = {
        row["name"]
        for row in cur.execute("PRAGMA table_info(announcements)").fetchall()
    }
    if "is_important" not in existing_columns:
        cur.execute("ALTER TABLE announcements ADD COLUMN is_important INTEGER DEFAULT 0")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS announcement_reads (
            announcement_id INTEGER NOT NULL,
            member_id INTEGER NOT NULL,
            read_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(announcement_id, member_id),
            FOREIGN KEY(announcement_id) REFERENCES announcements(id),
            FOREIGN KEY(member_id) REFERENCES members(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS part_memos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            part TEXT NOT NULL,
            title TEXT NOT NULL,
            memo TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(created_by) REFERENCES members(id)
        )
    """)

    conn.commit()
    conn.close()


def _target_members(target_type, target_part=None, target_grade=None):
    conditions = ["status = '在籍'"]
    params = []

    if target_type == "パート":
        conditions.append("part = ?")
        params.append(target_part)
    elif target_type == "学年":
        conditions.append("grade = ?")
        params.append(target_grade)

    conn = get_connection()
    members = pd.read_sql_query(f"""
        SELECT id, name, part, grade
        FROM members
        WHERE {' AND '.join(conditions)}
        ORDER BY part, grade, name
    """, conn, params=params)
    conn.close()

    return members


def create_announcement(target_type, target_part, target_grade, title, message, created_by, is_important=False):
    ensure_communication_schema()

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO announcements
        (target_type, target_part, target_grade, title, message, is_important, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        target_type,
        target_part if target_type == "パート" else None,
        target_grade if target_type == "学年" else None,
        title,
        message,
        1 if is_important else 0,
        created_by,
    ))
    announcement_id = cur.lastrowid
    conn.commit()
    conn.close()

    targets = _target_members(target_type, target_part, target_grade)
    for member_id in targets["id"].tolist():
        create_notification(
            target_member_id=int(member_id),
            notification_type="announcement",
            title=title,
            message=message,
        )

    return announcement_id, len(targets)


def get_announcements_for_member(member_id, part, grade):
    ensure_communication_schema()

    conn = get_connection()
    announcements = pd.read_sql_query("""
        SELECT
            a.id,
            a.target_type,
            a.target_part,
            a.target_grade,
            a.title,
            a.message,
            a.is_important,
            a.created_at,
            creator.name AS creator_name,
            CASE WHEN ar.member_id IS NULL THEN 0 ELSE 1 END AS is_read
        FROM announcements a
        JOIN members creator ON a.created_by = creator.id
        LEFT JOIN announcement_reads ar
            ON a.id = ar.announcement_id
            AND ar.member_id = ?
        WHERE
            a.target_type = '全体'
            OR (a.target_type = 'パート' AND a.target_part = ?)
            OR (a.target_type = '学年' AND a.target_grade = ?)
        ORDER BY a.is_important DESC, a.created_at DESC
    """, conn, params=(member_id, part, grade))
    conn.close()

    return announcements


def mark_announcement_as_read(announcement_id, member_id):
    ensure_communication_schema()

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO announcement_reads
        (announcement_id, member_id)
        VALUES (?, ?)
    """, (announcement_id, member_id))
    conn.commit()
    conn.close()


def delete_announcement(announcement_id):
    ensure_communication_schema()

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM announcement_reads WHERE announcement_id = ?", (announcement_id,))
    cur.execute("DELETE FROM announcements WHERE id = ?", (announcement_id,))
    conn.commit()
    conn.close()


def create_part_memo(part, title, memo, created_by):
    ensure_communication_schema()

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO part_memos
        (part, title, memo, created_by)
        VALUES (?, ?, ?, ?)
    """, (part, title, memo, created_by))
    conn.commit()
    conn.close()


def get_part_memos(part):
    ensure_communication_schema()

    conn = get_connection()
    memos = pd.read_sql_query("""
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
        ORDER BY pm.created_at DESC
    """, conn, params=(part,))
    conn.close()

    return memos


def delete_part_memo(memo_id):
    ensure_communication_schema()

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM part_memos WHERE id = ?", (memo_id,))
    conn.commit()
    conn.close()
