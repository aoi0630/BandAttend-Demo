from datetime import date

from database import get_connection


def start_new_school_year():
    conn = get_connection()
    cur = conn.cursor()
    today = date.today().isoformat()

    cur.execute("""
        UPDATE members
        SET status = '卒部',
            leave_date = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE status = '在籍'
        AND role != '管理者'
        AND role != '顧問'
        AND grade >= 4
    """, (today,))
    graduated_count = cur.rowcount

    cur.execute("""
        UPDATE members
        SET grade = grade + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE status = '在籍'
        AND role != '管理者'
        AND role != '顧問'
        AND grade < 4
    """)
    promoted_count = cur.rowcount

    conn.commit()
    conn.close()

    return promoted_count, graduated_count
