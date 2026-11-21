"""Server-only credential rotation for ElevenLabs speech requests."""

import hashlib
import os
from threading import Lock
from time import monotonic

import httpx

_lock = Lock()
_counters = {}
_cooldowns = {}


def keys():
    values = [os.getenv("ELEVENLABS_API_KEY", "")]
    values.extend(os.getenv("ELEVENLABS_API_KEYS", "").split(","))
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def _cache():
    if not os.getenv("REDIS_URL"):
        return None
    import redis

    return redis.Redis.from_url(
        os.environ["REDIS_URL"], socket_connect_timeout=0.3, socket_timeout=0.3
    )


def _fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _ordered_keys(values):
    group = _fingerprint("\n".join(values))
    try:
        cache = _cache()
        if cache is None:
            raise ConnectionError
        offset = cache.incr("elevenlabs:rotation:" + group) - 1
        available = [key for key in values if not cache.exists("elevenlabs:cooldown:" + _fingerprint(key))]
    except Exception:
        # Redis outages must not stop speech. The fallback is thread-safe and
        # process-local; normal production rotation is shared across workers.
        with _lock:
            offset = _counters.get(group, 0)
            _counters[group] = offset + 1
            available = [key for key in values if _cooldowns.get(_fingerprint(key), 0) <= monotonic()]
    ordered = values[offset % len(values):] + values[:offset % len(values)]
    return [key for key in ordered if key in available] or ordered


def _cooldown(key, seconds):
    fingerprint = _fingerprint(key)
    with _lock:
        _cooldowns[fingerprint] = monotonic() + seconds
    try:
        cache = _cache()
        if cache is not None:
            cache.setex("elevenlabs:cooldown:" + fingerprint, seconds, "1")
    except Exception:
        pass


def post(url, **kwargs):
    values = keys()
    if not values:
        raise ValueError("ElevenLabs API key is not configured")
    headers = dict(kwargs.pop("headers", {}))
    for key in _ordered_keys(values) if len(values) > 1 else values:
        response = httpx.post(url, headers={**headers, "xi-api-key": key}, **kwargs)
        if response.is_success:
            return response
        try:
            detail = response.json().get("detail", {})
            status = detail.get("status") if isinstance(detail, dict) else None
        except (ValueError, AttributeError):
            status = None
        if response.status_code in {401, 402, 429} or status == "quota_exceeded":
            _cooldown(key, 30 if response.status_code == 429 else 300)
            continue
        # Private voices may exist only in one account. Do not disable a key
        # globally because it cannot access this particular voice.
        if response.status_code in {403, 404} or status == "voice_not_found":
            continue
        return response
    return response
