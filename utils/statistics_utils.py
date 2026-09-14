import pandas as pd
from database import get_connection


def get_today_events(today):
    conn = get_connection()

    events = pd.read_sql_query("""
        SELECT id, date, start_time, end_time, event_type, title, location, memo
        FROM events
        WHERE date = ?
        ORDER BY start_time
    """, conn, params=(today,))

    conn.close()
    return events


def get_today_attendance_rate(today):
    conn = get_connection()

    data = pd.read_sql_query("""
        SELECT
            a.status,
            a.absence_type
        FROM attendance a
        JOIN events e ON a.event_id = e.id
        JOIN members m ON a.member_id = m.id
        WHERE e.date = ?
        AND m.status = '在籍'
        AND a.approval_status = '承認済み'
    """, conn, params=(today,))

    member_count = pd.read_sql_query("""
        SELECT COUNT(*) AS count
        FROM members
        WHERE status = '在籍'
        AND role != '管理者'
    """, conn)

    conn.close()

    total_members = int(member_count.iloc[0]["count"])

    if total_members == 0:
        return 0.0, 0, 0, 0, 0, 0

    justified_absent = len(data[(data["status"] == "欠席") & (data["absence_type"] == "正当")])
    effective_total_members = max(total_members - justified_absent, 0)

    if effective_total_members == 0:
        return 0.0, 0, 0, 0, 0, 0

    present = len(data[data["status"] == "出席"])
    absent = len(data[(data["status"] == "欠席") & (data["absence_type"] != "正当")])
    late = len(data[data["status"] == "遅刻"])
    class_late = len(data[data["status"] == "授業遅れ"])
    early_leave = len(data[data["status"] == "早退"])

    attendance_rate = present / effective_total_members * 100

    return attendance_rate, present, absent, late, class_late, early_leave


def get_today_birthdays(today):
    conn = get_connection()

    # today は "2026-07-01" のような文字列
    month_day = today[5:]

    birthdays = pd.read_sql_query("""
        SELECT name, grade, part, role, birthday
        FROM members
        WHERE status = '在籍'
        AND birthday IS NOT NULL
        AND substr(birthday, 6, 5) = ?
        ORDER BY part, grade, name
    """, conn, params=(month_day,))

    conn.close()
    return birthdays


def get_next_performance(today):
    conn = get_connection()

    performance = pd.read_sql_query("""
        SELECT date, title, event_type, location, start_time
        FROM events
        WHERE event_type IN ('本番', 'コンクール', '定期演奏会', '依頼演奏')
        AND date >= ?
        ORDER BY date, start_time
        LIMIT 1
    """, conn, params=(today,))

    conn.close()
    return performance


def get_pending_count():
    conn = get_connection()

    pending = pd.read_sql_query("""
        SELECT COUNT(*) AS count
        FROM attendance
        WHERE approval_status = '未承認'
    """, conn)

    conn.close()
    return int(pending.iloc[0]["count"])


def get_statistics_data():
    conn = get_connection()

    data = pd.read_sql_query("""
        SELECT
            m.id AS member_id,
            m.name,
            m.grade,
            m.part,
            a.status,
            a.absence_type,
            e.date
        FROM members m
        LEFT JOIN attendance a ON m.id = a.member_id
        LEFT JOIN events e ON a.event_id = e.id
        WHERE m.status = '在籍'
        AND m.role != '管理者'
        AND (a.approval_status = '承認済み' OR a.approval_status IS NULL)
    """, conn)

    conn.close()
    return data


def calc_attendance_rate(group):
    counted = group[
        group["status"].notna()
        & ~((group["status"] == "欠席") & (group["absence_type"] == "正当"))
    ]
    total = len(counted)
    present = len(counted[counted["status"] == "出席"])

    if total == 0:
        return 0

    return present / total * 100


def get_monthly_trend(data):
    data = data.dropna(subset=["date"]).copy()
    data["month"] = pd.to_datetime(data["date"]).dt.strftime("%Y-%m")

    results = []

    for month, group in data.groupby("month"):
        results.append({
            "月": month,
            "出席率": calc_attendance_rate(group)
        })

    return pd.DataFrame(results).sort_values("月")


def get_grade_stats(data):
    results = []

    for grade, group in data.groupby("grade"):
        results.append({
            "学年": f"{int(grade)}年",
            "出席率": calc_attendance_rate(group)
        })

    return pd.DataFrame(results)


def get_part_stats(data):
    results = []

    for part, group in data.groupby("part"):
        results.append({
            "パート": part,
            "出席率": calc_attendance_rate(group)
        })

    return pd.DataFrame(results)


def get_part_monthly_trend(data):
    data = data.dropna(subset=["date"]).copy()
    data["month"] = pd.to_datetime(data["date"]).dt.strftime("%Y-%m")

    results = []

    for (month, part), group in data.groupby(["month", "part"]):
        results.append({
            "月": month,
            "パート": part,
            "出席率": calc_attendance_rate(group)
        })

    return pd.DataFrame(results).sort_values(["月", "パート"])

def get_part_monthly_trend(data):
    data = data.dropna(subset=["date"]).copy()

    if data.empty:
        return pd.DataFrame()

    data["month"] = pd.to_datetime(data["date"]).dt.strftime("%Y-%m")

    results = []

    for (month, part), group in data.groupby(["month", "part"]):
        results.append({
            "月": month,
            "パート": part,
            "出席率": calc_attendance_rate(group)
        })

    return pd.DataFrame(results).sort_values(["月", "パート"])
