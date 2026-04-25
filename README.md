# PM-Dashboard

Live tennis dashboard for trading on Polymarket US. Personal tool, second-screen use during live trading sessions.

**Status:** Phase 1A — real API-Tennis worker in place. Pending first live-match test.

## Where to start

- `plan/Project_Plan.md` — what this project is and isn't
- `log/working_log.md` — session-by-session record
- `findings/findings.md` — operator observations from real use

## Local dev

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then fill in API_TENNIS_KEY, or set DEMO_MODE=1
uvicorn src.main:app --reload
```

Open `http://localhost:8000`.

## Run modes

- **Real**: set `API_TENNIS_KEY` in env. Worker connects to `wss://wss.api-tennis.com/live` and streams live match data into the dashboard.
- **Demo**: set `DEMO_MODE=1` (with or without an API key). Worker seeds five hardcoded matches matching the v11 design mockup. No network calls. Useful for design work and screenshots.

If neither is set, the worker logs an error and idles. The dashboard renders empty rows.

## First live-match test (10-minute gate)

After deploying with `API_TENNIS_KEY` set:

1. Open Render logs. Confirm `api_tennis_worker: connected, streaming events`.
2. Watch the dashboard during a live ATP/WTA/Challenger match. Score and game point should update within a minute of changes on the broadcast.
3. Look for `API-Tennis schema: field 'X' not found` warnings in the logs. Those reveal which defensively-guessed fields need a parser update — paste the warning into the next session and I'll patch the extractor.

## Deploy

Push to `main`. Render auto-deploys per `render.yaml`. `API_TENNIS_KEY` is set in the Render dashboard, not committed.
