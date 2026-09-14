from datetime import date, timedelta

import pandas as pd

from database import get_connection


def month_range(target=None, offset=0):
    target = target or date.today()
    year = target.year
    month = target.month + offset

    while month <= 0:
        year -= 1
        month += 12
    while month > 12:
        year += 1
        month -= 12

    start = date(year, month, 1)
    if month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)

    return start.isoformat(), end.isoformat(), f"{year}-{month:02d}"


def get_monthly_attendance(start_date, end_date):
    conn = get_connection()
    data = pd.read_sql_query("""
        SELECT
            m.id AS member_id,
            m.name,
            m.grade,
            m.part,
            e.id AS event_id,
            e.date,
            e.event_type,
            a.status,
            a.absence_type,
            a.approval_status
        FROM members m
        CROSS JOIN events e
        LEFT JOIN attendance a
            ON a.member_id = m.id
            AND a.event_id = e.id
            AND a.approval_status = '承認済み'
        WHERE m.status = '在籍'
        AND m.role NOT IN ('管理者', '顧問')
        AND e.date BETWEEN ? AND ?
        ORDER BY m.part, m.grade, m.name, e.date
    """, conn, params=(start_date, end_date))
    conn.close()
    return data


def effective_rate(group):
    counted = group[
        group["event_id"].notna()
        & ~((group["status"] == "欠席") & (group["absence_type"] == "正当"))
    ]

    if counted.empty:
        return 0.0

    present = len(counted[counted["status"] == "出席"])
    return present / len(counted) * 100


def member_monthly_summary(data):
    rows = []

    for member_id, group in data.groupby("member_id"):
        rows.append({
            "member_id": member_id,
            "名前": group["name"].iloc[0],
            "学年": group["grade"].iloc[0],
            "パート": group["part"].iloc[0],
            "出席率": effective_rate(group),
            "遅刻回数": len(group[group["status"] == "遅刻"]),
            "授業遅れ回数": len(group[group["status"] == "授業遅れ"]),
            "欠席回数": len(group[(group["status"] == "欠席") & (group["absence_type"] != "正当")]),
        })

    return pd.DataFrame(rows)


def part_monthly_summary(data):
    rows = []

    for part, group in data.groupby("part"):
        rows.append({
            "パート": part,
            "部員数": group["member_id"].nunique(),
            "出席率": effective_rate(group),
        })

    return pd.DataFrame(rows).sort_values("出席率", ascending=False)


def get_monthly_awards(target=None):
    start, end, month_label = month_range(target)
    current_data = get_monthly_attendance(start, end)

    if current_data.empty:
        return month_label, {}, pd.DataFrame(), pd.DataFrame()

    member_summary = member_monthly_summary(current_data)
    part_summary = part_monthly_summary(current_data)

    practice_data = current_data[current_data["event_type"].isin(["通常練習", "合奏", "分奏"])]
    practice_summary = member_monthly_summary(practice_data) if not practice_data.empty else pd.DataFrame()

    perfect_names = []
    no_late_names = []

    if not practice_summary.empty:
        perfect_names = practice_summary[practice_summary["出席率"] >= 100]["名前"].tolist()
        no_late_names = practice_summary[
            (practice_summary["遅刻回数"] == 0)
            & (practice_summary["授業遅れ回数"] == 0)
        ]["名前"].tolist()

    high_attendance = member_summary[member_summary["出席率"] >= 95].sort_values("出席率", ascending=False)
    best_part = part_summary.head(1)

    prev_start, prev_end, _ = month_range(target, offset=-1)
    previous_data = get_monthly_attendance(prev_start, prev_end)
    effort = pd.DataFrame()

    if not previous_data.empty:
        previous_summary = member_monthly_summary(previous_data)[["member_id", "出席率"]].rename(columns={"出席率": "前月出席率"})
        effort = member_summary.merge(previous_summary, on="member_id", how="inner")
        effort["前月比"] = effort["出席率"] - effort["前月出席率"]
        effort = effort[effort["前月比"] > 0].sort_values("前月比", ascending=False)

    awards = {
        "皆勤賞": perfect_names,
        "高出席率賞": high_attendance,
        "優秀パート": best_part,
        "努力賞": effort,
        "無遅刻賞": no_late_names,
    }

    return month_label, awards, member_summary, part_summary


def get_performance_participation_rate():
    conn = get_connection()
    data = pd.read_sql_query("""
        SELECT
            m.id AS member_id,
            m.name,
            e.id AS event_id,
            a.status,
            a.approval_status
        FROM members m
        CROSS JOIN events e
        LEFT JOIN attendance a
            ON a.member_id = m.id
            AND a.event_id = e.id
            AND a.approval_status = '承認済み'
        WHERE m.status = '在籍'
        AND m.role NOT IN ('管理者', '顧問')
        AND e.event_type IN ('本番', 'コンクール', '定期演奏会', '依頼演奏')
    """, conn)
    conn.close()

    if data.empty:
        return 0.0

    return len(data[data["status"] == "出席"]) / len(data) * 100
