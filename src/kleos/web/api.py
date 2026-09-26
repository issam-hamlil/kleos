"""JSON API for the Kleos Android app: review queue, approval, analytics.

Every route requires a bearer token (KLEOS_API_TOKEN), compared in constant
time. If the token is unset or too short the API refuses every request rather
than running open - this router is reachable from the internet through the
tunnel, and "forgot to configure auth" must fail closed.

Responses use one envelope: {"success": bool, "data": ..., "error": str|null}.
"""

from __future__ import annotations

import hmac
import logging
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Path, Query, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from kleos import clip_store, db
from kleos.config import MIN_API_TOKEN_LENGTH, Settings
from kleos.models import Clip, ClipStatus, PublishResult
from kleos.pipeline import (
    ClipNotPendingError,
    Pipeline,
    PublishingDisabledError,
    UnknownPlatformError,
)

logger = logging.getLogger(__name__)

API_PREFIX = "/api"
VIDEO_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
VideoId = Annotated[str, Path(pattern=VIDEO_ID_PATTERN)]


def require_token(request: Request, authorization: Annotated[str | None, Header()] = None) -> None:
    settings: Settings = request.app.state.settings
    expected = settings.kleos_api_token
    if len(expected) < MIN_API_TOKEN_LENGTH:
        raise HTTPException(status_code=503, detail="API disabled: KLEOS_API_TOKEN is not set")
    scheme, _, provided = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        provided.strip().encode(), expected.encode()
    ):
        raise HTTPException(
            status_code=401,
            detail="invalid or missing token",
            headers={"WWW-Authenticate": "Bearer"},
        )


router = APIRouter(prefix=API_PREFIX, tags=["api"], dependencies=[Depends(require_token)])


class ApproveRequest(BaseModel):
    platforms: list[str] = Field(min_length=1, max_length=10)


def _ok(data: Any) -> dict[str, Any]:
    return {"success": True, "data": data, "error": None}


def _fail(status_code: int, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"success": False, "data": None, "error": message},
        headers=headers,
    )


def _clip_json(clip: Clip, ttl_minutes: int) -> dict[str, Any]:
    return {
        "video_id": clip.ref.video_id,
        "title": clip.ref.title,
        "channel_id": clip.ref.channel_id,
        "watch_url": clip.ref.watch_url,
        "published_at": clip.ref.published_at.isoformat(),
        "created_at": clip.created_at.isoformat(),
        "expires_at": (clip.created_at + timedelta(minutes=ttl_minutes)).isoformat(),
        "duration_s": clip.duration_s,
        "status": clip.status.value,
        "platforms": list(clip.platforms),
    }


def _result_json(result: PublishResult) -> dict[str, Any]:
    return {
        "platform": result.platform,
        "ok": result.ok,
        "remote_id": result.remote_id,
        "error": result.error,
    }


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _pipeline(request: Request) -> Pipeline:
    return request.app.state.pipeline


@router.get("/platforms")
async def platforms(request: Request) -> dict[str, Any]:
    """Platforms a clip can be approved to right now."""
    return _ok(
        [
            {"name": p.name, "max_duration_s": p.max_duration_s}
            for p in _pipeline(request).available_publishers()
        ]
    )


@router.get("/pending")
async def pending(request: Request) -> dict[str, Any]:
    settings = _settings(request)
    clips = clip_store.list_by_status(settings.db_path, ClipStatus.PENDING)
    return _ok([_clip_json(clip, settings.pending_ttl_minutes) for clip in clips])


@router.get("/clips/{video_id}")
async def clip_detail(video_id: VideoId, request: Request) -> dict[str, Any]:
    settings = _settings(request)
    clip = clip_store.get(settings.db_path, video_id)
    if clip is None:
        raise HTTPException(status_code=404, detail="clip not found")
    return _ok(_clip_json(clip, settings.pending_ttl_minutes))


@router.get("/clips/{video_id}/stream", response_model=None)
async def stream(video_id: VideoId, request: Request) -> FileResponse:
    """The pending clip itself. FileResponse honours Range, so players can seek.

    The path comes from the database row, never from the request.
    """
    clip = clip_store.get(_settings(request).db_path, video_id)
    if clip is None or clip.status is not ClipStatus.PENDING or not clip.path.exists():
        raise HTTPException(status_code=404, detail="clip not available")
    return FileResponse(clip.path, media_type="video/mp4")


@router.post("/clips/{video_id}/approve")
async def approve(video_id: VideoId, body: ApproveRequest, request: Request) -> dict[str, Any]:
    try:
        results = await _pipeline(request).approve(video_id, body.platforms)
    except UnknownPlatformError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PublishingDisabledError as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    except ClipNotPendingError as exc:
        raise HTTPException(status_code=409, detail="clip is not pending") from exc
    logger.info("Approved %s for %s", video_id, ", ".join(body.platforms))
    return _ok({"video_id": video_id, "results": [_result_json(r) for r in results]})


@router.post("/clips/{video_id}/reject")
async def reject(video_id: VideoId, request: Request) -> dict[str, Any]:
    try:
        await _pipeline(request).reject(video_id)
    except ClipNotPendingError as exc:
        raise HTTPException(status_code=409, detail="clip is not pending") from exc
    return _ok({"video_id": video_id, "status": ClipStatus.REJECTED.value})


@router.get("/history")
async def history(
    request: Request, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> dict[str, Any]:
    rows = db.recent_publications(_settings(request).db_path, limit=limit)
    return _ok(
        [
            {
                "video_id": row["video_id"],
                "title": row["title"] or row["video_id"],
                "platform": row["platform"],
                "ok": bool(row["ok"]),
                "remote_id": row["remote_id"],
                "error": row["error"],
                "at": row["at"],
            }
            for row in rows
        ]
    )


@router.get("/analytics")
async def analytics(request: Request) -> dict[str, Any]:
    settings = _settings(request)
    counts = clip_store.status_counts(settings.db_path)
    decided = counts["approved"] + counts["rejected"] + counts["expired"]
    reviewed = clip_store.decided(settings.db_path)
    review_minutes = [
        (clip.decided_at - clip.created_at).total_seconds() / 60
        for clip in reviewed
        if clip.decided_at is not None
    ]
    return _ok(
        {
            "clips": counts,
            "approval_rate": counts["approved"] / decided if decided else None,
            "avg_review_minutes": (
                sum(review_minutes) / len(review_minutes) if review_minutes else None
            ),
            "platforms": db.publication_counts(settings.db_path),
            "publishing_enabled": _pipeline(request).publish_enabled(),
        }
    )


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if request.url.path.startswith(API_PREFIX):
        return _fail(exc.status_code, str(exc.detail), getattr(exc, "headers", None))
    return await http_exception_handler(request, exc)


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    if request.url.path.startswith(API_PREFIX):
        return _fail(422, "invalid request")
    return await request_validation_exception_handler(request, exc)


def install(app: FastAPI) -> None:
    """Mount the API and make its errors use the same envelope as its successes."""
    app.include_router(router)
    app.add_exception_handler(StarletteHTTPException, _http_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_error)  # type: ignore[arg-type]
