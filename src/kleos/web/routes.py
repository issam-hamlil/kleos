"""The operator surface: a status page, the kill switch, and media serving.

This is what the Cloudflare Tunnel exposes, so it is also what you open on your
phone. Put Cloudflare Access in front of it - the app has no auth of its own,
by design, because delegating that to the tunnel is both simpler and better.

The media route is the one exception to "nothing here is public": Meta's
servers must be able to reach it unauthenticated to fetch a Reel, so exclude
/media from any Access policy you configure.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from kleos import db
from kleos.config import Settings
from kleos.media.registry import MediaRegistry
from kleos.pipeline import Pipeline

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    settings: Settings = request.app.state.settings
    pipeline: Pipeline = request.app.state.pipeline
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "publications": db.recent_publications(settings.db_path, limit=50),
            "publish_enabled": pipeline.publish_enabled(),
            "channels": settings.channel_ids,
            "missing_credentials": settings.missing_credentials(),
            "platforms": tuple(
                (p.name, p.enabled, p.max_duration_s) for p in request.app.state.publishers
            ),
        },
    )


@router.post("/kill-switch")
async def toggle_kill_switch(request: Request) -> RedirectResponse:
    pipeline: Pipeline = request.app.state.pipeline
    new_state = not pipeline.publish_enabled()
    pipeline.set_publish_enabled(new_state)
    logger.warning("Kill switch toggled: publishing %s", "ENABLED" if new_state else "DISABLED")
    return RedirectResponse(url="/", status_code=303)


@router.get("/media/{token}.mp4")
async def serve_media(token: str, request: Request) -> FileResponse:
    """Serve a registered file to Meta.

    The path comes from the registry, never from the request, so a crafted token
    cannot escape the work directory. Unknown or expired tokens 404.
    """
    registry: MediaRegistry = request.app.state.registry
    path = registry.resolve(token)
    if path is None:
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path, media_type="video/mp4")


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
