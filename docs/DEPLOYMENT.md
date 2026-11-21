# Deployment and configuration

Use Docker Engine and Compose v2 or later. From the Sourcera directory run `cp .env.example .env` followed by `docker compose up --build -d`. The `bootstrap` service brings the database to Alembic head, declares RabbitMQ topology, creates the private audio bucket and seeds demo voices and stories. Its successful exited state is expected. Repeating bootstrap reuses the existing dataset. `./scripts/setup.sh` performs the same setup and supports a standalone `docker-compose` binary.

| Local service | URL or access |
|---|---|
| React | http://localhost:5173 |
| FastAPI and Swagger | http://localhost:8000/docs |
| Readiness | http://localhost:8000/api/v1/ready |
| RabbitMQ management | http://localhost:15672, username sourcera |
| MinIO console | http://localhost:9001, credentials from the operator environment |

RabbitMQ, PostgreSQL, Redis and the S3 API are internal services. Only the UI, API and two consoles publish loopback ports. The MinIO service uses a digest-pinned Bitnami Legacy community image. Review its maintenance status before deploying on a shared network. Production deployment also requires TLS termination, unique private credentials, trusted proxies, retention policy and network controls.

## Environment

The Compose environment file is ignored by Git. Configuration is read at process start. After changing it, run `./scripts/compose.sh up -d`. Rebuild after changing optional Python extras. Empty provider keys are expected for the local demo.

| Variables | Meaning |
|---|---|
| FRONTEND_PORT, API_PORT, RABBITMQ_MANAGEMENT_PORT, MINIO_CONSOLE_PORT | Host loopback port mappings |
| POSTGRES_PASSWORD, RABBITMQ_PASSWORD | Private database and broker credentials; development defaults are in the example |
| MINIO_ACCESS_KEY, MINIO_SECRET_KEY, MINIO_BUCKET | Private S3 credentials and audio bucket |
| JWT_SECRET, TOKEN_HOURS | HMAC signing key (32+ characters if specified) and token lifetime. An empty key creates a random mode-0600 file in the state volume |
| DEMO_MODE | Enables synthetic seed, demo login templates and aggregate dashboard access for demo users |
| CORS_ORIGINS | Comma-separated allowed frontend origins, used for HTTP and WebSocket origin validation |
| MAX_REQUEST_BYTES, RATE_PER_MINUTE | Upload ceiling and rate limit in a one-minute window |
| DATASET_DIR, DATASET_FILES | Mounted private directory and allowlisted input filenames |
| RSS_FEED_URLS, RSS_INTERVAL_MINUTES | Authorized HTTPS feed URLs and their polling interval |
| NEWS_SOURCES | Comma-separated live source IDs (bloomberg, dw, bbc, forex-factory), using the same polling interval |
| CONVERSATION_PROVIDER | `local` for the offline demo or `elevenagents` for signed voice WebSockets |
| ELEVENLABS_AGENT_ID, ELEVENLABS_API_KEY | Private ElevenAgents agent and its server-side API credential |
| ELEVENLABS_ALLOW_LICENSED_CONTEXT | Set to `1` only when authorized to send licensed records to the agent |
| NEWS_HTML_PARSER | beautifulsoup by default, or scrapling with the crawl extra |
| EMBEDDING_PROVIDER, EMBEDDING_MODEL, CLUSTER_SIMILARITY | local_hash or sentence_transformers, 384-dimensional semantic model and candidate similarity threshold |
| BACKEND_EXTRAS | Optional build extras, for example [ml,crawl]. The ML extra can materially increase image size |
| LLM_PROVIDER, LLM_BASE_URL, LLM_MODEL, LLM_API_KEY | mock, api or ollama; compatible service base URL, model and optional credential. The Ollama URL must be reachable from the container |
| TTS_PROVIDER, TTS_LOCAL_FALLBACK | local or elevenlabs; 1 enables local speech fallback after an eligible provider error |
| ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, ELEVENLABS_VOICE_MAP, ELEVENLABS_MODEL | Operator-authorized voices, optional per-style JSON object and synthesis model |
| STT_PROVIDER, STT_BASE_URL, STT_API_KEY, STT_MODEL | mock or whisper; compatible API base, credential and model. The mock accepts a text transcript |
| RANK_WEIGHTS | JSON object of named weights overriding the documented defaults |
| LLM_INPUT_USD_PER_M, LLM_OUTPUT_USD_PER_M, TTS_USD_PER_M_CHARS | Operator-supplied estimates per million units. Set these for paid providers |
| COMPUTE_USD_PER_HOUR | Assumed hourly compute cost applied to observed stage time; defaults to USD 0.04 |
| DATABASE_URL, BROKER_URL, REDIS_URL | Explicit service connection URLs when running outside the supplied Compose network |
| STATE_DIR, JOB_MODE, AUDIO_STORAGE, MINIO_ENDPOINT, AUDIO_DIR | Private key/Beat state directory, local or celery execution, local or minio storage, internal S3 URL and local audio directory |
| API_PROXY_TARGET | Vite proxy target including scheme and port |
| PLAYWRIGHT_BASE_URL, PLAYWRIGHT_CHANNEL | Target URL and installed browser channel for browser integration tests |

## Authorized data

Use a dedicated copy inside `datasets/` and specify its filename in `DATASET_FILES`. Disable demo mode on a fresh deployment if the licensed corpus should be the only input. The adapter accepts normalized JSON, JSONL or NDJSON up to 15 MiB per file. See AI_PIPELINE.md for field aliases. Place larger data in several allowlisted files. After reloading the configuration, submit `./scripts/compose.sh exec api python -m app.cli ingest export.jsonl`. This goes through the same workers as the operator-only HTTP endpoint.

To grant operations access, register an account, then run `./scripts/compose.sh exec api python -m app.cli grant-admin your-address@example.org` from the host. The command only accepts an existing registered account. No default administrator password is shared with demo users.

For shutdown with data retained, run `./scripts/compose.sh down`. At license expiry run `./scripts/cleanup.sh --confirm`. The command removes this Compose project's volumes (users, stories, derived evidence and scripts, audio, queues, state) and the dedicated input directory. Delete original exports, off-host copies and backups separately under the applicable agreement. The backend image's build context contains application source and the synthetic fixture only. Never put licensed files in source, frontend/public or container build contexts.

## Local process profile

### Dated Newstex archives and provider configuration

`NEWS_REFERENCE_TIME` is an optional ISO-8601 archive timestamp. `ACTIVE_CORPUS=licensed` limits new recommendations and story browsing to imported articles. `NEWS_EDITION_VERSION` distinguishes prepared daily recordings across corpus changes. Existing listening records remain available in history.

`DAILY_NEWS_PERIOD` defaults to `day`. Daily editions select three stories from that period. Archive deployments retain actual source dates and use their disclosed reference timestamp. `ANALYSIS_BATCH_SIZE` defaults to ten articles on PostgreSQL. Completed batches commit their valid evidence and progress atomically, allowing interrupted imports to resume. The analysis worker uses a thirty-minute graceful shutdown window during deployment.

`FACT_EXTRACTION_PROVIDER=hybrid` adds structured extraction for articles with sparse rule-derived evidence. Returned quotations must match exact private source spans. `CLUSTER_LLM_VERIFY=1` enables model review for uncertain event candidates above `CLUSTER_REVIEW_SIMILARITY`, which defaults to 0.78. `LLM_TIMEOUT_SECONDS` defaults to 180. `CRAWL_URLS` allowlists exact HTTPS article URLs for operator-submitted crawl jobs. The crawler requires explicit publication metadata and identifiable article content.

`STT_USD_PER_MINUTE` prices decoded audio duration. LLM and TTS prices use the existing per-million environment variables. These values are operator estimates. Vendor invoices require separate reconciliation.

The container frontend serves a production build through Nginx. The backend remains private behind its configured loopback port. A host reverse proxy must preserve WebSocket upgrade headers and permit audio uploads up to 12 MiB.

For an offline local-to-Compose migration, stop the old API and mount its dedicated data directory read-only into a one-off backend container. Set `PYTHONPATH=/app` for the script process and mount `scripts/` read-only at `/ops`. Run `/ops/migrate-local-state.py` with `--database` and `--audio`. The command migrates schema, copies records transactionally into an empty destination and uploads referenced audio to MinIO. It preserves account IDs and password hashes. Reuse the signing secret to preserve valid sessions. Start Compose and verify readiness before changing the host proxy.

Run `./scripts/local-demo.sh` with Python 3.12+, npm and Node 20.19+/22.12+. Linux requires eSpeak NG and FFmpeg. The macOS Python dependency supplies offline eSpeak NG. The script uses the same API and frontend and stores local demo data under `.local/demo/`. Compose is used for multi-process validation.

## Public QR address

The listening room is served at `https://qr.me/PJUMDW`. Build with `npm run build -- --base=/PJUMDW/` in `frontend/`, then copy dist contents to `/opt/sourcera/qr-public/PJUMDW/`. Include `deploy/nginx/sourcera-qr.conf` in the `qr.me` HTTPS server and remove the old exact-match `/PJUMDW` redirect. Run `nginx -t` before reloading; preserve other QR site locations.

Add `https://qr.me` to `CORS_ORIGINS` and the Google OAuth client's Authorized JavaScript origins if Google sign-in is enabled. The router, API, WebSockets, microphone worklet, manifest and notification worker support the prefix. A default frontend build still supports the original hostname's root path.
