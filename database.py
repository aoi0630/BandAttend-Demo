import os
import re
import sqlite3

IS_PORTFOLIO_DEMO = os.getenv("BANDATTEND_DEMO_DATABASE") == "1"
DB_PATH = os.getenv(
    "DB_PATH",
    "/tmp/bandattend_portfolio_demo.db" if IS_PORTFOLIO_DEMO else "database/band.db",
)
TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN")

TABLE_COLUMNS = {
    "events": [
        "id", "date", "start_time", "end_time", "event_type", "title",
        "location", "memo", "teacher_visit", "created_by", "created_at", "updated_at",
    ],
    "members": [
        "id",
        "student_id",
        "name",
        "grade",
        "birthday",
        "part",
        "role",
        "status",
        "email",
        "phone",
        "hometown",
        "band_years",
        "mbti",
        "class_late_weekdays",
        "club_duty",
        "has_seen_guide",
        "has_seen_privacy",
        "read_only",
        "birthday_celebrated_on",
        "pin_hash",
        "pin_salt",
        "pin_failed_attempts",
        "pin_locked_until",
        "last_login_at",
        "join_date",
        "leave_date",
        "created_at",
        "updated_at",
    ],
    "publications": [
        "id",
        "kind",
        "title",
        "period",
        "payload_json",
        "is_published",
        "audience_type",
        "audience_value",
        "created_by",
        "created_at",
        "updated_at",
    ],
    "announcements": [
        "id", "target_type", "target_part", "target_grade", "title", "message",
        "is_important", "send_to_teacher", "created_by", "todo_id", "created_at",
    ],
    "practice_reflections": [
        "id",
        "event_id",
        "target_scope",
        "title",
        "content",
        "created_by",
        "created_at",
        "updated_at",
    ],
    "member_registration_requests": [
        "id",
        "student_id",
        "name",
        "grade",
        "birthday",
        "part",
        "email",
        "phone",
        "join_date",
        "status",
        "reviewed_by",
        "reviewed_at",
        "review_note",
        "created_at",
        "updated_at",
    ],
    "login_events": ["id", "member_id", "logged_in_at"],
    "system_lifecycle": [
        "id", "current_phase", "phase_started_on", "trial_started_on",
        "release_started_on", "updated_by", "updated_at",
    ],
}


def ensure_event_teacher_visit_column(conn):
    columns = {row[1] for row in conn.execute("PRAGMA table_info(events)").fetchall()}
    if "teacher_visit" not in columns:
        conn.execute("ALTER TABLE events ADD COLUMN teacher_visit INTEGER DEFAULT 0")
        conn.commit()


def ensure_members_optional_columns(conn):
    columns = {row[1] for row in conn.execute("PRAGMA table_info(members)").fetchall()}
    changed = False
    if "club_duty" not in columns:
        conn.execute("ALTER TABLE members ADD COLUMN club_duty TEXT")
        changed = True
    if "has_seen_guide" not in columns:
        conn.execute("ALTER TABLE members ADD COLUMN has_seen_guide INTEGER DEFAULT 0")
        changed = True
    if "has_seen_privacy" not in columns:
        conn.execute("ALTER TABLE members ADD COLUMN has_seen_privacy INTEGER DEFAULT 0")
        changed = True
    if "read_only" not in columns:
        conn.execute("ALTER TABLE members ADD COLUMN read_only INTEGER DEFAULT 0")
        changed = True
    if "birthday_celebrated_on" not in columns:
        conn.execute("ALTER TABLE members ADD COLUMN birthday_celebrated_on TEXT")
        changed = True
    for column_name, column_type in {
        "pin_hash": "TEXT",
        "pin_salt": "TEXT",
        "pin_failed_attempts": "INTEGER DEFAULT 0",
        "pin_locked_until": "TEXT",
    }.items():
        if column_name not in columns:
            conn.execute(f"ALTER TABLE members ADD COLUMN {column_name} {column_type}")
            changed = True
    if "last_login_at" not in columns:
        conn.execute("ALTER TABLE members ADD COLUMN last_login_at TEXT")
        changed = True
    if changed:
        conn.commit()


def ensure_todo_notification_columns(conn):
    announcements = {row[1] for row in conn.execute("PRAGMA table_info(announcements)").fetchall()}
    notifications = {row[1] for row in conn.execute("PRAGMA table_info(notifications)").fetchall()}
    changed = False
    if "todo_id" not in announcements:
        conn.execute("ALTER TABLE announcements ADD COLUMN todo_id INTEGER")
        changed = True
    if "related_todo_id" not in notifications:
        conn.execute("ALTER TABLE notifications ADD COLUMN related_todo_id INTEGER")
        changed = True
    if changed:
        conn.commit()


def ensure_announcement_teacher_column(conn):
    columns = {row[1] for row in conn.execute("PRAGMA table_info(announcements)").fetchall()}
    if "send_to_teacher" not in columns:
        conn.execute("ALTER TABLE announcements ADD COLUMN send_to_teacher INTEGER DEFAULT 0")
        conn.commit()


def ensure_maintenance_flag(conn):
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
        "INSERT OR IGNORE INTO feature_flags (feature_key, enabled) VALUES ('maintenance_mode', 0)"
    )
    conn.commit()


def maintenance_mode_enabled(conn):
    ensure_maintenance_flag(conn)
    row = conn.execute(
        "SELECT enabled FROM feature_flags WHERE feature_key = 'maintenance_mode'"
    ).fetchone()
    return bool(row and row["enabled"])


class DictRow(dict):
    def __init__(self, keys, values):
        super().__init__(zip(keys, values))
        self._values = list(values)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


class CursorAdapter:
    def __init__(self, cursor, sql=None):
        self._cursor = cursor
        self._sql = sql or ""
        self.description = getattr(cursor, "description", None)

    def _keys(self):
        if not self.description:
            return _infer_column_names(self._sql)
        return [column[0] if isinstance(column, (list, tuple)) else column for column in self.description]

    def _row(self, row):
        if row is None or isinstance(row, dict):
            return row
        keys = self._keys()
        if not keys:
            return row
        return DictRow(keys, row)

    def fetchone(self):
        return self._row(self._cursor.fetchone())

    def fetchall(self):
        return [self._row(row) for row in self._cursor.fetchall()]

    def execute(self, *args, **kwargs):
        result = self._cursor.execute(*args, **kwargs)
        sql = args[0] if args else None
        return CursorAdapter(result, sql)

    def __iter__(self):
        for row in self._cursor:
            yield self._row(row)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class ConnectionAdapter:
    def __init__(self, connection):
        self._connection = connection

    def execute(self, *args, **kwargs):
        sql = args[0] if args else None
        return CursorAdapter(self._connection.execute(*args, **kwargs), sql)

    def cursor(self, *args, **kwargs):
        return CursorAdapter(self._connection.cursor(*args, **kwargs))

    def __getattr__(self, name):
        return getattr(self._connection, name)


def _get_turso_connection():
    try:
        import libsql
    except ImportError as exc:
        raise RuntimeError(
            "TURSO_DATABASE_URL is set, but the libsql package is not installed."
        ) from exc

    return ConnectionAdapter(
        libsql.connect(
            database=TURSO_DATABASE_URL,
            auth_token=TURSO_AUTH_TOKEN,
        )
    )

def _split_select_columns(select_clause):
    columns = []
    current = []
    depth = 0
    quote = None
    for char in select_clause:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in {"'", '"', "`"}:
            quote = char
            current.append(char)
            continue
        if char == "(":
            depth += 1
        elif char == ")" and depth:
            depth -= 1
        if char == "," and depth == 0:
            columns.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        columns.append("".join(current).strip())
    return columns


def _clean_column_name(name):
    return name.strip().strip('"').strip("'").strip("`").split(".")[-1]


def _infer_column_name(expression):
    alias_match = re.search(r"\s+AS\s+([\"'`]?\w+[\"'`]?)\s*$", expression, re.IGNORECASE)
    if alias_match:
        return _clean_column_name(alias_match.group(1))

    parts = expression.strip().split()
    if len(parts) > 1 and not parts[-1].upper().startswith(("FROM", "WHERE", "ORDER", "LIMIT")):
        return _clean_column_name(parts[-1])

    return _clean_column_name(expression)


def _infer_column_names(sql):
    normalized = " ".join((sql or "").strip().split())
    if not normalized.upper().startswith("SELECT "):
        return []

    star_match = re.match(r"SELECT\s+\*\s+FROM\s+([a-zA-Z_][a-zA-Z0-9_]*)", normalized, re.IGNORECASE)
    if star_match:
        return TABLE_COLUMNS.get(star_match.group(1).lower(), [])

    match = re.match(r"SELECT\s+(.+?)\s+FROM\s+", normalized, re.IGNORECASE)
    if not match:
        return []

    return [_infer_column_name(column) for column in _split_select_columns(match.group(1))]


def get_connection():
    if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
        return _get_turso_connection()

    directory = os.path.dirname(DB_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
