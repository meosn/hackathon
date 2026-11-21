# Liquid Briefing: criterion-by-criterion audit

Checked on 21 November 2026 against the one-page Sourcera challenge brief supplied by the user, the current repository and read-only production queries. This is an implementation/acceptance audit, not a prediction of the jury's score. Full compliance cannot yet be claimed.

| Criterion | Implemented and observed | Acceptance still needed |
|---|---|---|
| Trust and accuracy — 25 points | Factual prepared-audio segments contain claim IDs, article IDs, source URLs/excerpts and timings. The publication gate checks evidence spans and numbers before synthesis. Disagreements are flagged. The deployed database had 2,761 supported segments in completed episodes; all 2,761 had nonempty claim, article and citation fields. Investment-advice filtering is present. | Field presence and source alignment do not prove an article is true. Perform the jury's three-claim check and compare against its answer key/official releases. Native realtime conversation has source context but does not pass every spoken sentence through the prepared-script verification gate. |
| Fit to the listener — 20 points | Interests, preferred/excluded sources, language, depth, duration, listening history and reactions affect ranking/content. Existing archive recordings include English and German listeners, with distinct preference templates. Personal accounts support new/custom interests without changing the code. Demo-profile removal affects the public entry screen, not personalization. | Obtain the four official profiles and demonstrate them plus the wildcard using the actual judging criteria. The two historical app templates must not be described as the four official profiles. |
| Making sense of the news — 20 points | All eight archive jobs completed: 1,740 records, 4 exact duplicates removed, 1,736 articles analyzed. Local multilingual embeddings, guarded clustering, supported-fact extraction, disagreement detection and importance ranking are implemented. Publisher-family counting excludes language editions and detected reprints as independent evidence. | Clustering and fact-extraction precision/recall have not been measured against the official answer key. Similarity-based near-duplicate and event detection are heuristic. Independent-event coverage is not the same as two publishers supporting every narrated fact. |
| Scalability and cost — 15 points | Separate queues/workers, bounded batches, local embeddings, cheap rules, targeted small-model calls, deduplication, shared audio cache and usage observations are implemented. The complete-archive processing estimate is $0.13060096, with a linear 10× estimate of $1.30600960, excluding listener work; see COST_ANALYSIS.md. | Put scoped costs and assumptions in the final pitch. The existing global ledger rates are not model-specific; the report explicitly reprices the two GPT-4.1 mini calls. Invoice reconciliation and measured 10× throughput are not available. The brief requests a 10× estimate, so absence of a measured load test alone does not fail this criterion. |
| Listening experience — 10 points | Structured top-three daily episodes, additional stories, weekly editions, playback/seek controls, independent microphone muting, spoken conversation, voice previews and synthetic-voice labels exist. Trump pauses are shortened without resynthesizing cached words; transcript timings are updated together. Chrome and Safari/WebKit have previously played actual hosted audio. | Subjective pacing and physical-device microphone quality need listener review. Requested duration is a target dependent on source material and voice speed. At the latest balance check ElevenLabs had 961 characters remaining, preventing new long recordings. Cached recordings remain usable. |
| Path to product — 10 points | Personal accounts, private preferences/custom voices, preparation schedules and an editor-facing source/evidence view form a working product foundation. The player discloses AI narration. | A final presentation naming the paying customer, the newsroom workflow and commercial assumptions is not in this repository. Premium voice locking is implemented, but payment/subscription purchasing is not. A paywall alone is not a validated business model. |

## Deliverables

- **Working prototype:** real archive imports and audio for at least two distinct listener preferences exist. Ownership and evidence gates are implemented. New long audio currently depends on restoring provider allowance.
- **Presentation:** not supplied as a finished deck. Existing technical documentation and the cost report provide material, but do not constitute the requested presentation.

## Archive access and provenance

The previously supplied ZIP contains six publisher/language JSONL files plus README and tips. It has no separate official-release bundle, four-profile specification or answer key. Its 1,740 input records match the eight completed production import chunks. Full article text is private; public views expose bounded excerpts and source links.

A GET of https://hackathon.sourcera.news/ returned the team's registration form, not an archive index or download. The page requests team/name/email and acceptance of the data licence. No signup was submitted. The existing authorized ZIP is already imported; a team-issued download URL is needed to inspect newer files. The signup page must not be configured as an RSS source. The licensed dataset is event-only and must be deleted under its terms after the hackathon.

The current public product uses `ACTIVE_CORPUS=live`, so automatic daily recommendations use current public feeds. Archive episodes remain accessible; explicit archive story IDs can still be narrated. For an end-to-end jury run on the challenge week, use an isolated archive deployment or the documented `ACTIVE_CORPUS=licensed` / `NEWS_REFERENCE_TIME` configuration. Live RSS must not be presented as a replacement for the required challenge-dataset demonstration.

## RSS and public profiles

The production scheduler discovers enabled feeds every 15 minutes, independently of `DEMO_MODE`. Before this change, read-only queries already showed two or three completed cycles for each of the seven feeds (BBC World/Technology, DW English/German, NOS, Guardian World, Al Jazeera). Importing again skips exact duplicates and queues analysis for new articles. A regression test checks that a completed cycle is not duplicated before 15 minutes and that the next cycle queues with demo mode disabled.

The public frontend now offers only personal registration/sign-in and never automatically calls `/auth/demo`. Production sets `DEMO_MODE=false`, which disables the demo-creation endpoint and demo-template seeding. Existing account/history rows are preserved. Legacy developer/test demo tooling requires explicit opt-in and is not exposed in the public interface.

## Validation for this change

- Backend: 115 tests passed, including refreshed RSS with demo disabled and cached Trump retiming preserving voiced samples and all shared transcript cues.
- Frontend: 41 tests passed; TypeScript/Vite build passed.
- Production checks and cached-audio migration results are appended below after deployment.
