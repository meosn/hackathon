FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg espeak-ng && rm -rf /var/lib/apt/lists/*
ARG BACKEND_EXTRAS=""
RUN case "$BACKEND_EXTRAS" in *ml*) pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu ;; esac
COPY pyproject.toml .
COPY app/__init__.py app/__init__.py
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --timeout 60 ".${BACKEND_EXTRAS}"
COPY app app
COPY alembic alembic
COPY alembic.ini .
RUN useradd --system --uid 10001 --create-home sourcera && mkdir -p /state /models && chown sourcera /state /models
USER sourcera
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--no-access-log"]
