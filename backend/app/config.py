"""Process configuration. Containers share the signing key through the state volume."""

import os
import secrets
from pathlib import Path
from urllib.parse import quote


def enabled(name, default=False):
    return os.getenv(name, str(int(default))).lower() in {"true", "1", "yes"}


class Settings:
    database_url = os.getenv("DATABASE_URL") or (
        "postgresql+psycopg://sourcera:"
        + quote(os.environ["POSTGRES_PASSWORD"], safe="")
        + "@postgres/sourcera"
        if os.getenv("JOB_MODE") == "celery"
        else "sqlite:///./sourcera.db"
    )
    broker_url = os.getenv("BROKER_URL") or (
        "amqp://sourcera:"
        + quote(os.environ["RABBITMQ_PASSWORD"], safe="")
        + "@rabbitmq:5672//"
        if os.getenv("JOB_MODE") == "celery"
        else "amqp://localhost"
    )
    redis_url = os.getenv("REDIS_URL", "redis://localhost/0")
    job_mode = os.getenv("JOB_MODE", "local")
    demo_mode = enabled("DEMO_MODE", True)
    state_dir = Path(os.getenv("STATE_DIR", ".local"))
    cors_origins = os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    request_limit = int(os.getenv("MAX_REQUEST_BYTES", "12582912"))
    token_hours = int(os.getenv("TOKEN_HOURS", "12"))
    rate_per_minute = int(os.getenv("RATE_PER_MINUTE", "40"))


settings = Settings()


def signing_key():
    supplied = os.getenv("JWT_SECRET")
    if supplied:
        if len(supplied) < 32:
            raise ValueError("JWT_SECRET requires at least 32 characters")
        return supplied
    settings.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = settings.state_dir / "session.key"
    if not path.exists():
        # Publish a complete key atomically even if several services start together.
        from tempfile import NamedTemporaryFile

        with NamedTemporaryFile(dir=path.parent, delete=False) as temp:
            temp.write(secrets.token_hex(32).encode())
        try:
            os.link(temp.name, path)
        except FileExistsError:
            pass
        finally:
            os.unlink(temp.name)
    return path.read_text().strip()
