import pandas as pd

from database import get_connection


def ensure_todo_schema():
    conn = get_connection()
    cur = conn.cursor()

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

    conn.commit()
    conn.close()


def create_todo(scope, part, category, title, detail, created_by):
    ensure_todo_schema()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO todos
        (scope, part, category, title, detail, created_by)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        scope,
        part if scope == "パート" else None,
        category,
        title,
        detail,
        created_by,
    ))

    conn.commit()
    conn.close()


def get_todos(scope=None, part=None, include_completed=False):
    ensure_todo_schema()

    conditions = []
    params = []

    if scope:
        conditions.append("t.scope = ?")
        params.append(scope)

    if part:
        conditions.append("t.part = ?")
        params.append(part)

    if not include_completed:
        conditions.append("t.completed = 0")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    conn = get_connection()
    todos = pd.read_sql_query(f"""
        SELECT
            t.id,
            t.scope,
            t.part,
            t.category,
            t.title,
            t.detail,
            t.completed,
            t.created_at,
            creator.name AS creator_name,
            completer.name AS completer_name,
            t.completed_at
        FROM todos t
        JOIN members creator ON t.created_by = creator.id
        LEFT JOIN members completer ON t.completed_by = completer.id
        {where}
        ORDER BY t.completed, t.created_at DESC
    """, conn, params=params)
    conn.close()

    return todos


def complete_todo(todo_id, completed_by):
    ensure_todo_schema()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE todos
        SET completed = 1,
            completed_by = ?,
            completed_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (completed_by, todo_id))

    conn.commit()
    conn.close()


def delete_todo(todo_id):
    ensure_todo_schema()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM todos WHERE id = ?", (todo_id,))

    conn.commit()
    conn.close()
