# BandAttend React Frontend Prototype

This is a Next.js prototype for a Figma-like BandAttend frontend.

It currently uses mock data and keeps the existing Streamlit app untouched.
The next step is to connect these screens to the existing BandAttend data/API.

## Run

```bash
PATH=/Users/katoaoi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin:$PATH \
  /Users/katoaoi/.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/pnpm dev
```

Default URL:

```text
http://localhost:3000
```

## API Login

The login screen now calls the BandAttend API.

Start the API from the repository root:

```bash
.venv/bin/python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Then start or open the frontend.

Initial admin login:

```text
学籍番号: admin
名前: 管理者
```
