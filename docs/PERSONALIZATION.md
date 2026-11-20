# How each listener gets an edition

Each recommendation is computed from the listener's current preferences and the global story inventory. A new account can choose arbitrary interests immediately. Interests are case-insensitive topic names with spaces normalized to underscores. Stories must match the requested time window, topic and source selection. Selecting story IDs explicitly lets listeners revisit older reporting.

| Ranking input | Default weight | Value |
| --- | ---: | --- |
| Interest match | 0.34 | One when a story topic or category matches a chosen interest |
| Global importance | 0.22 | Story importance, scaled from zero to one |
| Recency | 0.14 | One divided by one plus the story's age in days divided by three |
| Urgency | 0.08 | Story urgency, scaled from zero to one |
| Preferred publisher | 0.08 | One when an eligible publisher is preferred |
| Unheard preference | 0.07 | One for a story the listener has yet to play |
| Explicit feedback | 0.07 | Minus one, zero or one |

The sum determines order. Publication time and story ID break ties. When a story scores at least 0.9 for urgency and 0.8 for importance, the highest ranked qualifying story receives a place in the top three. Source exclusions, topic filters and the requested period still apply. Configure individual weights through a JSON object in `RANK_WEIGHTS`, for example `{"interest":0.4,"importance":0.25}`.

A request uses the listener's preferred language, length, voice and depth unless the request overrides those fields. The generator selects supported claims in the requested language and drops citations from excluded publishers. The word budget uses 145 words per minute. Brief, standard and detailed editions allow one, two or three supported claims per story. Small datasets produce shorter editions once available evidence is exhausted.

The technology listener prefers a three-minute English edition and the energetic voice. The finance listener prefers a six-minute German edition and professional delivery. The multilingual fixture contains German source evidence for a finance story. Unsupported translations cannot enter a script. A request with no eligible evidence fails with a message that identifies the selection issue.

Clients call `GET /api/v1/recommendations` for the listener's ranked feed. Playback writes `PUT /api/v1/listening-history/{story_id}`. Feedback uses `PUT /api/v1/feedback/{story_id}` with a score of -1, 0 or 1. Both updates are idempotent.

Run `python -m pytest tests/test_listener_workflow.py` from the backend with its dependencies installed to exercise profile changes, wildcard interests, breaking news, source exclusions, publication gates and playback.
