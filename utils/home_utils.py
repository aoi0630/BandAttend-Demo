import pandas as pd

from database import get_connection


def ensure_home_schema():
    conn = get_connection()
    cur = conn.cursor()

    existing_settings_columns = {
        row["name"]
        for row in cur.execute("PRAGMA table_info(settings)").fetchall()
    }
    if "show_next_performance_home" not in existing_settings_columns:
        cur.execute("ALTER TABLE settings ADD COLUMN show_next_performance_home INTEGER DEFAULT 1")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_task_checks (
            member_id INTEGER NOT NULL,
            task_date TEXT NOT NULL,
            task_key TEXT NOT NULL,
            completed INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(member_id, task_date, task_key),
            FOREIGN KEY(member_id) REFERENCES members(id)
        )
    """)

    cur.execute("""
        INSERT OR IGNORE INTO settings
        (id, club_name, school_year, semester)
        VALUES
        (1, '吹奏楽部', '2026年度', '前期')
    """)

    conn.commit()
    conn.close()


def get_daily_task_checks(member_id, task_date):
    ensure_home_schema()

    conn = get_connection()
    checks = pd.read_sql_query("""
        SELECT task_key, completed
        FROM daily_task_checks
        WHERE member_id = ?
        AND task_date = ?
    """, conn, params=(member_id, task_date))
    conn.close()

    return {
        row["task_key"]: bool(row["completed"])
        for _, row in checks.iterrows()
    }


def set_daily_task_check(member_id, task_date, task_key, completed):
    ensure_home_schema()

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO daily_task_checks
        (member_id, task_date, task_key, completed, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(member_id, task_date, task_key)
        DO UPDATE SET
            completed = excluded.completed,
            updated_at = CURRENT_TIMESTAMP
    """, (member_id, task_date, task_key, 1 if completed else 0))
    conn.commit()
    conn.close()


def get_show_next_performance_home():
    ensure_home_schema()

    conn = get_connection()
    row = conn.execute("""
        SELECT show_next_performance_home
        FROM settings
        WHERE id = 1
    """).fetchone()
    conn.close()

    if row is None:
        return True

    return bool(row["show_next_performance_home"])


def set_show_next_performance_home(enabled):
    ensure_home_schema()

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE settings
        SET show_next_performance_home = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
    """, (1 if enabled else 0,))
    conn.commit()
    conn.close()
