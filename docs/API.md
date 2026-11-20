# API contracts

All application paths begin with `/api/v1`. Use the interactive Swagger page at `/docs` and the complete machine-readable contract at `/openapi.json`, also checked into `shared/contracts/openapi.json`. Run `make openapi` after changing routes. Signed-in routes accept `Authorization: Bearer <access_token>`.

| Group | Entry points |
|---|---|
| Session | POST `/auth/register`, `/auth/login`, `/auth/demo`; GET `/auth/me` |
| Listener | GET/PATCH `/users/me`, `/users/me/preferences`; GET/PUT `/users/me/interests`; PUT `/users/me/sources` |
| Catalog | GET `/sources`, `/topics`, `/voices`, `/recommendations`, `/stories`, `/stories/{id}`, `/articles/{id}` |
| Evidence | GET `/stories/{id}/articles`, `/facts` and `/source-comparison` beneath the story resource |
| Briefing | POST/GET `/briefings`; GET `/briefings/{id}` and its `transcript`, `sources`, `audio` resources; POST `/briefings/{id}/retry` |
| Feedback | PUT `/listening-history/{story_id}` and `/feedback/{story_id}` |
| Assistant | POST `/conversations`, GET `/conversations/{id}`, POST `/conversations/{id}/messages` or `/audio`; GET `/conversations/{id}/messages/{message_id}/audio` |
| Live voice | POST `/agent-session`, POST `/agent-context`; provider selection from GET `/health` |
| Schedules | GET/POST/PUT `/schedules`; PATCH/DELETE `/schedules/{id}`; GET `/timezones` |
| Operations | POST `/ingestion/jobs`, GET `/ingestion/jobs/{id}`; operator-only story merge/split; GET `/metrics/costs`, `/health`, `/ready` |

`POST /briefings` accepts day/week/month, optional topic, article-evidence language, duration target, voice slug and selected story IDs. A 202 response includes `briefing_id` and `status`. The authenticated resource supplies numeric progress and ordered segments. Retrieve the WAV only after completion. A request for a private resource owned by another listener returns 404. A conflicting number has a `conflicting` status and evidence in story detail.

`GET /stories` supports date range, language, topic, source, minimum importance, search, sort, limit and cursor. Follow the opaque `next_cursor` using the same filters. Each `/articles/{id}` record contains normalized full text that can be sliced at the reported character offsets.

For live progress, open `/api/v1/ws/briefings/{id}` on the same host. The first client frame must be JSON with a `token` property. The gateway verifies ownership and origin, then emits status changes and closes on a terminal state. The event name has the form `briefing.<status>`. Each frame includes the briefing ID, UTC timestamp and progress. Reconnecting gets the latest state. REST remains available during reconnects.

Login uses JSON email/password. Registration also takes a display name. Schedule creation takes `time` in HH:MM, `timezone` as a fixed GMT offset such as `GMT+02:00` or `GMT-03:30` (saved IANA zones remain supported), `enabled`, and `days_of_week` (Monday=0 through Sunday=6; omitted means every day). Multiple daily times use separate rows. PUT `/schedules` atomically replaces the authenticated listener’s complete plan with an array of these entries, rejecting overlapping slots. Existing matching rows retain their IDs and completed-run markers. Newly added past times begin at their next occurrence. GET `/timezones` lists the fixed GMT offsets for the dropdown, including fractional-hour offsets. The UI renders hour and minute selectors separately; the API still stores their combined `HH:MM` value. Fixed GMT offsets do not follow seasonal clock changes. Conversation creation accepts an optional story or briefing context. Text turns take `{"text":"What do other sources say?"}`; voice turns use multipart field `file`.

For ElevenAgents voice sessions, send optional `briefing_id`, `story_id` and `playback_seconds` in the authenticated `POST /agent-session` request. Use the returned `signed_url` to connect over WebSocket and pass the bounded `context` string in the `sourcera_context` dynamic variable. `POST /agent-context` refreshes the authorized context with the same request format. Set `more_news: true` to retrieve other recent news while excluding the specified briefing's stories.

HTTP errors include `error.code`, `error.message` and `detail`. Invalid inputs return 422. The gateway bounds uploaded bytes, rate-limits expensive requests and omits request bodies and access tokens from application logging.


`POST /briefings/{id}/revoice` creates a new narration of the authenticated listener's completed episode using their currently selected preset voice. It preserves the script, story order, language and citations, queues only the voice stage, and returns the usual 202 queued response. Current evidence is still checked before and after synthesis. Another listener's episode returns 404; an unfinished episode returns 409. Identical narration uses the existing audio cache.

## Streamed audio

`POST /conversations/{id}/realtime` accepts `{ "sdp": "<WebRTC offer>" }` and returns `application/sdp`. It requires the conversation owner, `REALTIME_ENABLED=1` and a configured OpenAI key. Provider credentials stay on the server. `GET /health` advertises `realtime_voice`.

`POST /conversations/{id}/realtime-evidence` accepts `{ "question": "…", "decision": { "intent": "EXPLAIN_STORY", "retrieval_query": "standalone English search question" }, "story_id": "optional current briefing story" }`. The supplied playback story must belong to this conversation’s briefing. The response contains verified evidence and a playback action, used internally by the audio model, never rendered as a chat bubble.


`POST /conversations/{id}/speech-session` authorizes the owner’s live ElevenLabs synthesis channel. With `REALTIME_SPEECH_PROVIDER=elevenlabs`, it returns a single-use TTS WebSocket token, the selected mapped voice ID, model and sample rate. The response is `private, no-store`. The permanent ElevenLabs API key stays server-side. Realtime negotiation advertises its output route through `X-Speech-Output`; ElevenLabs mode requests streamed GPT text, while OpenAI mode requests native audio.
