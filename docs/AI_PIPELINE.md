# News ingestion and event analysis

An ingestion job processes one input globally. Its committed article IDs pass to the analysis stage. Listeners reuse the resulting stories, facts and vectors.

## Sources and import

The bundled fixture lives at `backend/app/news/fixtures/synthetic.json`. Every publisher, event and example-domain URL in it is fictional. Seeding anchors relative publication times to the first import. Restarting reuses that import. The demo covers English, German and Dutch. Its 17 input records include one exact duplicate that differs only by HTML markup.

For an authorized event export, mount the file in the read-only datasets directory, set `DATASET_FILES` to its filename and submit the following body to authenticated operator endpoint `POST /api/v1/ingestion/jobs`.

```json
{"kind":"dataset","locator":"week.jsonl"}
```

Use the returned job ID with `GET /api/v1/ingestion/jobs/{job_id}`. The importer accepts UTF-8 JSON arrays, objects containing an `articles` array, and JSONL/NDJSON. Split files above 15 MiB. A row requires an absolute HTTP(S) source URL, publisher, publication timestamp with timezone, BCP-47-style language code, title and body. An author and external ID are optional. Supported input aliases appear below.

| Normalized field | Accepted export fields |
| --- | --- |
| title | title, headline |
| content | content, body, full_text, text, content_html |
| source | source, publisher, source_name |
| url | url, original_url, link |
| published_at | published_at, publication_date, published, date |
| external_id | external_id, id, article_id |

These mappings describe this adapter's input contract. The original hackathon export was unavailable. Inspect its schema and map fields before importing. Retain the original URLs and real publication times. The demo clock applies exclusively to the synthetic fixture. Use the project cleanup command in the deployment guide before the license expires.

A normalized row example for a locally authored fixture follows.

```json
{"article_id":"sample-1","publisher":"Example publication","headline":"Oris opens Harbor transit pilot","body":"Oris opened the Harbor transit pilot.","original_url":"https://publication.example/pilot","publication_date":"2026-11-20T08:00:00Z","language":"en"}
```

For operator-approved feeds, set `RSS_FEED_URLS` to comma-separated HTTPS feed URLs and submit `{"kind":"rss","locator":"<configured URL>"}`. Scheduled discovery uses the same import path. HTTPX applies a timeout and download limit, then feedparser reads already-downloaded bytes. Redirects are disabled. Undated or unlinked entries are skipped. Feed body text, an entry link and a publisher label provide provenance. There is no general-purpose URL fetch endpoint. `NEWS_HTML_PARSER=beautifulsoup` removes scripts, styles, templates and markup. Operators with the `crawl` extra may select `scrapling` for HTML parsing. Use `BACKEND_EXTRAS=[ml,crawl]` for a Compose build with both optional providers. [Scrapling parser documentation](https://scrapling.readthedocs.io/en/latest/parsing/main_classes.html)

## Event construction

1. Store NFC-normalized visible text with collapsed whitespace. Keep the publisher, URL, author, external ID, language, timestamps and SHA-256 digest. Exact normalized-body duplicates increment the job counter and skip all model work. Synthetic and imported provenance have separate deduplication boundaries.
2. Embed each unique article once. The offline `local_hash` profile projects normalized multilingual lexical features into 384 dimensions. The separate `sentence_transformers` profile loads the configured multilingual encoder and checks its output size. Set `EMBEDDING_PROVIDER=sentence_transformers`, install the `ml` extra and make the model weights available before starting ingestion. The persisted model identifier scopes candidate lookup. [Sentence Transformers encoding reference](https://sbert.net/docs/package_reference/sentence_transformer/model.html)
3. Search within 72 hours of both the candidate article and the story's original time. PostgreSQL retrieves up to 32 candidates by cosine distance, with an HNSW vector index. SQLite evaluates eligible candidates in process for the local demo. [pgvector SQLAlchemy reference](https://github.com/pgvector/pgvector-python#sqlalchemy)
4. Require a shared named title anchor, a compatible action and specific shared event terms. Titles with different distinctive names on both sides or disjoint explicit actions are kept apart. The cosine threshold defaults to 0.46 and can be set through `CLUSTER_SIMILARITY`. A merge needs enough lexical evidence even when the embedding similarity is high.
5. Mark near-identical same-language article variants within an event using token trigrams, Jaccard similarity of at least 0.76, and unchanged numeric values. Preserve both articles and their source URLs. A near copy does not increase the count of publications used for the importance boost.
6. Extract source-aligned statements, refresh comparison groups, then emit an event and write model usage within the same transaction. PostgreSQL serializes concurrent clustering edits through a transaction-scoped advisory lock. Retrying a completed stage reuses the committed outcome. Ingestion and analysis stage timings include SQL work. Embedding timings are a subset of analysis time.

## Topics and scoring

Weighted topic lexicons inspect the headline four times and the lead once. AI receives a technology topic and finance receives an economy topic. An unmatched article goes to general. Original-language excerpts remain available. Language-neutral hashes alone cannot reliably link arbitrary synonyms, publisher translations, or differently transliterated names; guarded clustering favors retaining separate events in these cases.

The global importance score adds the following terms and caps the result at 0.99.

- A 0.38 baseline.
- An impact contribution of 0.23 for finance, energy or climate coverage, and 0.12 for other topics.
- 0.065 for each distinct contributing publisher, up to four.
- 0.27 if the lead contains the emergency signal.

Urgency has a 0.30 baseline, adds 0.59 for the emergency signal and 0.09 for a warning or rate cut, capped at 0.99. The emergency signal is an explicit evacuation/emergency term or a flood with a warning. These scores rank event coverage. The personalized ranking also uses preferences, recency and listening history.

## Inspection and corrections

Read `GET /stories/{id}` for article membership, evidence and disagreements. An operator can merge via `POST /stories/{id}/merge` with `{"into_story_id":"..."}`, or split via `POST /stories/{id}/split` with `{"article_ids":["..."]}`. The prefix is `/api/v1`. A split must select a proper subset. Corrections recompute topic scores, evidence and disagreements. Stories referenced by briefing items or conversation messages retain their membership to preserve historical citations. A fully merged source story is archived.


## Running the provider checks

The default news tests use the offline hash encoder. To run the same assertions against the configured Sentence Transformers model and the Scrapling parser, install the optional extras and supply the downloaded model directory. A model ID also works when the host can reach the model registry.

```bash
cd backend
python -m pip install -e '.[ml,crawl,test]'
NEWS_HTML_PARSER=scrapling EMBEDDING_PROVIDER=sentence_transformers \
  EMBEDDING_MODEL=/absolute/path/to/paraphrase-multilingual-MiniLM-L12-v2 \
  python -m pytest -q tests/test_news_pipeline.py tests/test_news_verification.py
```
