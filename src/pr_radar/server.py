import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from pr_radar.github import GitHubError
from pr_radar.radar import Dashboard, Radar
from pr_radar.sync import SyncSettings

_STATIC_DIR = Path(__file__).parent / "static"
ACTION_HEADER = "X-PR-Radar"
_READ_ONLY_METHODS = {"GET", "HEAD", "OPTIONS"}


def build_app(radar: Radar) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        poller = asyncio.create_task(radar.run_forever())
        yield
        poller.cancel()

    app = FastAPI(title="PR Radar", lifespan=lifespan)
    # Blocks DNS-rebinding pages from reading private PR data through another host name.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    @app.middleware("http")
    async def guard_and_disable_cache(request: Request, call_next):
        # Other websites cannot send a custom header without CORS, so this stops them from triggering actions.
        if request.method not in _READ_ONLY_METHODS and request.headers.get(ACTION_HEADER) != "1":
            return Response(status_code=403, content="Missing X-PR-Radar header")
        response = await call_next(request)
        # The page changes with each update of the app, so the browser must always check for a new copy.
        response.headers["Cache-Control"] = "no-cache"
        return response

    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    @app.get("/api/dashboard")
    async def dashboard() -> Dashboard:
        return radar.dashboard()

    @app.post("/api/refresh")
    async def refresh() -> Dashboard:
        await radar.check()
        return radar.dashboard()

    @app.get("/api/menubar", response_class=PlainTextResponse)
    async def menubar() -> str:
        return radar.menubar()

    @app.get("/api/report/weekly", response_class=PlainTextResponse)
    async def weekly_report() -> str:
        try:
            return await radar.weekly_report()
        except GitHubError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.post("/api/events/read")
    async def mark_all_read() -> None:
        radar.mark_read(None)

    @app.post("/api/events/{event_id:path}/read")
    async def mark_read(event_id: str) -> None:
        radar.mark_read(event_id)

    @app.post("/api/snooze/{pr_id}")
    async def snooze(pr_id: str, minutes: int = Query(gt=0, le=60 * 24 * 14)) -> None:
        radar.snooze(pr_id, minutes)

    @app.delete("/api/snooze/{pr_id}")
    async def unsnooze(pr_id: str) -> None:
        radar.unsnooze(pr_id)

    @app.post("/api/settings/sync")
    async def update_sync(
        light_check_seconds: int | None = Query(default=None, ge=5, le=3600),
        full_check_minutes: int | None = Query(default=None, ge=1, le=120),
    ) -> SyncSettings:
        return radar.update_sync(light_check_seconds, full_check_minutes)

    @app.post("/api/focus")
    async def start_focus(minutes: int = Query(gt=0, le=240)) -> None:
        radar.start_focus(minutes)

    @app.delete("/api/focus")
    async def end_focus() -> None:
        await radar.end_focus()

    @app.post("/api/test-alert")
    async def test_alert() -> None:
        radar.send_test_alert()

    return app
