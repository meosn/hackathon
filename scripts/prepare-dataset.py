"""Split a supplied Newstex archive into bounded, private JSONL import files."""

import argparse
import json
import os
from pathlib import Path
import zipfile


def write_batch(folder, stem, index, lines):
    path = folder / f"{stem}-{index:03d}.jsonl"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.writelines(lines)
    return path.name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, default=Path("datasets"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    filenames, count, latest = [], 0, ""
    with zipfile.ZipFile(args.archive) as archive:
        for name in archive.namelist():
            if not name.endswith(".jsonl") or name.startswith("__MACOSX/"):
                continue
            batch, size, index = [], 0, 0
            with archive.open(name) as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    latest = max(latest, row["date"])
                    batch.append(line)
                    size += len(line)
                    count += 1
                    if size >= 8 * 1024 * 1024:
                        filenames.append(
                            write_batch(args.output, Path(name).stem, index, batch)
                        )
                        index += 1
                        batch, size = [], 0
            if batch:
                filenames.append(
                    write_batch(args.output, Path(name).stem, index, batch)
                )
    print(json.dumps({"records": count, "files": filenames, "reference_time": latest}))


if __name__ == "__main__":
    main()
