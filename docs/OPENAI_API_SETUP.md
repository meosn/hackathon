# Connect hackathon OpenAI credits

The project already supports OpenAI-compatible Chat Completions for evidence-grounded briefing text and OpenAI Whisper for speech recognition. No frontend API key or new SDK is required.

## 1. Activate credits and create a key

1. In the OpenAI Platform, check **Billing > Overview** to verify that credits are available to the organization/project.
2. Under **API keys**, create a **project-scoped secret key** for the project using those credits.
3. Never add the key to a GitHub commit, issue, chat, frontend `VITE_*` variable, or screenshot. If leaked, revoke it and create a replacement.

OpenAI trial credits belong to the billed OpenAI organization, not to an individual API key. A new key in the same billed organization can use its available credits. They do not transfer to another organization's balance.

## 2. Configure Sourcera

**Recommended:** On the machine running Docker Compose, run `python3 scripts/configure_openai.py` and paste your *newly rotated* API key into the hidden prompt. The helper updates the local, ignored `.env`, retains other settings, and never prints the secret. Then proceed to step 3.

**Alternatively, configure manually:** From the repository root, copy the template only if you have not already configured your local environment:

```bash
cp .env.example .env
```

Edit these values **in the local, gitignored root `.env`** (replace the placeholder with your actual newly created key):

```dotenv
LLM_PROVIDER=api
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-proj-REPLACE_LOCALLY
STT_PROVIDER=whisper
STT_BASE_URL=https://api.openai.com/v1
STT_MODEL=whisper-1
# STT_API_KEY is optional: when empty, the backend reuses LLM_API_KEY.
STT_API_KEY=
```

Leave `TTS_PROVIDER=local` for offline synthesized narration, or configure ElevenLabs separately if you have its own key and authorized voices. OpenAI credits do **not** cover ElevenLabs. In the current backend, OpenAI text generation and speech transcription are supported, but OpenAI text-to-speech is **not** implemented.

The root `.env` is already gitignored and supplied to the backend API and workers through Docker Compose. **Never put `LLM_API_KEY` into `frontend/.env` or frontend code.**

## 3. Run / restart

```bash
./scripts/compose.sh up -d
```

For a brand-new install, build/start the stack per the README:

```bash
docker compose up --build -d
```

Open http://localhost:5173. Generate a new briefing to exercise the configured LLM; for speech transcription, allow microphone access on localhost or HTTPS. A cached or already-prepared briefing may not invoke the model again.

## 4. Verify without exposing secrets

- Inspect the **OpenAI Platform > Usage** page to confirm requests and token usage for your project.
- Check application logs for provider errors, but do not print or paste environment variables.
- If you see `401`, check key/organization; if `429`, check rate limits and available credits.
- For OpenAI structured-output errors, verify that the selected model supports the JSON schema request. The current provider adapter sends `response_format: json_schema` to `/chat/completions`.
- The API spending cap and usage dashboard are maintained in the OpenAI Platform; the project's cost ledger is an estimate, not a hard spending limit. Set appropriate limits in OpenAI and monitor the remaining trial balance and its expiration date.

## Relevant code

- `backend/app/briefing/providers.py`: `LLM_PROVIDER=api`, `LLM_MODEL`, `LLM_API_KEY`, and the Chat Completions request.
- `backend/app/briefing/voice.py`: `STT_PROVIDER=whisper`, `STT_API_KEY` or the fallback `LLM_API_KEY`.
- `docker-compose.yml`: root `.env` loaded by backend services.
- `docs/VOICE_PIPELINE.md`: speech and conversation setup.

For a shared deployment, store the key as a server-side secret and give only authorized teammates access to the deployment, rather than sharing the secret itself.
