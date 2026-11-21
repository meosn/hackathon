# Executed validation

## Hosted Newstex deployment, 20 November 2026

The supplied challenge archive contained 1,740 records. All eight prepared import files completed through RabbitMQ/Celery. Exact deduplication retained 1,736 articles and removed four duplicates. The resulting active corpus contains 1,554 stories, 15,416 source-supported statements and 314 statements flagged as conflicting. Conflict markers describe the pipeline's source comparison results.

The hosted installation uses PostgreSQL/pgvector, Redis, RabbitMQ, Celery workers and Beat, MinIO, FastAPI and a production frontend served by Nginx. Migration preserved 835 existing records and their referenced audio. HTTPS remains configured on the separate Sourcera hostname. The existing qr.me site continued returning HTTP 200.

The combined backend suite passed 58 tests after integration with the live-source update. Nine frontend tests, three Chrome browser scenarios and the TypeScript/Vite build passed. Added checks cover Newstex field mapping, private licensed article text, generated-answer history and citation allowlists, unsupported numeric rewrites, safe source-wording recovery, resumable analysis batches, aligned batched speech, three-story daily editions and additional selections without repeated stories.

Live provider checks used GPT-4o mini and ElevenLabs with operator-supplied credentials. A virtual microphone in Chrome submitted a spoken question on the hosted site. Narration paused, Scribe transcribed the question, the API returned an answer with four citations and ElevenLabs speech played. Disabling the microphone released its media tracks. A separate unsupported-question check returned zero citations. Physical microphone acoustics require device testing.

Daily templates in English and German completed with three stories each. The affected existing listener's prepared edition was verified playing in Chrome. Two successive additional-news requests returned three new stories apiece, with no overlap with the daily edition or preceding selection. Licensed full article text remained inaccessible through the article API. Archive dates remain unchanged, and the UI discloses the latest publication timestamp of 19 November 2026.

Token, character and timing observations feed the cost ledger. Published unit prices produce estimates, and calls without sufficient billing information remain visibly unpriced. Historical validation entries below describe earlier configurations.

Validation date is 20 November 2026. The project was built in an isolated directory in the existing hackathon workspace. The application used synthetic input. Original source mirror files were read only.

| Check | Executed command or action | Result |
|---|---|---|
| Python behavior | `cd backend && ../.venv/bin/python -m pytest -q` | 41 tests passed |
| React behavior | `cd frontend && npm test` | Seven Vitest / React Testing Library tests passed |
| Frontend bundle | `cd frontend && npm run build` | TypeScript and Vite production build passed |
| Optional parser and semantic embedding | `NEWS_HTML_PARSER=scrapling EMBEDDING_PROVIDER=sentence_transformers EMBEDDING_MODEL=/tmp/sourcera-qa-multilingual-minilm HF_HUB_OFFLINE=1 ../.venv/bin/python -m pytest -q tests/test_news_pipeline.py tests/test_news_verification.py` from backend | 21 tests passed with actual downloaded multilingual MiniLM weights and Scrapling, five upstream lxml warnings |
| Compose startup | `DOCKER_CONTEXT=colima-sourcera-qa ./scripts/compose.sh up --build -d` | All eleven long-running services became healthy, initialization container exited successfully |
| Clean first run | `DOCKER_CONTEXT=colima-sourcera-qa ./scripts/test-compose.sh` | New PostgreSQL and storage volumes migrated and seeded through ingestion/analysis queues, two editions and a custom listener generated, receipts verified, temporary deployment removed |
| Browser on Compose | `cd frontend && PLAYWRIGHT_CHANNEL=chrome npm run test:e2e` | Two tests passed, desktop playback/source/chat and mobile registration/scheduling |
| Native local model | One selected synthetic claim via Ollama `llama3.1:8b` | Structured output passed evidence verification without provider fallback, local speech decoded successfully |
| Infrastructure inspection | `./scripts/compose.sh exec -T api python -m app.cli diagnostics --check-delivery` | Alembic 0001_initial, pgvector 0.8.7, HNSW index and durable consumer receipts confirmed |

## Fresh deployment observations

The first-run integration script uses its own Compose project and dynamically assigned loopback ports. It removed its temporary volumes after completing. One ingestion job and one analysis job reached done. Two briefing jobs and two voice jobs reached done. The receipt ledger contained news.analysis.completed, briefing.completed and voice.synthesis.completed. MinIO contained two generated audio objects. The main demo deployment stayed available at ports 5173 and 8000.

The import produced 16 articles from 17 records, seven stories, 28 supported claims and two conflicting assertions. English and German editions led with different stories and had valid evidence snapshots and WAV timing boundaries. A third account used a new set of interests immediately.

The trust suite checks changed numbers, percentages, currency, units, dates, negation, actor order, unsupported statements, missing evidence, bad spans and a constrained valid paraphrase. Script tampering blocks speech publication. A later retry can recover after the selection changes. Authentication checks cover listener ownership for audio, conversation, transcript and schedule resources and the initial authenticated WebSocket frame.

## Scope of external checks

The default deployed demo selects the deterministic model, lexical embedding adapter and eSpeak NG. The optional Sentence Transformers and Scrapling implementations were exercised separately. The MiniLM tensor was downloaded from the public model distribution and verified by its declared SHA-256 before loading. The native Ollama check used an already installed model and a disposable database.

The ElevenLabs, compatible remote LLM and Whisper interfaces were exercised with simulated HTTP transports. Hosted API credentials, actual vendor audio generation and live microphone recognition were outside this run. Newstex files and official release material were unavailable. Date windows, source-language coverage and conservative disagreement detection are documented in the pipeline guides. The 10× value is an explicit cost projection.

## Fixes found during validation

- A committed mobile delivery schedule initially displayed stale query data. The settings flow now updates the query cache after saving, and the mobile browser test confirms the time persists.
- Failed model drafts could lose usage observations when their transaction rolled back. Attempt observations now survive the rollback and remain counted once per call.
- Concurrent synthesis could associate a timeline with a competing audio write. PostgreSQL cache locking and immutable content-derived object keys preserve the winning waveform and timing record.
- Final verification now refreshes and checks the saved citation snapshot and evidence spans before publication.
- The original MinIO image endpoint refused access. The deployment uses a tested, digest-pinned Bitnami community image with an actual ready endpoint.

## Home-page sketch revision

The home route now uses the supplied speaker-selection layout. Existing accounts migrate to revision 0002_discussion_model. Voice style, language, duration and discussion mode are stored through the preferences API. The day/week selector passes its period to the existing generation form.

After this change, 42 backend tests and seven frontend tests passed. The two Chrome scenarios passed against the Docker deployment, including speaker selection, discussion selection, persistence after reload, audio playback, evidence display, chat and mobile onboarding. The desktop and mobile screenshots were inspected. Portraits use original illustrated characters. The default discussion backend remains the local configured assistant.

## Live ElevenLabs deployment check

The local deployment was subsequently configured for ElevenLabs at the user's request. The key lives in the Git-ignored mode-0600 environment file. The provider's authenticated voice catalog returned available premade voices. The five application styles map to Daniel (professional), Charlie (energetic), Chris (casual), George (studio assistant) and Brian (cyberpunk). Local speech fallback is disabled in this installation.

A new asynchronous briefing went through the existing evidence gate, ElevenLabs multilingual v2 synthesis, WAV decoding and MinIO storage. The authenticated briefing endpoint reported audio_provider=elevenlabs. The retrieved WAV contained 432,152 bytes and 9.8 seconds, and its factual segment retained its source citations. This was a live vendor API call with the configured account. Vendor billing was not independently measured. Existing cached editions retain their original audio.

## Daily recording and voice-session revision

The full backend suite passed 45 tests and the frontend suite passed eight tests. Added regressions cover daily idempotence, next-day creation, copying a prepared template to a private listener, preserving the baseline after preference changes, explicitly regenerating a custom voice, the resume command, the real Scribe request format, and voice-activity capture cleanup.

Two Chrome scenarios passed against Compose. Play started a buffered daily recording without POST /briefings, and preferences still persisted. Mobile registration and schedule editing passed. A separate Chrome test injected an offline-synthesized question into a virtual microphone stream. Real voice-activity detection paused the narration, ElevenLabs Scribe transcribed it, source retrieval returned citations, and ElevenLabs speech played the answer. Switching the microphone off ended its media tracks. Physical microphone capture and acoustic echo behavior in a room were outside this automated test.

A separate live HTTP probe produced a prepared 47.98-second daily recording through ElevenLabs. “What do other sources say about this story?” was transcribed correctly and answered with two citations. Speech recognition and retrieval took 1.19 seconds. Spoken audio was ready in 3.09 seconds from submission, and the answer lasted 6.34 seconds. These are observations from one request and do not guarantee a latency bound.

## Compact listening-home revision

The frontend production build and eight unit tests passed. Both Chrome scenarios passed on the updated Compose frontend. They checked immediate prepared playback without a generation POST, voice preference changes, creation and automatic playback of a weekly episode, model selection on the separate Settings page, source-backed discussion and mobile onboarding. Desktop and mobile screenshots were inspected. A separate virtual-microphone check through ElevenLabs confirmed interruption of both the briefing and a spoken assistant answer, and release of capture tracks when the session ended. Recognition and response remain asynchronous provider operations while capture continues. Physical-room echo behavior remains device-dependent.

## Interaction flicker regression

The authenticated pages now share a persistent header. Voice selection updates the preference optimistically and keeps the portrait row at full opacity while saving. The feedback row and playback timeline retain their dimensions. Prepared audio is cached for five minutes after its last observer detaches, and sign-out revokes the object URL and clears the private cache.

Nine frontend tests and three Chrome scenarios passed. The new scenario delayed a voice-preference request, checked that all portrait buttons remained at full opacity, and verified that the same header DOM node survived settings navigation. Returning to the listening room reused the exact audio URL without a new audio request. No document request occurred and the page time origin remained unchanged. The production frontend build passed.

## Scheduled notifications, private voice collections and CPU inference — 21 November 2026

Migration `0011_notifications_voices` adds owner-scoped collection entries, browser subscriptions and ready notifications. Existing saved voices are backfilled with their owner/name. The complete current backend suite passed **123 tests**; the frontend passed **46 tests** and the TypeScript/Vite build. Fresh local migration bootstrap also completed. Tests cover private collection ownership, preserving multiple custom characters, favorite persistence, removal/restoration, device opt-out, forbidden push endpoints, ready-stage idempotency, provider retry de-duplication, VAPID signing and an actual AES128GCM encryption/decryption round trip using a generated browser key pair. The local-provider test confirms the request goes to Ollama without cloud credentials and does not fall back to a paid model.

Against the deployed HTTPS site, desktop Chrome and touch-enabled mobile WebKit confirmed that a saved custom voice appears in Settings, star changes survive reload and only favorites appear on the listening home. Browser JS errors were absent. Both browsers fetched the service worker, install manifest and authenticated public VAPID key. Prepared-audio requests were intercepted in these collection/UI scenarios to avoid consuming the already limited narration allowance; these tests do not claim fresh audio synthesis.

An actual headless Chrome push subscription was attempted after granting its test context notification permission. The browser/OS rejected registration with `Registration failed - permission denied`, so a real system banner was **not** verified. The product exposes **Send test** for a user-enabled device. Safari on iPhone/iPad requires a Home Screen installation; browser/OS permission and connectivity remain prerequisites.

Ollama was enabled on the deployment host with Qwen3 0.6B, bound only to its Docker bridge, cloud access disabled, one loaded model/request and bounded CPU/RAM. An initial UUID-heavy answer timed out after 35 seconds. Compact indexed source context, a short answer schema, disabled thinking, a 2,048-token context and two CPU threads reduced the measured source-grounded answer to **8.28 seconds** (205 input and 41 output tokens), passing the existing gate with two source citations. This is one observed request, not a guaranteed response bound. For prepared narration, local mode assembles verified source sentences without a rewriting API. Cloud speech, cloning, web research and native realtime audio remain independent paid services.

## Mobile layout revision — 21 November 2026

The mobile stylesheet is loaded after the base styles, with desktop rules unchanged. Fixes cover the notification popover's viewport anchoring, long personal narrator names, compact narrator controls, equal-width voice-engine choices, wrapping navigation/forms and 16px inputs to avoid mobile Safari focus zoom. Controls receive larger touch targets and the existing safe-area padding remains in place. No root-level overflow clipping is used to hide layout errors.

Chrome and touch-enabled WebKit checks at 320px and 390px covered listening home, all four settings sections, Explore, episode history and the assistant. Stress data included an 80-character custom voice name with no spaces, an open notification menu and the expanded model selector. Before the fix, the long name expanded the 320px page to 563px and the notification panel extended left of the viewport. After the fix the same checks reported no horizontal overflow. The production stylesheet bundle was also checked in WebKit. The 48 frontend tests and TypeScript/Vite build passed. Layout checks reused an existing private QA edition and substituted a tiny WAV to avoid generating or repeatedly downloading long narration; speech-provider behavior was not under test.
