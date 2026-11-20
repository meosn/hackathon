"""Copy an offline local deployment into an empty configured PostgreSQL/MinIO stack."""

import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, func, select

from app.db import engine, load_models
from app.briefing.voice import _bucket, put_object


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    args = parser.parse_args()
    metadata = load_models()
    command.upgrade(Config("alembic.ini"), "head")
    client, bucket = _bucket()
    from botocore.exceptions import ClientError

    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        if exc.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
            raise
        client.create_bucket(Bucket=bucket)
    source = create_engine(f"sqlite:///file:{args.database.resolve()}?mode=ro&uri=true")
    total = 0
    with source.connect() as incoming, engine.begin() as outgoing:
        for table in metadata.sorted_tables:
            if outgoing.scalar(select(func.count()).select_from(table)):
                raise ValueError("Destination must be empty before migration")
        for table in metadata.sorted_tables:
            rows = [dict(row) for row in incoming.execute(select(table)).mappings()]
            if table.name == "generated_audio":
                for row in rows:
                    path = (args.audio / row["object_key"]).resolve()
                    if not path.is_relative_to(args.audio.resolve()):
                        raise ValueError("Audio key escapes the source directory")
                    put_object(row["object_key"], path.read_bytes())
            if rows:
                outgoing.execute(table.insert(), rows)
            total += len(rows)
            print(table.name, len(rows), flush=True)
    source.dispose()
    print("Migrated records", total)


if __name__ == "__main__":
    main()
