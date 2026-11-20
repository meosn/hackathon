# Sourcera
### The Liquid Briefing · MAIN AI Hackathon 2026

Personalized audio news with a prepared daily briefing and an interruptible voice conversation.

Press **Play** to hear today's saved edition. Ask a question while listening to pause the recording and receive a spoken, source-grounded answer. Say **continue** to return to the briefing. Choose a different narrator or create a weekly edition from the episode library. Detailed preferences and model selection live in **Settings**.

## Quick start

Install Docker Engine with Compose, then run from the repository root:

```bash
cp .env.example .env
docker compose up --build -d
```

The setup wrapper creates the environment file and input directory automatically:

```bash
./scripts/setup.sh
```

Open [localhost:5173](http://localhost:5173) and select **Technology enthusiast** or **Financial analyst**. Registration also supports a new listener with arbitrary interests. First startup applies database migrations, imports synthetic news and prepares the demo editions in the background. Play becomes available after the recording has been prepared and buffered.

| Service | Local address |
|---|---|
| React application | http://localhost:5173 |
| FastAPI documentation | http://localhost:8000/docs |
| API readiness | http://localhost:8000/api/v1/ready |
| RabbitMQ management | http://localhost:15672 |
| MinIO console | http://localhost:9001 |

The example environment uses local speech and deterministic AI adapters, so the demo can run without external accounts. Host ports and credentials are configurable in `.env`.

## ElevenLabs speech and voice questions

For hosted narration and speech recognition, edit these entries in your local `.env`:

```dotenv
TTS_PROVIDER=elevenlabs
STT_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=your_elevenlabs_api_key
ELEVENLABS_VOICE_ID=your_permitted_voice_id
ELEVENLABS_MODEL=eleven_multilingual_v2
ELEVENLABS_STT_MODEL=scribe_v2
TTS_LOCAL_FALLBACK=0
```

Use a voice available to your ElevenLabs account. `ELEVENLABS_VOICE_MAP` can map the application styles `professional`, `energetic`, `casual`, `jarvis` and `cyberpunk` to different permitted voice IDs. Hosted synthesis and recognition consume the account's API allowance. Apply configuration changes with:

```bash
./scripts/compose.sh up -d
```

The microphone starts after Play and browser permission. It stays active while narration and answers play. Detected speech pauses playback and cancels stale responses. End the session or disable the microphone to release capture. Use localhost or HTTPS and a supported browser. Headphones help isolate the user's speech from speaker output.

Recognition, retrieval and synthesis run as asynchronous turns while microphone capture continues. In a recorded live check, a spoken answer was ready about 3.1 seconds after question submission. Provider and network latency varies.

## Daily editions and personalization

A listener's baseline edition is prepared once per local calendar day with the **Professional news** voice. New listeners receive a default 06:00 preparation schedule in their profile time zone when they have no schedule. Existing schedules can be edited or disabled.

The recording is downloaded before Play is enabled. Pressing Play uses the buffered audio. Selecting another voice saves the preference; **Create with this voice** generates a separate edition. Prepared weekly editions play from their cover. A missing weekly edition is presented as a creation action.

Two demo preference templates use different interests and languages. Their prepared audio can be reused while each listener keeps private edition records and conversation history. A new preference set requires an initial preparation.

## News, evidence and the demo dataset

The bundled corpus is explicitly synthetic. Its organizations, events, publications and example-domain URLs are invented.

| Fresh fixture import | Result |
|---|---:|
| Input records | 17 |
| Retained articles | 16 |
| Exact duplicate removed | 1 |
| Clustered events | 7 |
| Supported claims | 28 |
| Conflicting claims | 2 |

The pipeline cleans articles, removes exact duplicates, stores embeddings, applies guarded event clustering and extracts statements with exact source spans. Contradictory numerical reports remain visible. Every factual narration line passes a database-backed citation gate before publication. The transcript provides segment timing, source excerpts and article links. The supported label describes alignment with stored evidence.

The default embedding adapter uses deterministic multilingual lexical features. The `ml` extra enables Sentence Transformers. The `crawl` extra enables Scrapling. Model selection supports deterministic adapters, Ollama and a structured-output compatible API. See the pipeline and deployment guides for configuration and coverage limits.

For authorized Newstex files, place JSON, JSONL or NDJSON exports in the ignored `datasets/` directory and allowlist their filenames through `DATASET_FILES`. Then submit an import:

```bash
./scripts/compose.sh exec api python -m app.cli ingest export.jsonl
```

The hackathon dataset remains subject to its authorized usage period. At expiry, the following command deletes this deployment's data volumes, generated audio, derived records and dedicated input directory:

```bash
./scripts/cleanup.sh --confirm
```

Original exports and separately held backups require cleanup under the applicable agreement.

## Architecture

| Area | Implementation |
|---|---|
| Frontend | React 19, TypeScript, Vite, Tailwind, React Router, TanStack Query, Zustand |
| API and data | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL and pgvector |
| Background processing | Separate ingestion, analysis, briefing and voice workers using Celery, RabbitMQ and Celery Beat |
| Cache and storage | Redis and MinIO, with authenticated audio retrieval through the API |
| AI and voice | Structured model adapters, deterministic evidence gates, ElevenLabs, local eSpeak NG and configurable STT |
| Operations | Health checks, transactional event outbox, delivery receipts, bounded retries and usage accounting |

```text
backend/app/news/       Import, normalization, clustering and evidence
backend/app/briefing/   Daily editions, ranking, scripts, audio and discussion
backend/alembic/       Versioned database schema
frontend/src/          Listening room, settings, player, library and sources
shared/contracts/      Exported OpenAPI contract
scripts/               Setup, demo, validation and data cleanup
docs/                  Architecture, decisions and implementation details
```

## Development and tests

For a local Python and Node environment:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e './backend[test]'
cd frontend
npm ci
cd ..
make test
```

`make test` runs the backend tests, frontend tests and production frontend build. To run the lighter SQLite and local-audio demo, use `./scripts/local-demo.sh`. It installs the declared dependencies and starts the API and UI. Linux needs eSpeak NG and FFmpeg; macOS uses the packaged eSpeak NG library.

With the application running, execute the HTTP demo and browser checks:

```bash
python3 scripts/demo.py --third-profile
cd frontend
npx playwright install chromium
npm run test:e2e
```

For installed Google Chrome, use `PLAYWRIGHT_CHANNEL=chrome npm run test:e2e`.

| Executed verification | Result |
|---|---|
| Backend suite | 45 passed |
| Frontend unit and component tests | 9 passed |
| Browser scenarios | 3 passed |
| TypeScript and Vite production build | Passed |
| Fresh Docker volumes, migrations, RabbitMQ delivery and MinIO storage | Passed |
| Live ElevenLabs recognition and synthesis with a virtual microphone | Passed |

The checks include daily idempotence, profile differences, citation rejection, numeric conflicts, audio caching, interruption, playback, onboarding, settings and stable navigation. Physical microphone acoustics remain device-dependent. Full run details and provider scope are recorded in the validation guide.

Additional commands:

```bash
./scripts/verify-stack.sh
./scripts/test-compose.sh
make openapi
cd frontend && npm run api:types
```

## Documentation

- [Demo walkthrough](docs/DEMO_GUIDE.md) and [executed validation](docs/VALIDATION.md)
- [Architecture](docs/ARCHITECTURE.md), [database](docs/DATABASE.md) and [messaging](docs/MESSAGING.md)
- [News pipeline](docs/AI_PIPELINE.md), [fact verification](docs/FACT_VERIFICATION.md) and [personalization](docs/PERSONALIZATION.md)
- [Voice pipeline](docs/VOICE_PIPELINE.md), [API](docs/API.md) and [OpenAPI snapshot](shared/contracts/openapi.json)
- [Deployment and environment variables](docs/DEPLOYMENT.md), [cost analysis](docs/COST_ANALYSIS.md) and [decisions](docs/DECISIONS.md)

API keys, environment files, recordings, database state, dependency directories and licensed datasets are excluded from source control. The supplied Compose configuration exposes application and console ports on loopback for local demonstration.
