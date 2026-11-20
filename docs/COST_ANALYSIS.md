# Costs and volume projection

For the hosted API configuration, estimates use USD 0.15 per million input tokens and USD 0.60 per million output tokens for GPT-4o mini. ElevenLabs multilingual v2 uses an estimate of USD 80 per million characters, and Scribe v2 uses USD 0.20 per audio hour. These are published-price assumptions checked on 20 November 2026. Account allowances, discounts and invoices can change the amount charged. [OpenAI model pricing](https://developers.openai.com/api/docs/models/gpt-4o-mini), [ElevenLabs API pricing](https://elevenlabs.io/pricing/api).

The figures below come from the fresh-volume Docker acceptance run on 20 November 2026. All inputs were synthetic. The default providers ran locally. The ledger records observed calls, token counters when reported, character counts and wall-clock stage time. No paid vendor was contacted in this run.

| Observed quantity | Value |
|---|---:|
| Presented input records | 17 |
| Exact duplicates removed | 1 |
| Retained articles and embedding calls | 16 |
| Stories | 7 |
| Supported claims / conflicting claims | 28 / 2 |
| Completed briefings | 2 |
| TTS characters synthesized | 1,162 |
| Remote LLM calls / STT calls | 0 / 0 |
| External API charges | USD 0 |
| Normalization time | 0.0186 s |
| Analysis time, including embeddings | 0.1181 s |
| Embedding time, included in analysis | 0.0013 s |
| Script and verification time | 0.0620 s |
| Speech generation time | 1.8021 s |

The two generated editions contained 14 English factual statements and four German factual statements. Their actual spoken lengths were 56.16 and 23.72 seconds. Available evidence determined these short lengths. Audio reuse produces no additional provider call when an identical voice, language and script is requested.

## Explicit estimates

`COMPUTE_USD_PER_HOUR` defaults to an assumed USD 0.04 per observed active-stage hour. It is an accounting assumption. The deployment receives no cloud invoice and measures no energy consumption. The estimate excludes idle capacity, database memory, broker, storage and network costs. Embedding time stays inside the enclosing analysis timer, and remote model time stays inside the script timer, to avoid adding the same wall time twice.

For this run, the active compute estimate was USD 0.0000222319. Dataset processing contributed USD 0.0000015188, or about USD 0.0000002170 per story. Listener processing contributed USD 0.0000207131, or about USD 0.0000103566 per completed edition.

The simulated 10× dataset workload has 170 input records at the same duplicate ratio, coverage pattern and unit-time behavior. Listener demand stays fixed at two editions. Its formula is `10 × dataset cost + listener cost`, yielding USD 0.0000359013 for this run. This is a small-fixture linear projection. It does not measure a 170-record processing run or predict nonlinear cluster retrieval, database contention or extra facts selected for narration. At fixed dataset size, additional listeners increase ranking, text and speech demand independently. If ten times as many users each generate the same number of editions, listener demand scales separately.

API estimates use operator-provided per-million input-token, output-token and TTS-character prices. Zero-price configuration for a remote provider leaves its observations counted as unpriced, and the dashboard reports that count. These provider estimates remain separate from actual API-charge observations. Failed provider attempts retain their observed usage after a stage rollback, and retry observations correspond to the additional calls made.

## Optional provider measurements

A separate local Ollama probe used the installed `llama3.1:8b` model. The provider reported 135 input tokens and 86 output tokens in 6.87 seconds. Its single factual line passed the source gate and produced a 6.82-second local WAV. That isolated probe is excluded from the Compose ledger above. Tests with simulated ElevenLabs and Whisper transports validate their request and response integration. Hosted-vendor billing and microphone recognition quality remain unmeasured.

Fetch current totals through `GET /api/v1/metrics/costs` as an operator or demo listener, or run `./scripts/compose.sh exec api python -m app.cli costs`. Repeated demo runs change aggregate totals.
