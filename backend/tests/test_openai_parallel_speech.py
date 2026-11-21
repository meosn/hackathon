import threading
from types import SimpleNamespace
import pytest
from app.briefing import voice
from test_listener_workflow import session


def test_parallel_speech_keeps_segment_order_boundaries_and_main_thread_accounting(session, monkeypatch):
    monkeypatch.setenv('OPENAI_TTS_CONCURRENCY', '3')
    barrier = threading.Barrier(3)
    main_thread = threading.get_ident()
    observations = []
    original = voice.observe

    def observe(db, *args, **kwargs):
        assert threading.get_ident() == main_thread
        observations.append(kwargs['characters'])
        return original(db, *args, **kwargs)

    def speech(text, language, profile, config):
        assert threading.get_ident() != main_thread
        barrier.wait(timeout=3)
        return bytes([int(text), 0]) * (voice.RATE * int(text))

    monkeypatch.setattr(voice, '_segment_pcm', speech)
    monkeypatch.setattr(voice, 'observe', observe)
    segments = [SimpleNamespace(text=str(i), language='en') for i in (1, 2, 3)]
    config = ('openai', 'gpt-4o-mini-tts', 'marin')
    audio = voice._render_audio(session, segments, 'professional', 'parallel', config)
    assert audio.boundaries == [[0, 1.2], [1.2, 3.4], [3.4, 6.6]]
    assert observations == [1, 1, 1]
    # A second request must use the completed cache without more provider calls.
    assert voice._render_audio(session, segments, 'professional', 'again', config).id == audio.id
    assert len(observations) == 3


def test_parallel_speech_stops_new_requests_after_failure(monkeypatch):
    monkeypatch.setenv('OPENAI_TTS_CONCURRENCY', '1')
    calls, observations = [], []

    def failed(text, *args):
        calls.append(text)
        raise ValueError('provider refused speech')

    monkeypatch.setattr(voice, '_segment_pcm', failed)
    monkeypatch.setattr(voice, 'observe', lambda *args, **kwargs: observations.append(kwargs))
    with pytest.raises(ValueError, match='provider refused speech'):
        voice.openai_parts(None, [('one', 'en'), ('two', 'en')], 'professional', ('openai', 'tts', 'marin'), 'failed')
    assert calls == ['one']
    assert len(observations) == 1
