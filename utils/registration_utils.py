from database import get_connection


def ensure_registration_requests_table(conn=None):
    owns_connection = conn is None
    if owns_connection:
        conn = get_connection()

    conn.execute("""
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
    columns = {row[1] for row in conn.execute("PRAGMA table_info(member_registration_requests)").fetchall()}
    if "pin_hash" not in columns:
        conn.execute("ALTER TABLE member_registration_requests ADD COLUMN pin_hash TEXT")
    if "pin_salt" not in columns:
        conn.execute("ALTER TABLE member_registration_requests ADD COLUMN pin_salt TEXT")
    conn.commit()

    if owns_connection:
        conn.close()


def submit_registration_request(student_id, name):
    student_id = student_id.strip()
    name = name.strip()

    conn = get_connection()
    ensure_registration_requests_table(conn)
    cur = conn.cursor()

    try:
        if cur.execute("SELECT 1 FROM members WHERE student_id = ?", (student_id,)).fetchone():
            raise ValueError("この学籍番号はすでに部員登録されています。")

        if cur.execute("""
            SELECT 1 FROM member_registration_requests
            WHERE student_id = ? AND status = '申請中'
        """, (student_id,)).fetchone():
            raise ValueError("この学籍番号の申請はすでに受け付けています。")

        cur.execute("""
            INSERT INTO member_registration_requests
            (student_id, name, grade, birthday, part, email, phone, join_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (student_id, name, 1, None, "未設定", None, None, None))
        conn.commit()
    finally:
        conn.close()


def get_registration_requests(status="申請中"):
    import pandas as pd

    conn = get_connection()
    ensure_registration_requests_table(conn)
    if status == "すべて":
        query = "SELECT * FROM member_registration_requests ORDER BY created_at DESC, id DESC"
        params = ()
    else:
        query = """
            SELECT * FROM member_registration_requests
            WHERE status = ? ORDER BY created_at, id
        """
        params = (status,)
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def review_registration_request(request_id, reviewer_id, approved, review_note="", grade=1, part=""):
    conn = get_connection()
    ensure_registration_requests_table(conn)
    cur = conn.cursor()

    try:
        request = cur.execute("""
            SELECT * FROM member_registration_requests
            WHERE id = ? AND status = '申請中'
        """, (request_id,)).fetchone()
        if not request:
            raise ValueError("この申請はすでに処理済みです。")

        if approved:
            if cur.execute("SELECT 1 FROM members WHERE student_id = ?", (request["student_id"],)).fetchone():
                raise ValueError("同じ学籍番号の部員がすでに登録されています。")
            cur.execute("""
                INSERT INTO members
                (student_id, name, grade, birthday, part, role, status, email, phone, join_date)
                VALUES (?, ?, ?, ?, ?, '一般部員', '在籍', ?, ?, ?)
            """, (
                request["student_id"], request["name"], grade,
                request["birthday"], part, request["email"],
                request["phone"], request["join_date"],
            ))

        status = "承認" if approved else "拒否"
        cur.execute("""
            UPDATE member_registration_requests
            SET status = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP,
                review_note = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (status, reviewer_id, review_note.strip(), request_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
