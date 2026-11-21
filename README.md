# Sourcera
### The Liquid Briefing · MAIN AI Hackathon 2026

Personalized audio news with a prepared daily briefing and an interruptible voice conversation.

Press **Play** to hear today's saved edition. Ask a question while listening to pause the recording and receive a spoken, source-grounded answer. Say **continue** to return to the briefing. Choose a different narrator or open the prepared weekly edition from the episode library. Detailed preferences and model selection live in **Settings**.

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

Open [localhost:5173](http://localhost:5173), register a personal account and choose your interests in Settings. Public demo profiles and automatic guest sign-in have been removed. `DEMO_MODE=false` is the default; the legacy demo API and synthetic seeding are available only to explicitly configured development/test environments. First startup applies database migrations. Configure live feeds or import an authorized dataset before preparing audio.

| Service | Local address |
|---|---|
| React application | http://localhost:5173 |
| FastAPI documentation | http://localhost:8000/docs |
| API readiness | http://localhost:8000/api/v1/ready |
| RabbitMQ management | http://localhost:15672 |
| MinIO console | http://localhost:9001 |

The example environment uses local speech and deterministic AI adapters for local development. Host ports and credentials are configurable in `.env`.

## ElevenAgents voice conversations

Enable a private ElevenLabs agent for live voice conversations by setting these values in `.env`:

```dotenv
CONVERSATION_PROVIDER=elevenagents
ELEVENLABS_AGENT_ID=your_agent_id
ELEVENLABS_API_KEY=your_elevenlabs_api_key
```

Configure the agent's prompt, voice and language using the [ElevenAgents setup guide](docs/VOICE_PIPELINE.md#elevenagents-speech-to-speech). Rebuild and apply the settings with `./scripts/compose.sh up --build -d`. **Voice chat** opens a signed WebSocket to ElevenLabs. Sourcera provides the current episode, playhead and source evidence, or the selected story in Ask Sourcera. ElevenLabs processes the microphone stream and speaks the answer in the same session. The prepared briefing remains available for playback, and text questions remain available in Ask Sourcera.

The checkout defaults to `CONVERSATION_PROVIDER=local` for the offline demo. The prepared narration voice has its own setting and remains independent of the voice selected in the ElevenAgents dashboard.

### Prepared narration and text answers

Set `LLM_PROVIDER=api`, `LLM_MODEL` and `LLM_API_KEY` to enable generated conversation answers and rewritten narration. `LLM_BASE_URL` supports compatible APIs. `LLM_PROVIDER=ollama` selects a reachable Ollama service. Conversation generation receives the current story, preferences, recent messages and retrieved claims. Each answer sentence cites one stored claim and passes source checks. Failed generation returns source search results with an explicit fallback indicator.

`EMBEDDING_PROVIDER=sentence_transformers` and `BACKEND_EXTRAS=[ml,crawl]` enable multilingual neural embeddings and Scrapling. Models are cached in a private Compose volume. Optional `CLUSTER_LLM_VERIFY=1` reviews uncertain semantic event matches. `FACT_EXTRACTION_PROVIDER=hybrid` recovers short exact evidence quotations when cheap extraction finds fewer than three claims.

For hosted narration, edit these entries in your local `.env`:

```dotenv
TTS_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=your_elevenlabs_api_key
ELEVENLABS_VOICE_ID=your_permitted_voice_id
ELEVENLABS_MODEL=eleven_multilingual_v2
TTS_LOCAL_FALLBACK=0
```

Use a voice available to your ElevenLabs account. `ELEVENLABS_VOICE_MAP` can map the application styles `professional`, `energetic`, `casual`, `jarvis` and `cyberpunk` to different permitted voice IDs. Hosted synthesis consumes the account's API allowance. Apply configuration changes with:

```bash
./scripts/compose.sh up -d
```

## Daily editions and personalization

Daily and weekly editions are prepared proactively for the listener's current content settings and chosen narrator. New listeners receive a default 06:00 preparation schedule in their profile time zone when they have no schedule. Settings → Daily routine provides daily, twice-daily, weekday, weekly and custom plans. Each selected day can have its own delivery times; the time zone uses a short GMT-offset list, and hours (00–23) and minutes (00–59) have separate dropdowns. GMT offsets stay fixed; saved regional zones remain compatible. The scheduler creates a distinct three-story edition for each slot and avoids repeating it during daylight-saving clock changes. Scheduled editions appear in the briefing library. Existing plans can be edited or disabled.

Daily editions select the three highest-ranked eligible stories. Choose **More news** to hear additional stories without repeating the original selection. Follow-up questions can request more detail about a story. Dated archives display their reference date in the listening room.

The recording is downloaded before Play is enabled. Pressing Play uses the buffered audio. Selecting a voice previews it and saves the preference; narration is prepared in the background using the existing approved script where possible. Daily and weekly editions are queued on entry and after applying settings. Weekly covers are enabled after the recording is ready and buffered.

Private prepared templates can reuse approved narration for matching preferences while each listener keeps separate edition records and conversation history. A new preference set requires an initial preparation. The production scheduler polls the configured RSS sources every 15 minutes independently of demo mode.

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

The challenge ZIP can be prepared with `python3 scripts/prepare-dataset.py /path/to/archive.zip`. This validates JSON and splits large feeds into bounded private files. Use its printed filenames for `DATASET_FILES`, then run `./scripts/compose.sh exec api python -m app.cli ingest-all`. The importer maps Newstex publication, author, source permalink and article ID explicitly.

For a dated archive, set `NEWS_REFERENCE_TIME` to its latest publication timestamp and `ACTIVE_CORPUS=licensed`. Date filters use this reference and the interface displays the archive date. `NEWS_EDITION_VERSION` creates a new daily baseline when switching corpora. Public licensed-story views expose limited short quotations and source links. Original article text stays in private storage.

The hackathon dataset remains subject to its authorized usage period. At expiry, the following command deletes this deployment's data volumes, generated audio, derived records and dedicated input directory:

```bash
./scripts/cleanup.sh --confirm
```

Original exports and separately held backups require cleanup under the applicable agreement.

### Live sources

Set `NEWS_SOURCES=bloomberg,dw,bbc,forex-factory` in `.env` to enable all four sources, or list just the ones you want. Run `./scripts/compose.sh up --build -d` to build and start the updated services. The worker imports them every `RSS_INTERVAL_MINUTES` (60 by default). Bloomberg Markets, DW English and BBC Business use RSS. Forex Factory reads Latest Stories and Hot Stories from its public news page, using the card excerpt when available and the headline otherwise. Its timestamps without a zone are treated as UTC. If the site refuses the request, the import job follows the worker's regular retry policy.

For live world and technology coverage, use `NEWS_SOURCES=bbc-world,bbc-technology,dw,dw-de,nos-nl,guardian-world,aljazeera`, `RSS_INTERVAL_MINUTES=15`, `RSS_MAX_ARTICLES=12`, `RSS_MAX_AGE_HOURS=48` and `NEWS_ENRICH_FEEDS=1`. The German DW and Dutch NOS feeds supply original reporting for those narration languages. Language and section feeds from the same broadcaster share one publisher identity. Known publishers' publicly served article paragraphs can supplement the short RSS summaries; unavailable or restricted pages fall back to their feed excerpts. Fetches are bounded and redirects to other hosts are rejected. `NEWS_LLM_MODEL` optionally selects a separate fast ingestion/comparison model. After ingestion and analysis complete, set `ACTIVE_CORPUS=live`, clear `NEWS_REFERENCE_TIME` and give `NEWS_EDITION_VERSION` a new value to switch prepared editions. Live ranking uses publication times from public-feed articles, excludes fixtures and archive-only events, and leaves historical episodes accessible. Inspect ingestion status and source comparisons before switching an existing archive deployment.

To request an immediate import for an enabled source:

```bash
./scripts/compose.sh exec api python -m app.cli ingest-source bbc
```

If the Forex Factory request is blocked, save the news page as HTML from a browser that can open it. Import the snapshot with the date, time and UTC offset displayed by Forex Factory at capture so both absolute and relative dates are interpreted correctly:

```bash
./scripts/compose.sh exec -T api python -m app.cli ingest-forex-html \
  --captured-at 2026-11-20T21:58:00+02:00 < forex-factory.html
```

To add another RSS or Atom source, append its direct HTTPS feed URL to the comma-separated `RSS_FEED_URLS` setting. Import jobs run independently per source and feed through the existing article, clustering and evidence pipeline.

## Architecture

| Area | Implementation |
|---|---|
| Frontend | React 19, TypeScript, Vite, Tailwind, React Router, TanStack Query, Zustand |
| API and data | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL and pgvector |
| Background processing | Separate ingestion, analysis, briefing and voice workers using Celery, RabbitMQ and Celery Beat |
| Cache and storage | Redis and MinIO, with authenticated audio retrieval through the API |
| AI and voice | ElevenAgents conversational WebSocket SDK, structured model adapters, evidence gates and separate episode narration |
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

## Challenge acceptance

See [the criterion-by-criterion audit](docs/HACKATHON_READINESS.md) for implemented behavior, verified archive processing, costs and remaining acceptance requirements.

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
