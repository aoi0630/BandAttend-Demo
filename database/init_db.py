from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from database import get_connection


conn = get_connection()
cur = conn.cursor()

# 部員情報
cur.execute("""
CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    grade INTEGER,
    birthday TEXT,
    part TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT DEFAULT '在籍',
    email TEXT,
    phone TEXT,
    hometown TEXT,
    band_years INTEGER,
    mbti TEXT,
    class_late_weekdays TEXT,
    club_duty TEXT,
    has_seen_guide INTEGER DEFAULT 0,
    has_seen_privacy INTEGER DEFAULT 0,
    read_only INTEGER DEFAULT 0,
    birthday_celebrated_on TEXT,
    pin_hash TEXT,
    pin_salt TEXT,
    pin_failed_attempts INTEGER DEFAULT 0,
    pin_locked_until TEXT,
    last_login_at TEXT,
    join_date TEXT,
    leave_date TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""")

# 未登録者からの部員登録申請
cur.execute("""
CREATE TABLE IF NOT EXISTS member_registration_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    name TEXT NOT NULL,
    grade INTEGER NOT NULL,
    birthday TEXT,
    part TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    pin_hash TEXT,
    pin_salt TEXT,
    join_date TEXT,
    status TEXT DEFAULT '申請中',
    reviewed_by INTEGER,
    reviewed_at TEXT,
    review_note TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(reviewed_by) REFERENCES members(id)
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS login_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    logged_in_at TEXT NOT NULL,
    FOREIGN KEY(member_id) REFERENCES members(id)
)
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_login_events_logged_in_at ON login_events(logged_in_at)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_login_events_member_id ON login_events(member_id)")

cur.execute("""
CREATE TABLE IF NOT EXISTS system_lifecycle (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    current_phase TEXT,
    phase_started_on TEXT,
    trial_started_on TEXT,
    release_started_on TEXT,
    updated_by INTEGER,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""")
cur.execute("INSERT OR IGNORE INTO system_lifecycle (id) VALUES (1)")

existing_member_columns = {
    row[1]
    for row in cur.execute("PRAGMA table_info(members)").fetchall()
}
for column_name, column_type in {
    "hometown": "TEXT",
    "band_years": "INTEGER",
    "mbti": "TEXT",
    "class_late_weekdays": "TEXT",
    "club_duty": "TEXT",
    "has_seen_guide": "INTEGER DEFAULT 0",
    "has_seen_privacy": "INTEGER DEFAULT 0",
    "read_only": "INTEGER DEFAULT 0",
    "birthday_celebrated_on": "TEXT",
    "pin_hash": "TEXT",
    "pin_salt": "TEXT",
    "pin_failed_attempts": "INTEGER DEFAULT 0",
    "pin_locked_until": "TEXT",
    "last_login_at": "TEXT",
}.items():
    if column_name not in existing_member_columns:
        cur.execute(f"ALTER TABLE members ADD COLUMN {column_name} {column_type}")

# 練習・本番予定
cur.execute("""
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    start_time TEXT,
    end_time TEXT,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    memo TEXT,
    teacher_visit INTEGER DEFAULT 0,
    created_by INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(created_by) REFERENCES members(id)
)
""")

existing_event_columns = {
    row[1]
    for row in cur.execute("PRAGMA table_info(events)").fetchall()
}
if "teacher_visit" not in existing_event_columns:
    cur.execute("ALTER TABLE events ADD COLUMN teacher_visit INTEGER DEFAULT 0")

# 出席記録
cur.execute("""
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL,
    event_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    reason TEXT,
    approval_status TEXT DEFAULT '未承認',
    absence_type TEXT DEFAULT 'なし',
    approved_by INTEGER,
    approved_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(member_id) REFERENCES members(id),
    FOREIGN KEY(event_id) REFERENCES events(id),
    FOREIGN KEY(approved_by) REFERENCES members(id),
    UNIQUE(member_id, event_id)
)
""")

cur.execute("""
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
""")

# 設定
cur.execute("""
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    club_name TEXT DEFAULT '吹奏楽部',
    school_year TEXT,
    semester TEXT,
    show_next_performance_home INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""")

existing_settings_columns = {
    row[1]
    for row in cur.execute("PRAGMA table_info(settings)").fetchall()
}
if "show_next_performance_home" not in existing_settings_columns:
    cur.execute("ALTER TABLE settings ADD COLUMN show_next_performance_home INTEGER DEFAULT 1")

cur.execute("""
CREATE TABLE IF NOT EXISTS feature_flags (
    feature_key TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_by INTEGER,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(updated_by) REFERENCES members(id)
)
""")
cur.execute("""
INSERT OR IGNORE INTO feature_flags (feature_key, enabled)
VALUES ('leave_credit', 1)
""")
cur.execute("""
INSERT OR IGNORE INTO feature_flags (feature_key, enabled)
VALUES ('maintenance_mode', 0)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS feature_metadata (
    feature_key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
""")

# ホームの関連システム
cur.execute("""
CREATE TABLE IF NOT EXISTS external_system_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    url TEXT NOT NULL,
    icon_url TEXT,
    created_by INTEGER NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(created_by) REFERENCES members(id)
)
""")

# ホームの日次チェック
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

# 通知
cur.execute("""
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    target_member_id INTEGER NOT NULL,

    notification_type TEXT NOT NULL,

    title TEXT NOT NULL,

    message TEXT NOT NULL,

    related_attendance_id INTEGER,

    related_todo_id INTEGER,

    is_read INTEGER DEFAULT 0,

    created_at TEXT DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY(target_member_id) REFERENCES members(id),
    FOREIGN KEY(related_attendance_id) REFERENCES attendance(id)
)
""")

# お知らせ
cur.execute("""
CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type TEXT NOT NULL,
    target_part TEXT,
    target_grade INTEGER,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    is_important INTEGER DEFAULT 0,
    send_to_teacher INTEGER DEFAULT 0,
    created_by INTEGER NOT NULL,
    todo_id INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(created_by) REFERENCES members(id)
)
""")

existing_announcement_columns = {
    row[1] for row in cur.execute("PRAGMA table_info(announcements)").fetchall()
}
if "send_to_teacher" not in existing_announcement_columns:
    cur.execute("ALTER TABLE announcements ADD COLUMN send_to_teacher INTEGER DEFAULT 0")

# お知らせ既読
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

# 欠席・遅刻一覧の共有スナップショット
cur.execute("""
CREATE TABLE IF NOT EXISTS absence_report_shares (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_roles TEXT NOT NULL,
    part_filter TEXT,
    payload_json TEXT NOT NULL,
    created_by INTEGER NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(created_by) REFERENCES members(id)
)
""")

# パート別連絡メモ
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

# バックアップ履歴
cur.execute("""
CREATE TABLE IF NOT EXISTS backup_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backup_date TEXT DEFAULT CURRENT_TIMESTAMP,
    backup_file TEXT,
    created_by INTEGER,
    FOREIGN KEY(created_by) REFERENCES members(id)
)
""")

# 休暇権利
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

# 休暇権利申請
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

# To Doリスト
cur.execute("""
CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL,
    part TEXT,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT,
    created_by INTEGER NOT NULL,
    completed INTEGER DEFAULT 0,
    completed_by INTEGER,
    completed_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(created_by) REFERENCES members(id),
    FOREIGN KEY(completed_by) REFERENCES members(id)
)
""")

for table_name, column_name in (
    ("announcements", "todo_id"),
    ("notifications", "related_todo_id"),
):
    existing_columns = {
        row[1] for row in cur.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in existing_columns:
        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} INTEGER")

# 将来用：合奏メモ・音声認識
cur.execute("""
CREATE TABLE IF NOT EXISTS practice_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER,
    speaker TEXT,
    content TEXT NOT NULL,
    category TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(event_id) REFERENCES events(id)
)
""")

# 練習終了後の振り返り・共有事項
cur.execute("""
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
""")

# 管理者がホームへ公開するランキング・統計
cur.execute("""
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
""")

existing_publication_columns = {
    row[1] for row in cur.execute("PRAGMA table_info(publications)").fetchall()
}
if "audience_type" not in existing_publication_columns:
    cur.execute("ALTER TABLE publications ADD COLUMN audience_type TEXT DEFAULT 'all'")
if "audience_value" not in existing_publication_columns:
    cur.execute("ALTER TABLE publications ADD COLUMN audience_value TEXT")

# 初期管理者
cur.execute("""
INSERT OR IGNORE INTO members
(student_id, name, grade, birthday, part, role, status, join_date)
VALUES
('admin', '管理者', 0, NULL, 'システム管理', '管理者', '在籍', NULL)
""")

cur.execute("""
UPDATE members
SET part = 'システム管理',
    grade = 0
WHERE role = '管理者'
""")

cur.execute("""
UPDATE members
SET part = 'システム管理',
    grade = 0
WHERE role = '顧問'
""")

cur.execute("""
UPDATE attendance
SET approval_status = '承認済み',
    absence_type = 'なし',
    approved_by = member_id,
    approved_at = COALESCE(approved_at, CURRENT_TIMESTAMP),
    updated_at = CURRENT_TIMESTAMP
WHERE status = '出席'
AND approval_status != '承認済み'
""")

# 初期設定
cur.execute("""
INSERT OR IGNORE INTO settings
(id, club_name, school_year, semester)
VALUES
(1, '吹奏楽部', '2026年度', '前期')
""")

conn.commit()
conn.close()

print("BandAttend Version 2.0 データベースを作成しました")
