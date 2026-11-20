"""Keep observations of external calls even when a later evidence gate rolls back."""

from contextlib import contextmanager

from app.usage import ModelUsage, record

_KEY = "sourcera_provider_observations"


@contextmanager
def account_attempts(db):
    if _KEY in db.info:
        yield
        return
    observations = []
    db.info[_KEY] = observations
    try:
        yield
    except Exception:
        if observations:
            # Roll back the failed application operation before replaying only its usage rows.
            db.rollback()
            for observation_id, stage, model, kwargs in observations:
                if not db.get(ModelUsage, observation_id):
                    record(db, stage, model, **kwargs)
            db.commit()
        raise
    finally:
        db.info.pop(_KEY, None)


def observe(db, stage, model, **kwargs):
    row_id = record(db, stage, model, **kwargs)
    if _KEY in db.info:
        db.info[_KEY].append((row_id, stage, model, kwargs))
