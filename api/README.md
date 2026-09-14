# BandAttend API

This is the first API layer for connecting the React frontend to the existing BandAttend SQLite data.

It currently provides:

- `GET /api/health`
- `POST /api/auth/login`
- `GET /api/me`
- `PATCH /api/profile`
- `GET /api/home`
- `GET /api/events?month=YYYY-MM`
- `POST /api/attendance/confirm`
- `POST /api/attendance`
- `GET /api/announcements?filter=unread|all`
- `POST /api/announcements`
- `POST /api/announcements/{id}/read`
- `DELETE /api/announcements/{id}`
- `GET /api/part-memos?part=PART`
- `POST /api/part-memos`
- `DELETE /api/part-memos/{id}`

## Run

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

The React frontend expects the API at:

```text
http://localhost:8000
```

`GET /api/home` returns the logged-in member's home-screen data from the existing SQLite database:

- today's events
- next performance countdown
- unread notifications
- birthdays today
- available leave credits
- role-aware next tasks

`PATCH /api/profile` updates the logged-in member's editable profile fields:

- `birthday`
- `joinDate`

It intentionally does not expose email or phone editing in the React profile screen.

`GET /api/events?month=YYYY-MM` returns month calendar events with:

- event detail
- attendance count
- current user's attendance state
- whether the same-day attendance button can be shown

`POST /api/attendance/confirm` upserts same-day attendance from the calendar button:

- `status = '出席'`
- `approval_status = '承認済み'`
- `absence_type = 'なし'`
- `reason = 'カレンダーの出席ボタンから参加確認'`

`POST /api/attendance` upserts same-day attendance from the dedicated attendance screen:

- accepts `出席`, `欠席`, `遅刻`, or `早退`
- saves the optional reason/memo
- `approval_status = '未承認'`
- `absence_type = 'なし'`
- notifies part leaders when a member submits or updates attendance

The announcement endpoints use the existing `announcements` and `announcement_reads` tables:

- members can view unread or all visible announcements
- members can mark announcements as read
- `部長`, `副部長`, `顧問`, and `管理者` can publish announcements
- the same roles can delete announcements

The part memo endpoints use the existing `part_memos` table:

- general members and part leaders see their own part
- `部長`, `副部長`, `顧問`, and `管理者` can view all parts
- general members can post to their own part
- `部長`, `副部長`, and `管理者` can post to any part
- memo deletion follows the Streamlit page rules: managers, own-part part leaders, or the original author

## Development Login

The initial admin user is created by `database/init_db.py`:

```text
studentId: admin
name: 管理者
```
