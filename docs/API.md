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
| Schedules | GET/POST `/schedules`; PATCH/DELETE `/schedules/{id}` |
| Operations | POST `/ingestion/jobs`, GET `/ingestion/jobs/{id}`; operator-only story merge/split; GET `/metrics/costs`, `/health`, `/ready` |

`POST /briefings` accepts day/week/month, optional topic, article-evidence language, duration target, voice slug and selected story IDs. A 202 response includes `briefing_id` and `status`. The authenticated resource supplies numeric progress and ordered segments. Retrieve the WAV only after completion. A request for a private resource owned by another listener returns 404. A conflicting number has a `conflicting` status and evidence in story detail.

`GET /stories` supports date range, language, topic, source, minimum importance, search, sort, limit and cursor. Follow the opaque `next_cursor` using the same filters. Each `/articles/{id}` record contains normalized full text that can be sliced at the reported character offsets.

For live progress, open `/api/v1/ws/briefings/{id}` on the same host. The first client frame must be JSON with a `token` property. The gateway verifies ownership and origin, then emits status changes and closes on a terminal state. The event name has the form `briefing.<status>`. Each frame includes the briefing ID, UTC timestamp and progress. Reconnecting gets the latest state. REST remains available during reconnects.

Login uses JSON email/password. Registration also takes a display name. Schedule creation takes `time` in HH:MM, `timezone` as an IANA zone, and `enabled`. Conversation creation accepts an optional story or briefing context. Text turns take `{"text":"What do other sources say?"}`; voice turns use multipart field `file`.

HTTP errors include `error.code`, `error.message` and `detail`. Invalid inputs return 422. The gateway bounds uploaded bytes, rate-limits expensive requests and omits request bodies and access tokens from application logging.


## Streamed audio

`POST /conversations/{id}/realtime` accepts `{ "sdp": "<WebRTC offer>" }` and returns `application/sdp`. It requires the conversation owner, `REALTIME_ENABLED=1` and a configured OpenAI key. Provider credentials stay on the server. `GET /health` advertises `realtime_voice`.

`POST /conversations/{id}/realtime-evidence` accepts `{ "question": "…", "decision": { "intent": "EXPLAIN_STORY", "retrieval_query": "standalone English search question" }, "story_id": "optional current briefing story" }`. The supplied playback story must belong to this conversation’s briefing. The response contains verified evidence and a playback action, used internally by the audio model, never rendered as a chat bubble.
