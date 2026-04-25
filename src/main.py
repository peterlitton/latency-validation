"""FastAPI app.

Serves the dashboard HTML at /, the current state as JSON at /api/matches,
and pushes state snapshots over WS at /ws/matches.

The API-Tennis worker runs as a background asyncio task started on lifespan.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from . import api_tennis_worker, state

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main")

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = Jinja2Templates(directory=ROOT / "templates")

# Push cadence for WS snapshots. Tighten if it feels laggy in real use.
WS_PUSH_INTERVAL_SEC = 1.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker_task = asyncio.create_task(api_tennis_worker.run(), name="api_tennis_worker")
    log.info("worker started")
    try:
        yield
    finally:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        log.info("worker stopped")


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
async def dashboard(request: Request):
    return TEMPLATES.TemplateResponse("dashboard.html", {"request": request})


@app.get("/api/matches")
async def matches_json():
    return JSONResponse(state.snapshot())


@app.websocket("/ws/matches")
async def matches_ws(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            await ws.send_json(state.snapshot())
            await asyncio.sleep(WS_PUSH_INTERVAL_SEC)
    except WebSocketDisconnect:
        return
    except Exception:
        log.exception("ws send failed")
        try:
            await ws.close()
        except Exception:
            pass
