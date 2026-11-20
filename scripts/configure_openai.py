#!/usr/bin/env python3
"""Configure Sourcera's existing OpenAI text and Whisper providers locally.

Run this script on the machine that runs Docker Compose. Never commit .env.
"""

from getpass import getpass
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
TEMPLATE = ROOT / ".env.example"

PUBLIC_SETTINGS = {
    "LLM_PROVIDER": "api",
    "LLM_BASE_URL": "https://api.openai.com/v1",
    "LLM_MODEL": "gpt-4o-mini",
    "STT_PROVIDER": "whisper",
    "STT_BASE_URL": "https://api.openai.com/v1",
    "STT_MODEL": "whisper-1",
    "STT_API_KEY": "",  # Existing backend falls back to LLM_API_KEY.
}


def main():
    if ENV.is_symlink():
        raise SystemExit("Refusing to replace a symlinked .env file.")
    if not TEMPLATE.is_file():
        raise SystemExit("Run this from a Sourcera checkout with .env.example.")

    print("Use a newly rotated OpenAI API key (never the one shared in chat).")
    key = getpass("New OpenAI API key (hidden input): ").strip()
    if not key.startswith("sk-") or len(key) < 20 or any(ch.isspace() for ch in key):
        raise SystemExit("Invalid API-key format; no file was changed.")

    existing = ENV.read_text(encoding="utf-8") if ENV.exists() else TEMPLATE.read_text(encoding="utf-8")
    settings = {**PUBLIC_SETTINGS, "LLM_API_KEY": key}
    found = set()
    updated = []
    for line in existing.splitlines(keepends=True):
        label = line.partition("=")[0].strip()
        if not line.lstrip().startswith("#") and label in settings:
            updated.append(f"{label}={settings[label]}\n")
            found.add(label)
        else:
            updated.append(line)
    if updated and not updated[-1].endswith("\n"):
        updated.append("\n")
    for name, value in settings.items():
        if name not in found:
            updated.append(f"{name}={value}\n")

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=ROOT, prefix=".openai-env-", delete=False
        ) as handle:
            temp_path = Path(handle.name)
            os.chmod(temp_path, 0o600)
            handle.writelines(updated)
        os.replace(temp_path, ENV)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    print("Configured backend GPT + Whisper in local .env; API key not printed.")
    print("Apply settings with: ./scripts/compose.sh up -d")
    print("Speech synthesis still uses local TTS unless ElevenLabs is configured separately.")


if __name__ == "__main__":
    main()
