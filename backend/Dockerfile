FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg espeak-ng && rm -rf /var/lib/apt/lists/*
ARG BACKEND_EXTRAS=""
COPY pyproject.toml .
COPY app/__init__.py app/__init__.py
RUN pip install --no-cache-dir ".${BACKEND_EXTRAS}"
COPY app app
COPY alembic alembic
COPY alembic.ini .
RUN useradd --system --uid 10001 --create-home sourcera && mkdir -p /state && chown sourcera /state
USER sourcera
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--no-access-log"]
