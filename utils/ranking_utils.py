import pandas as pd
from database import get_connection


def get_ranking_data(start_date=None, end_date=None):
    conn = get_connection()

    where_date = ""
    params = []

    if start_date and end_date:
        where_date = "AND e.date BETWEEN ? AND ?"
        params.extend([start_date, end_date])

    query = f"""
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
        {where_date}
    """

    data = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return data


def calculate_member_ranking(data):
    results = []

    for member_id, group in data.groupby("member_id"):
        name = group["name"].iloc[0]
        grade = group["grade"].iloc[0]
        part = group["part"].iloc[0]

        counted = group[
            group["status"].notna()
            & ~((group["status"] == "欠席") & (group["absence_type"] == "正当"))
        ]
        total = len(counted)
        present = len(counted[counted["status"] == "出席"])
        unjustified = len(counted[counted["absence_type"] == "不当"])
        late = len(counted[counted["status"] == "遅刻"])
        class_late = len(counted[counted["status"] == "授業遅れ"])

        if total == 0:
            attendance_rate = 0
            unjustified_rate = 0
        else:
            attendance_rate = present / total * 100
            unjustified_rate = unjustified / total * 100

        results.append({
            "名前": name,
            "学年": grade,
            "パート": part,
            "出席率": attendance_rate,
            "不当欠席率": unjustified_rate,
            "遅刻回数": late,
            "授業遅れ回数": class_late,
        })

    return pd.DataFrame(results)


def calculate_part_ranking(data):
    results = []

    for part, group in data.groupby("part"):
        counted = group[
            group["status"].notna()
            & ~((group["status"] == "欠席") & (group["absence_type"] == "正当"))
        ]
        total = len(counted)
        present = len(counted[counted["status"] == "出席"])
        unjustified = len(counted[counted["absence_type"] == "不当"])

        if total == 0:
            attendance_rate = 0
            unjustified_rate = 0
        else:
            attendance_rate = present / total * 100
            unjustified_rate = unjustified / total * 100

        results.append({
            "パート": part,
            "出席率": attendance_rate,
            "不当欠席率": unjustified_rate,
        })

    return pd.DataFrame(results)
