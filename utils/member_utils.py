import pandas as pd
from database import get_connection


def get_members(status="在籍"):
    conn = get_connection()

    if status == "全員":
        query = """
            SELECT *
            FROM members
            ORDER BY part, grade, name
        """
        df = pd.read_sql_query(query, conn)
    else:
        query = """
            SELECT *
            FROM members
            WHERE status = ?
            ORDER BY part, grade, name
        """
        df = pd.read_sql_query(query, conn, params=(status,))

    conn.close()
    return df


def add_member(student_id, name, grade, birthday, part, role, email, phone, join_date):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO members
        (student_id, name, grade, birthday, part, role, status, email, phone, join_date)
        VALUES (?, ?, ?, ?, ?, ?, '在籍', ?, ?, ?)
    """, (
        student_id,
        name,
        grade,
        birthday,
        part,
        role,
        email,
        phone,
        join_date
    ))

    conn.commit()
    conn.close()


def update_member(member_id, student_id, name, grade, birthday, part, role, status, email, phone, join_date, leave_date):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE members
        SET student_id = ?,
            name = ?,
            grade = ?,
            birthday = ?,
            part = ?,
            role = ?,
            status = ?,
            email = ?,
            phone = ?,
            join_date = ?,
            leave_date = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        student_id,
        name,
        grade,
        birthday,
        part,
        role,
        status,
        email,
        phone,
        join_date,
        leave_date,
        member_id
    ))

    conn.commit()
    conn.close()


def retire_member(member_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE members
        SET status = '退部',
            leave_date = DATE('now'),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (member_id,))

    conn.commit()
    conn.close()

def import_members_from_csv(df):
    conn = get_connection()
    cur = conn.cursor()

    success_count = 0
    error_rows = []

    for index, row in df.iterrows():
        try:
            cur.execute("""
                INSERT INTO members
                (student_id, name, grade, birthday, part, role, status, email, phone, join_date)
                VALUES (?, ?, ?, ?, ?, ?, '在籍', ?, ?, ?)
            """, (
                str(row.get("student_id", "")),
                str(row.get("name", "")),
                int(row.get("grade", 0)),
                str(row.get("birthday", "")),
                str(row.get("part", "")),
                str(row.get("role", "一般部員")),
                str(row.get("email", "")),
                str(row.get("phone", "")),
                str(row.get("join_date", "")),
            ))

            success_count += 1

        except Exception as e:
            error_rows.append({
                "行番号": index + 1,
                "学籍番号": row.get("student_id", ""),
                "名前": row.get("name", ""),
                "エラー": str(e)
            })

    conn.commit()
    conn.close()

    return success_count, error_rows