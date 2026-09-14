"""Create an isolated BandAttend portfolio demo dataset.

Run database/init_db.py first with DB_PATH pointing at a dedicated demo DB.
This script intentionally refuses to run against the default production/local
database path.
"""

from __future__ import annotations

import os
import hashlib
import sys
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database import get_connection  # noqa: E402


DEMO_STUDENT_ID = os.getenv("DEMO_STUDENT_ID", "portfolio-demo")
DEMO_PIN = os.getenv("DEMO_PIN", "2580")
DEMO_NAME = "採用担当者様"
PIN_ITERATIONS = 210_000


def hash_pin(pin: str) -> tuple[str, str]:
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256", pin.encode("utf-8"), bytes.fromhex(salt), PIN_ITERATIONS
    )
    return digest.hex(), salt


def require_demo_database() -> None:
    db_path = os.getenv("DB_PATH", "database/band.db")
    turso_url = os.getenv("TURSO_DATABASE_URL")
    confirmed = os.getenv("BANDATTEND_DEMO_DATABASE") == "1"

    if turso_url and not confirmed:
        raise SystemExit(
            "Tursoへ作成する場合は、専用のデモDBであることを確認して "
            "BANDATTEND_DEMO_DATABASE=1 を設定してください。"
        )

    normalized = Path(db_path).name.lower()
    if not turso_url and ("demo" not in normalized or normalized == "band.db"):
        raise SystemExit(
            "誤操作防止のため、DB_PATHには demo を含む専用ファイル名を指定してください。"
        )

    if len(DEMO_PIN) != 4 or not DEMO_PIN.isdigit():
        raise SystemExit("DEMO_PINは4桁の数字にしてください。")


def upsert_member(
    conn, student_id, name, grade, birthday, part, role="一般部員", read_only=0
):
    existing = conn.execute(
        "SELECT id FROM members WHERE student_id = ?", (student_id,)
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE members
            SET name=?, grade=?, birthday=?, part=?, role=?, status='在籍',
                email=NULL, phone=NULL, hometown='サンプル市',
                band_years=3, mbti='ENFP', has_seen_guide=1,
                has_seen_privacy=1, read_only=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (name, grade, birthday, part, role, read_only, existing["id"]),
        )
        return int(existing["id"])

    cur = conn.execute(
        """
        INSERT INTO members
        (student_id, name, grade, birthday, part, role, status, hometown,
         band_years, mbti, has_seen_guide, has_seen_privacy, read_only, join_date)
        VALUES (?, ?, ?, ?, ?, ?, '在籍', 'サンプル市', 3, 'ENFP', 1, 1, ?, ?)
        """,
        (student_id, name, grade, birthday, part, role, read_only, date.today().isoformat()),
    )
    return int(cur.lastrowid)


def seed() -> None:
    require_demo_database()
    conn = get_connection()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS demo_seed_meta (
            seed_key TEXT PRIMARY KEY,
            seeded_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    admin = conn.execute(
        "SELECT id FROM members WHERE role='管理者' ORDER BY id LIMIT 1"
    ).fetchone()
    if not admin:
        raise SystemExit("先に database/init_db.py を実行してください。")
    admin_id = int(admin["id"])

    demo_id = upsert_member(
        conn, DEMO_STUDENT_ID, DEMO_NAME, 2, "2009-04-15", "クラリネット"
    )
    ops_id = upsert_member(
        conn,
        "portfolio-ops",
        "採用担当者様（運営閲覧）",
        0,
        None,
        "システム管理",
        "管理者",
        1,
    )
    fake_members = [
        ("demo-flute", "山田 さくら", 1, "2010-05-12", "フルート", "一般部員"),
        ("demo-clarinet", "佐藤 はるか", 2, "2009-08-03", "クラリネット", "パートリーダー"),
        ("demo-sax", "鈴木 ひなた", 3, "2008-11-21", "サックス", "一般部員"),
        ("demo-trumpet", "田中 あおい", 2, "2009-02-14", "トランペット", "一般部員"),
        ("demo-horn", "高橋 みなみ", 3, "2008-09-09", "ホルン", "部長"),
        ("demo-percussion", "伊藤 つばさ", 1, "2010-12-01", "パーカッション", "一般部員"),
    ]
    member_ids = [demo_id]
    for values in fake_members:
        member_ids.append(upsert_member(conn, *values))

    pin_hash, pin_salt = hash_pin(DEMO_PIN)
    conn.execute(
        """
        UPDATE members
        SET pin_hash=?, pin_salt=?, pin_failed_attempts=0, pin_locked_until=NULL,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (pin_hash, pin_salt, demo_id),
    )
    conn.execute(
        """
        UPDATE members
        SET pin_hash=?, pin_salt=?, pin_failed_attempts=0, pin_locked_until=NULL,
            read_only=1, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (pin_hash, pin_salt, ops_id),
    )

    already_seeded = conn.execute(
        "SELECT 1 FROM demo_seed_meta WHERE seed_key='portfolio-v1'"
    ).fetchone()
    if not already_seeded:
        today = date.today()
        event_rows = [
            (today - timedelta(days=7), "16:00", "18:00", "合奏", "課題曲 合奏", "音楽室"),
            (today - timedelta(days=2), "16:00", "18:00", "パート練習", "基礎練習", "各教室"),
            (today, "16:00", "18:00", "通常練習", "放課後練習", "音楽室"),
            (today + timedelta(days=3), "09:00", "12:00", "合奏", "コンクール曲 合奏", "講堂"),
            (today + timedelta(days=14), "09:30", "16:00", "コンクール", "地区吹奏楽コンクール", "市民文化会館"),
        ]
        event_ids = []
        for event_date, start, end, kind, title, location in event_rows:
            cur = conn.execute(
                """
                INSERT INTO events
                (date, start_time, end_time, event_type, title, location, memo, created_by)
                VALUES (?, ?, ?, ?, ?, ?, 'ポートフォリオ用の架空データです', ?)
                """,
                (event_date.isoformat(), start, end, kind, title, location, admin_id),
            )
            event_ids.append(int(cur.lastrowid))

        for member_index, member_id in enumerate(member_ids):
            for event_index, event_id in enumerate(event_ids[:2]):
                status = "出席"
                reason = None
                absence_type = "なし"
                if member_index == 2 and event_index == 1:
                    status = "遅刻"
                    reason = "委員会活動のため（サンプル）"
                    absence_type = "正当"
                conn.execute(
                    """
                    INSERT OR IGNORE INTO attendance
                    (member_id, event_id, status, reason, approval_status,
                     absence_type, approved_by, approved_at)
                    VALUES (?, ?, ?, ?, '承認済み', ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (member_id, event_id, status, reason, absence_type, admin_id),
                )

        conn.execute(
            """
            INSERT INTO announcements
            (target_type, title, message, is_important, created_by)
            VALUES
            ('全体', 'デモ環境へようこそ',
             'この環境の氏名・予定・出欠情報はすべて架空のサンプルデータです。',
             1, ?)
            """,
            (admin_id,),
        )
        conn.execute(
            """
            INSERT INTO announcements
            (target_type, title, message, is_important, created_by)
            VALUES
            ('全体', '次回合奏のお知らせ',
             '次回はコンクール曲を中心に合奏します。譜面と筆記用具を準備してください。',
             0, ?)
            """,
            (admin_id,),
        )
        conn.execute(
            """
            INSERT INTO todos
            (scope, category, title, detail, created_by)
            VALUES
            ('全体', '練習', '個人練習の記録',
             '苦手な部分を10分間練習し、次回の合奏に備える（サンプル）', ?)
            """,
            (admin_id,),
        )
        conn.execute(
            "INSERT INTO demo_seed_meta (seed_key) VALUES ('portfolio-v1')"
        )

    conn.commit()
    conn.close()
    print("企業向けデモ環境を作成しました")
    print(f"学籍番号: {DEMO_STUDENT_ID}")
    print(f"暗証番号: {DEMO_PIN}")
    print("運営閲覧用学籍番号: portfolio-ops")
    print("注意: この認証情報は専用デモ環境だけで使用してください。")


if __name__ == "__main__":
    seed()
