import httpx
import pytest

from app.briefing import eleven_keys

URL = 'https://api.elevenlabs.io/v1/text-to-speech/public-voice'


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setenv('ELEVENLABS_API_KEY', 'first')
    monkeypatch.setenv('ELEVENLABS_API_KEYS', 'second')
    monkeypatch.delenv('REDIS_URL', raising=False)
    eleven_keys._counters.clear()
    eleven_keys._cooldowns.clear()


def response(code=200, status=None):
    return httpx.Response(code, request=httpx.Request('POST', URL),
                          json={'detail': {'status': status}})


def test_rotation_and_deduplication(monkeypatch):
    monkeypatch.setenv('ELEVENLABS_API_KEYS', ' second, first, ,second ')
    seen = []
    def send(url, **kwargs):
        seen.append(kwargs['headers']['xi-api-key'])
        assert kwargs['json'] == {'text': 'Hello'}
        return response()
    monkeypatch.setattr(httpx, 'post', send)
    for _ in range(4):
        eleven_keys.post(URL, json={'text': 'Hello'}).raise_for_status()
    assert seen == ['first', 'second', 'first', 'second']


@pytest.mark.parametrize('code,status', [(401, None), (402, None), (429, None), (400, 'quota_exceeded')])
def test_failover_and_cooldown(monkeypatch, code, status):
    seen = []
    def send(url, **kwargs):
        key = kwargs['headers']['xi-api-key']
        seen.append(key)
        return response(code, status) if key == 'first' else response()
    monkeypatch.setattr(httpx, 'post', send)
    eleven_keys.post(URL).raise_for_status()
    eleven_keys.post(URL).raise_for_status()
    assert seen == ['first', 'second', 'second']


def test_private_voice_access_falls_back_without_disabling_key(monkeypatch):
    seen = []
    def send(url, **kwargs):
        key = kwargs['headers']['xi-api-key']
        seen.append(key)
        return response(404, 'voice_not_found') if key == 'first' else response()
    monkeypatch.setattr(httpx, 'post', send)
    eleven_keys.post(URL).raise_for_status()
    assert seen == ['first', 'second']
    assert not eleven_keys._cooldowns


def test_all_exhausted_returns_provider_error_and_does_not_loop(monkeypatch):
    seen = []
    def send(url, **kwargs):
        seen.append(kwargs['headers']['xi-api-key'])
        return response(401, 'quota_exceeded')
    monkeypatch.setattr(httpx, 'post', send)
    with pytest.raises(httpx.HTTPStatusError):
        eleven_keys.post(URL).raise_for_status()
    assert seen == ['first', 'second']


def test_invalid_request_and_network_failures_are_not_replayed(monkeypatch):
    seen = []
    def send(url, **kwargs):
        seen.append(kwargs['headers']['xi-api-key'])
        return response(422)
    monkeypatch.setattr(httpx, 'post', send)
    assert eleven_keys.post(URL).status_code == 422
    assert len(seen) == 1
    def offline(*args, **kwargs):
        raise httpx.ReadTimeout('uncertain provider completion')
    monkeypatch.setattr(httpx, 'post', offline)
    with pytest.raises(httpx.ReadTimeout):
        eleven_keys.post(URL)


def test_shared_counter_and_cooldown_across_process_state(monkeypatch):
    class Cache:
        counter = 0
        blocked = set()
        def incr(self, key):
            self.counter += 1
            return self.counter
        def exists(self, key):
            return key in self.blocked
        def setex(self, key, seconds, value):
            self.blocked.add(key)
    cache = Cache()
    monkeypatch.setattr(eleven_keys, '_cache', lambda: cache)
    assert eleven_keys._ordered_keys(['first', 'second']) == ['first', 'second']
    assert eleven_keys._ordered_keys(['first', 'second']) == ['second', 'first']
    eleven_keys._cooldown('first', 300)
    eleven_keys._cooldowns.clear()
    assert eleven_keys._ordered_keys(['first', 'second']) == ['second']


def test_redis_outage_and_single_key_compatibility(monkeypatch):
    def offline():
        raise ConnectionError('Redis unavailable')
    monkeypatch.setattr(eleven_keys, '_cache', offline)
    assert eleven_keys._ordered_keys(['first', 'second'])[0] == 'first'
    assert eleven_keys._ordered_keys(['first', 'second'])[0] == 'second'
    monkeypatch.delenv('ELEVENLABS_API_KEYS')
    monkeypatch.setattr(httpx, 'post', lambda url, **kwargs: response())
    assert eleven_keys.post(URL).status_code == 200
