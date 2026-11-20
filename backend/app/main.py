import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager
import json
import logging
import os
from time import monotonic
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from sqlalchemy import text
from .config import settings
from .db import SessionLocal, load_models
from .account_routes import router as accounts
from .news.routes import router as news
from .briefing.routes import router as briefings


class JsonLog(logging.Formatter):
    def format(self, record):
        return json.dumps(
            {
                "time": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "event": record.getMessage(),
                **{
                    k: getattr(record, k)
                    for k in ("stage", "error_type")
                    if hasattr(record, k)
                },
            }
        )


handler = logging.StreamHandler()
handler.setFormatter(JsonLog())
logger = logging.getLogger("sourcera")
logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False
load_models()


async def local_timer():
    from .jobs import tick

    while True:
        await asyncio.sleep(5)
        try:
            await asyncio.to_thread(tick.run)
        except Exception as exc:
            logger.warning(
                "local_scheduler_error", extra={"error_type": type(exc).__name__}
            )


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(local_timer()) if settings.job_mode == "local" else None
    yield
    if task:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


app = FastAPI(title="Sourcera", version="1.0.0", lifespan=lifespan)
prefix = "/api/v1"


def error(code, message, status):
    return JSONResponse(
        {"error": {"code": code, "message": message}, "detail": message},
        status_code=status,
    )


@app.exception_handler(RequestValidationError)
async def validation(request, exc):
    fields = [str(err["loc"][-1]) for err in exc.errors()]
    return error("validation", "Invalid request fields: " + ", ".join(fields), 422)


from starlette.exceptions import HTTPException as StarletteHTTPException


@app.exception_handler(StarletteHTTPException)
async def http_error(request, exc):
    response = error("http_" + str(exc.status_code), str(exc.detail), exc.status_code)
    if exc.headers:
        response.headers.update(exc.headers)
    return response


@app.exception_handler(Exception)
async def internal_error(request, exc):
    logger.error("request_failed", extra={"error_type": type(exc).__name__})
    return error("internal_error", "The request could not be completed.", 500)


class RequestLimits:
    def __init__(self, app):
        self.app = app
        self.windows = defaultdict(deque)
        self.cache = None
        self.cleaned = 0

    def local_limit(self, host):
        now = monotonic()
        if now - self.cleaned > 60:
            self.windows = defaultdict(
                deque, {k: v for k, v in self.windows.items() if v and v[-1] > now - 60}
            )
            self.cleaned = now
        window = self.windows[host]
        while window and window[0] <= now - 60:
            window.popleft()
        if len(window) >= settings.rate_per_minute:
            return False
        window.append(now)
        return True

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        spoken = (
            scope["method"] == "GET"
            and "/conversations/" in scope["path"]
            and scope["path"].endswith("/audio")
        )
        if scope["method"] not in ("POST", "PUT", "PATCH") and not spoken:
            return await self.app(scope, receive, send)

        async def reject(code, msg, status):
            await error(code, msg, status)(scope, receive, send)

        if scope["method"] == "POST" or spoken:
            host = scope.get("client", ("local",))[0]
            if settings.job_mode == "celery":
                from redis.asyncio import Redis

                if self.cache is None:
                    self.cache = Redis.from_url(settings.redis_url, socket_timeout=2)
                # Atomic expiry prevents counters surviving the minute after a worker crash.
                try:
                    count = await self.cache.eval(
                        "local n=redis.call('INCR', KEYS[1]); if n==1 then redis.call('EXPIRE', KEYS[1],60) end; return n",
                        1,
                        "rate:" + host,
                    )
                except Exception:
                    return await reject(
                        "temporarily_unavailable",
                        "Request limiter is unavailable.",
                        503,
                    )
                allowed = count <= settings.rate_per_minute
            else:
                allowed = self.local_limit(host)
            if not allowed:
                return await reject("rate_limit", "Please retry in a minute.", 429)
        if spoken:
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > settings.request_limit:
                return await reject(
                    "request_too_large", "Request exceeds upload limit.", 413
                )
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        sent = False

        async def replay():
            nonlocal sent
            if sent:
                return await receive()
            sent = True
            return {
                "type": "http.request",
                "body": b"".join(chunks),
                "more_body": False,
            }

        await self.app(scope, replay, send)


app.add_middleware(RequestLimits)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Range"],
)


@app.get(prefix + "/health")
def health():
    return {"status": "ok", "service": "sourcera", "demo_mode": settings.demo_mode}


@app.get(prefix + "/ready")
def ready():
    try:
        with SessionLocal() as db:
            db.execute(text("select version_num from alembic_version")).scalar_one()
            if settings.demo_mode and settings.job_mode == "celery":
                from .news.models import IngestionJob
                from sqlalchemy import select

                seeded = db.scalar(
                    select(IngestionJob.id)
                    .where(
                        IngestionJob.kind == "fixture",
                        IngestionJob.status == "completed",
                    )
                    .limit(1)
                )
                if not seeded:
                    raise RuntimeError("Demo ingestion in progress")
        if settings.job_mode == "celery":
            import redis
            from .messaging import connection

            redis.Redis.from_url(
                settings.redis_url, socket_connect_timeout=2, socket_timeout=2
            ).ping()
            with connection() as broker:
                broker.connect()
        if os.getenv("AUDIO_STORAGE") == "minio":
            from .briefing.voice import _bucket

            client, bucket = _bucket()
            client.head_bucket(Bucket=bucket)
    except Exception as exc:
        logger.warning("readiness_failed", extra={"error_type": type(exc).__name__})
        raise HTTPException(503, "A required service is unavailable")
    return {"status": "ready", "jobs": settings.job_mode}


for router in (accounts, briefings, news):
    app.include_router(router, prefix=prefix)
