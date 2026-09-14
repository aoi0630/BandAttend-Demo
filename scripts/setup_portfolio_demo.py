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
DEMO_NAME = "ゲスト"
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

    # Vercelのコールドスタートごとに大量の架空データを書き直さない。
    # 既に最新版が入っている場合は読み取り1回で終了する。
    if conn.execute(
        """
        SELECT 1
        WHERE EXISTS (SELECT 1 FROM demo_seed_meta WHERE seed_key='portfolio-v3')
          AND EXISTS (SELECT 1 FROM demo_seed_meta WHERE seed_key='portfolio-v4')
        """
    ).fetchone():
        conn.close()
        return

    demo_id = upsert_member(
        conn, DEMO_STUDENT_ID, DEMO_NAME, 2, "2009-04-15", "クラリネット", read_only=1
    )
    ops_id = upsert_member(
        conn,
        "portfolio-ops",
        "ゲスト（運営閲覧）",
        0,
        None,
        "システム管理",
        "管理者",
        1,
    )
    fake_members = [
        ("demo-flute", "山田 さくら", 1, "2010-05-12", "フルート", "一般部員"),
        ("demo-flute-2", "小林 りん", 2, "2009-07-18", "フルート", "パートリーダー"),
        ("demo-flute-3", "中村 まお", 3, "2008-10-02", "フルート", "一般部員"),
        ("demo-clarinet", "佐藤 はるか", 2, "2009-08-03", "クラリネット", "パートリーダー"),
        ("demo-clarinet-2", "吉田 えま", 1, "2010-06-26", "クラリネット", "一般部員"),
        ("demo-clarinet-3", "山本 そら", 3, "2008-12-08", "クラリネット", "一般部員"),
        ("demo-sax", "鈴木 ひなた", 3, "2008-11-21", "サックス", "一般部員"),
        ("demo-sax-2", "松本 ゆい", 1, "2010-09-17", "サックス", "一般部員"),
        ("demo-trumpet", "田中 あおい", 2, "2009-02-14", "トランペット", "一般部員"),
        ("demo-trumpet-2", "井上 けんた", 1, "2010-04-09", "トランペット", "パートリーダー"),
        ("demo-horn", "高橋 みなみ", 3, "2008-09-09", "ホルン", "部長"),
        ("demo-horn-2", "木村 なな", 2, "2009-01-27", "ホルン", "一般部員"),
        ("demo-trombone", "清水 そうた", 3, "2008-06-11", "トロンボーン", "副部長"),
        ("demo-euphonium", "森 みさき", 2, "2009-03-30", "ユーフォニアム", "一般部員"),
        ("demo-bass", "池田 りく", 1, "2010-08-22", "バスパート", "一般部員"),
        ("demo-percussion", "伊藤 つばさ", 1, "2010-12-01", "パーカッション", "一般部員"),
        ("demo-percussion-2", "橋本 こはる", 3, "2008-05-19", "パーカッション", "パートリーダー"),
    ]
    member_ids = [demo_id]
    for values in fake_members:
        member_ids.append(upsert_member(conn, *values))

    extra_family_names = ["阿部", "石井", "上田", "遠藤", "岡田", "加藤", "川口", "斎藤", "坂本", "藤田", "前田", "村上", "渡辺", "青木"]
    extra_given_names = ["あかり", "かえで", "しおり", "なお", "みお", "ゆう", "れい", "あさひ", "かな", "たくみ", "のぞみ", "はる"]
    extra_parts = ["フルート", "クラリネット", "サックス", "トランペット", "ホルン", "トロンボーン", "ユーフォニアム", "バスパート", "パーカッション"]
    for index in range(42):
        family = extra_family_names[index % len(extra_family_names)]
        given = extra_given_names[(index * 5) % len(extra_given_names)]
        grade = index % 3 + 1
        part = extra_parts[index % len(extra_parts)]
        member_ids.append(upsert_member(
            conn,
            f"demo-member-{index + 1:02d}",
            f"{family} {given}",
            grade,
            f"{2011 - grade}-{index % 12 + 1:02d}-{index % 27 + 1:02d}",
            part,
            "一般部員",
        ))

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
        "SELECT 1 FROM demo_seed_meta WHERE seed_key='portfolio-v3'"
    ).fetchone()
    if not already_seeded:
        today = date.today()
        event_rows = []
        for day_offset in range(-35, 71):
            event_date = today + timedelta(days=day_offset)
            if event_date.weekday() not in {0, 2, 3, 5}:  # 月・水・木・土
                continue
            if event_date.weekday() == 5:
                event_rows.append((event_date, "09:00", "13:00", "合奏", "休日全体合奏", "講堂"))
            elif event_date.weekday() == 2:
                event_rows.append((event_date, "16:00", "18:30", "分奏", "木管・金管分奏", "音楽室・視聴覚室"))
            elif event_date.weekday() == 3:
                event_rows.append((event_date, "16:00", "18:00", "パート練習", "パート別練習", "各教室"))
            else:
                event_rows.append((event_date, "16:00", "18:30", "通常練習", "放課後練習", "音楽室"))
        event_rows.extend([
            (today + timedelta(days=28), "09:30", "16:00", "コンクール", "地区吹奏楽コンクール", "市民文化会館"),
            (today + timedelta(days=56), "10:00", "15:30", "依頼演奏", "地域交流コンサート", "中央公民館"),
        ])
        event_ids = []
        for event_date, start, end, kind, title, location in event_rows:
            cur = conn.execute(
                """
                INSERT INTO events
                (date, start_time, end_time, event_type, title, location, memo, created_by)
                VALUES (?, ?, ?, ?, ?, ?, '開始15分前までに集合してください。チューナー、譜面、筆記用具を持参します（デモ用の架空予定）。', ?)
                """,
                (event_date.isoformat(), start, end, kind, title, location, admin_id),
            )
            event_ids.append(int(cur.lastrowid))

        past_event_ids = [event_id for event_id, row in zip(event_ids, event_rows) if row[0] < today][-4:]
        for member_index, member_id in enumerate(member_ids):
            for event_index, event_id in enumerate(past_event_ids):
                status = "出席"
                reason = None
                absence_type = "なし"
                if (member_index + event_index) % 13 == 0:
                    status = "欠席"
                    reason = "学校行事と重なるため（サンプル）"
                    absence_type = "正当"
                elif (member_index * 2 + event_index) % 11 == 0:
                    status = "遅刻"
                    reason = "委員会活動のため（サンプル）"
                    absence_type = "正当"
                elif (member_index + event_index * 3) % 17 == 0:
                    status = "早退"
                    reason = "通院のため（サンプル）"
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
            (target_type, target_part, title, message, is_important, send_to_teacher, created_by)
            VALUES
            ('パート', 'クラリネット', 'クラリネットパート連絡',
             '次回はロングトーンの後、自由曲のAから練習します。個人譜を確認してください。',
             0, 0, ?)
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
            """
            INSERT INTO todos
            (scope, category, title, detail, created_by)
            VALUES
            ('全体', '準備', 'コンクール持ち物確認',
             '譜面、チューナー、筆記用具、昼食、飲み物を前日までに確認する（サンプル）', ?)
            """,
            (admin_id,),
        )
        for day_offset in range(1, 15):
            login_day = today - timedelta(days=day_offset)
            for member_id in member_ids[: max(5, 15 - day_offset // 2)]:
                conn.execute(
                    "INSERT INTO login_events (member_id, logged_in_at) VALUES (?, ?)",
                    (member_id, f"{login_day.isoformat()} 16:{(member_id * 7) % 60:02d}:00"),
                )
        conn.execute(
            "INSERT INTO demo_seed_meta (seed_key) VALUES ('portfolio-v3')"
        )

    # v4: 審査時にさまざまな運用場面を確認できる追加シナリオ。
    # v3を導入済みの公開DBにも一度だけ追加し、新規DBではv3に続けて投入する。
    if not conn.execute(
        "SELECT 1 FROM demo_seed_meta WHERE seed_key='portfolio-v4'"
    ).fetchone():
        today = date.today()
        scenario_events = [
            (5, "13:00", "16:00", "自主練習", "希望者自主練習", "音楽室", 0,
             "参加は任意です。基礎練習、個人練習、譜読みを中心に行います。"),
            (12, "09:00", "17:00", "集中練習", "コンクール前集中練習", "講堂", 1,
             "午前は基礎合奏、午後は課題曲と自由曲を通します。昼食、飲み物、譜面、チューナー、筆記用具を持参してください。長時間練習のため途中に休憩を設けます。"),
            (19, "16:00", "18:30", "合奏", "先生による合奏指導", "音楽室", 1,
             "先生来校日です。開始10分前までに合奏隊形を完成させてください。"),
            (26, "09:00", "16:30", "ホール練習", "コンクール会場リハーサル", "市民文化会館", 1,
             "本番と同じ配置で演奏します。楽器運搬担当は8時30分集合です。"),
            (34, "16:00", "18:00", "ミーティング", "定期演奏会 選曲会", "視聴覚室", 0,
             "候補曲の音源を聴き、演奏時間と編成を確認します。"),
            (41, "13:00", "17:00", "学年練習", "学年別アンサンブル練習", "各教室", 0,
             "1年・2年・3年に分かれてアンサンブル練習を行います。"),
            (48, "09:30", "15:30", "録音", "アンサンブルコンテスト録音審査", "音楽室", 1,
             "録音中は廊下を含めて静かにしてください。出演者以外は指定教室で待機します。"),
            (55, "10:00", "15:00", "依頼演奏", "地域交流コンサート", "中央公民館", 1,
             "地域行事での依頼演奏です。制服、譜面台、演奏用ファイルを持参してください。"),
            (69, "13:00", "18:00", "リハーサル", "定期演奏会 通しリハーサル", "講堂", 1,
             "司会、舞台転換、照明を含む通しリハーサルです。係ごとの動きも確認します。"),
            (83, "09:00", "17:00", "本番", "定期演奏会", "市民文化会館", 1,
             "集合時刻、持ち物、係の担当は事前のお知らせを確認してください。"),
            (90, None, None, "休み", "活動休止日", None, 0,
             "本日の部活動は休みです。"),
        ]
        scenario_event_ids = []
        for offset, start, end, kind, title, location, teacher_visit, memo in scenario_events:
            event_date = (today + timedelta(days=offset)).isoformat()
            conn.execute(
                """
                INSERT INTO events
                (date, start_time, end_time, event_type, title, location, memo,
                 teacher_visit, created_by)
                SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM events WHERE date=? AND title=?
                )
                """,
                (event_date, start, end, kind, title, location, memo,
                 teacher_visit, admin_id, event_date, title),
            )
            event = conn.execute(
                "SELECT id FROM events WHERE date=? AND title=? ORDER BY id LIMIT 1",
                (event_date, title),
            ).fetchone()
            scenario_event_ids.append(int(event["id"]))

        scenario_members = {}
        for student_id in (
            "demo-flute", "demo-flute-2", "demo-clarinet-2",
            "demo-trumpet", "demo-horn-2", "demo-euphonium",
            "demo-bass", "demo-percussion",
        ):
            row = conn.execute(
                "SELECT id FROM members WHERE student_id=?", (student_id,)
            ).fetchone()
            if row:
                scenario_members[student_id] = int(row["id"])

        attendance_scenarios = [
            ("demo-flute", 1, "欠席", "学校行事と重なるため（サンプル）", "未承認", "なし"),
            ("demo-clarinet-2", 1, "遅刻", "委員会終了後に参加するため（サンプル）", "未承認", "なし"),
            ("demo-trumpet", 2, "早退", "通院のため（サンプル）", "承認済み", "正当"),
            ("demo-horn-2", 3, "欠席", "家族行事のため（サンプル）", "承認済み", "正当"),
            ("demo-euphonium", 4, "遅刻", "模擬試験終了後に参加（サンプル）", "拒否", "なし"),
            ("demo-bass", 5, "欠席", "資格試験のため（サンプル）", "承認済み", "正当"),
            ("demo-percussion", 6, "早退", "帰宅時間の都合（サンプル）", "未承認", "なし"),
            ("demo-flute-2", 7, "欠席", "進路面談のため（サンプル）", "未承認", "なし"),
        ]
        for student_id, event_index, status, reason, approval, absence_type in attendance_scenarios:
            member_id = scenario_members.get(student_id)
            if member_id is None:
                continue
            reviewer = admin_id if approval in {"承認済み", "拒否"} else None
            conn.execute(
                """
                INSERT OR REPLACE INTO attendance
                (member_id, event_id, status, reason, approval_status,
                 absence_type, approved_by, approved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?,
                        CASE WHEN ? IS NULL THEN NULL ELSE CURRENT_TIMESTAMP END)
                """,
                (member_id, scenario_event_ids[event_index], status, reason,
                 approval, absence_type, reviewer, reviewer),
            )

        extra_announcements = [
            ("コンクール前集中練習について", "集合時刻と持ち物を確認してください。昼食と十分な飲み物が必要です。", 1),
            ("楽器運搬担当のお知らせ", "ホール練習日は、担当者のみ通常より30分早く集合してください。", 0),
            ("定期演奏会の選曲アンケート", "候補曲を確認し、次回のミーティングまでに希望を回答してください。", 0),
        ]
        for title, message, important in extra_announcements:
            conn.execute(
                """
                INSERT INTO announcements
                (target_type, title, message, is_important, created_by)
                SELECT '全体', ?, ?, ?, ?
                WHERE NOT EXISTS (SELECT 1 FROM announcements WHERE title=?)
                """,
                (title, message, important, admin_id, title),
            )

        extra_todos = [
            ("準備", "コンクールの持ち物を確認", "制服、譜面、チューナー、昼食、飲み物を確認する"),
            ("係活動", "演奏会係の担当を確認", "舞台、受付、楽器運搬の担当表を確認する"),
            ("提出", "選曲アンケートに回答", "定期演奏会で演奏したい曲を回答する"),
        ]
        for category, title, detail in extra_todos:
            conn.execute(
                """
                INSERT INTO todos (scope, category, title, detail, created_by)
                SELECT '全体', ?, ?, ?, ?
                WHERE NOT EXISTS (SELECT 1 FROM todos WHERE title=?)
                """,
                (category, title, detail, admin_id, title),
            )

        conn.execute(
            "INSERT INTO demo_seed_meta (seed_key) VALUES ('portfolio-v4')"
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
