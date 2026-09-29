# Changes

Summary of everything done in this project since the start of the session,
grouped by theme rather than strict chronological order.

## 1. Embedding backend made swappable

- **Added** `embedding_backend.py` — a `get_embedder(model_name)` factory
  switched by the `EMBED_BACKEND` env var:
  - `sentence_transformers` (default) — calls `sentence-transformers` directly.
  - `llama_index_hf` — uses llama-index's `HuggingFaceEmbedding` wrapper.
  - Both expose the same `get_text_embedding(text)` interface.
- **Fixed**: original code imported `SentenceTransformerEmbedding` from
  `llama_index.embeddings`, which does not exist in any llama-index version
  and was never installed. This broke `retrieval/retriever.py`,
  `ingestion/ingestion_csv.py`, and `tests/test_ingest.py` at import time.
- **Changed** those three files to call `embedding_backend.get_embedder(...)`
  instead.
- Installed `llama-index-embeddings-huggingface` and added it, along with
  `sentence-transformers`, to `requirements.txt`.

## 2. PDF ingestion (new capability)

Previously only CSV ingestion existed, and no PDF source could be ingested
at all (`pdf_render/render_pdf.py` only goes markdown → PDF, not PDF → data).

- **Added** `ingestion/pdf_utils.py` — `extract_pdf_text(path)` shared helper
  (via `pypdf`).
- **Added** `ingestion/ingestion_pdf.py` — `parse_canonical_qa_pdf(text)`
  parses PDFs shaped like `qa_content.pdf` (numbered `Question` / `Answer` /
  `Subject:` blocks) into `{question_text, answer_text, subject}` records.
- **Added** `ingestion/qp_sa_converter.py` — `convert_qp_sa(qp_path, sa_path)`
  handles the harder case: a question paper and a suggested-answer paper as
  two separate PDFs, with nested `Question N` → `a)/b)/c)` → `i)/ii)`
  sub-parts on one side and `Question No. N(a)(i) [XM]`-style headers on the
  other.
  - Matches sub-parts between the two files by their **`[XM]` mark sequence**
    (not by lettering, which was found to drift between the two documents in
    real exam papers).
  - If the two files don't have the same number of marked sub-parts, the
    pair is skipped with a `NEEDS REVIEW` warning instead of guessing.
  - If a sub-part's mark values disagree (source typo), it's still paired
    but flagged with a `VERIFY` warning.
  - Strips repeated page headers/footers before parsing.
- Added `pypdf` to `requirements.txt`.
- Verified end-to-end against real sample files: `qa_content.pdf` (10/10
  parsed), and a real QP+SA pair (13/13 sub-parts matched, one genuine
  source typo correctly flagged rather than silently trusted).

## 3. CLI for ingestion

- **Added** `ingest_cli.py` — command-line entry point over
  `ingestion_pdf.main()`:
  ```bash
  python ingest_cli.py qa_content.pdf
  python ingest_cli.py --pair QP.pdf SA.pdf
  python ingest_cli.py qa_content.pdf --pair Chapter1-QP.pdf Chapter1-SA.pdf
  ```

## 4. Deduplication on re-ingestion

- **Problem**: every ingestion run generated a random `uuid.uuid4()` per
  record, so re-ingesting the same file created duplicate Qdrant points
  instead of updating existing ones.
- **Added** `ingestion/qdrant_upsert.py` — a shared `upsert_records()` used
  by both CSV and PDF ingestion, with `record_id()` computing a
  **deterministic UUID5 hash** of `question_text + answer_text + subject`.
  Same content always maps to the same point ID, so re-ingesting the same
  file overwrites in place instead of duplicating.
- **Refactored** `ingestion/ingestion_csv.py` and `ingestion/ingestion_pdf.py`
  to both call this shared helper, removing two separately-buggy upsert
  implementations (the CSV path used fragile row-index IDs; the PDF path
  used fully random IDs).
- Verified: re-ingesting `qa_content.pdf` twice stays at 10 points, not 20;
  re-ingesting the QP+SA pair twice stays at 23, not 46. Wiped and
  re-ingested the real `student_validator_qa` collection to clear out
  duplicates accumulated before this fix.

## 5. Multi-provider LLM support (OpenRouter / Gemini)

- **Refactored** `llm_verdict/verdict_llm.py`: `get_llm_verdict(prompt)` now
  dispatches on the `LLM_PROVIDER` env var (`openrouter` default, or
  `gemini`) via a `_PROVIDERS` dict, same pattern as `embedding_backend.py`.
  Function signature unchanged, so `api/main.py` and existing tests needed
  no changes.
- Gemini calls `https://generativelanguage.googleapis.com/v1beta/models/{LLM_MODEL}:generateContent`,
  authenticating via the `X-goog-api-key` header (matches Google's current
  documented approach — keeps the key out of URLs/logs, unlike an earlier
  version of this code that used a `?key=` query param).
- To switch models: edit `.env` only —
  ```bash
  LLM_PROVIDER=gemini
  LLM_MODEL=gemini-2.5-pro
  GEMINI_API_KEY=...
  ```
  Retrieval, prompt composition, and the `/validate` API contract are
  unchanged regardless of provider.

## 6. Other pre-existing bugs found and fixed

- `retrieval/retriever.py` called `QdrantClient.search()`, which was removed
  in `qdrant-client` 1.18 in favor of `.query_points()`. This blocked the
  entire `/validate` endpoint regardless of ingestion source. Fixed to use
  `client.query_points(..., query=vec, ...)` and read `.points` off the
  response.
- `tests/conftest.py` and `tests/test_ingest.py` both imported from a
  nonexistent module `ingestion.ingest_csv` (the real file is
  `ingestion_csv.py`) — fixed both.
- `tests/test_ingest.py` also sorted Qdrant points by `int(p.id)`, which
  assumed the old sequential-integer ID scheme; broke once IDs became
  content-derived UUIDs (see §4). Changed to match points to CSV rows by
  `question_text` instead.

## 7. Documentation

- **Added** `README.md` covering setup, running the API, all ingestion paths
  (CSV, canonical PDF, QP+SA pair, CLI), switching embedding backend,
  switching LLM provider, and running tests.
- **Added** architecture diagram and request-flow sequence diagram, authored
  as Mermaid (`docs/diagrams/architecture.mmd`, `docs/diagrams/request_flow.mmd`)
  and rendered to JPEG (`docs/diagrams/architecture.jpg`,
  `docs/diagrams/request_flow.jpg`) via `mermaid-cli`, embedded in the README.
- **Added** `.env.example` — a checked-in template of every env var the app
  uses, with placeholder values and comments on OpenRouter vs. Gemini config.
- **Added** this `CHANGES.md`.

## 8. Grading prompt now includes the question

- **Problem**: `llm_verdict/prompt_compose.py` built the grading prompt from
  the reference textbook answer(s), the student's answer, and the rubric —
  but never included the actual question being asked. The LLM was grading
  the student's answer purely by comparing it to reference answers, with no
  way to judge relevance/completeness against what was actually asked, or
  notice if the student answered a different question entirely.
- **Fixed**:
  - `compose_prompt(question, answer_textbook_list, answer_student, rules_md)`
    now takes `question` as its first argument and includes a
    `**Question:**` section in the prompt.
  - Added a new first grading instruction: check whether the student's
    answer actually addresses the question before comparing it to the
    rubric.
  - `api/main.py` passes `req.question` through to `compose_prompt(...)`.
  - `tests/test_prompt.py` updated for the new signature; asserts the
    question text appears in the composed prompt.
- Verified end-to-end via `TestClient` with a mocked LLM call: confirmed the
  actual submitted question text reaches the prompt handed to
  `get_llm_verdict()`.
- Updated `docs/diagrams/request_flow.mmd`/`.jpg` and the README's intro
  paragraph to reflect that the question is now part of what's sent to the
  LLM.

## 9. Environment / infrastructure (not code)

- Started a persistent Qdrant container (`docker run ... --name rag_mm_qdrant
  -v qdrant_storage:/qdrant/storage qdrant/qdrant`) since no local `qdrant`
  binary exists in this environment (the app's own auto-start fallback in
  `ingestion/qadrant_init.py` doesn't work here).
- Installed system libraries needed for headless Chrome (`libnspr4`,
  `libnss3`, `libasound2t64`) to render Mermaid diagrams to images via
  `mermaid-cli`/Puppeteer.
- Diagnosed (not fixed, since it's user config, not code): the original
  `.env` had a placeholder `OPENROUTER_API_KEY` causing 401s; later, a
  `GEMINI_API_KEY` was set without the corresponding `LLM_PROVIDER=gemini`,
  so requests were still silently going to OpenRouter with no key.
- The sandbox's Docker state (all containers and volumes, including
  `rag_mm_qdrant`) was reset mid-session. Recreated the container and
  re-ingested `qa_content.pdf` + the QP/SA pair to restore working data —
  a reminder that Qdrant data here is not currently persisted anywhere
  durable outside this container's volume.

## 10. Weakness-evaluation layer, feedback-retry loop, and token accounting

- **Problem observed**: live testing of `/validate` found the verdict LLM's
  "Weaknesses" section was not fully trustworthy — two concrete failure
  modes were reproduced: (1) it claimed the student's answer "omits" a point
  the student's answer literally contained (a hallucinated weakness,
  contradicting the same response's own Strengths section), and (2) even
  against the textbook answer copied verbatim, it still manufactured
  criticism under rubric headings that don't apply to a pure
  statutory-definition question (missing case law, missing fact-application),
  then had to self-disclaim it mid-sentence ("not critical here... not a
  significant flaw").
- **Added** a second, independent "checker" LLM call that runs after every
  verdict and scores the Weaknesses section on two criteria: grounded (not
  hallucinated) and applicable (relevant to what this specific question
  calls for). If the score is below a threshold, the verdict is regenerated
  with the checker's critique folded into the prompt (feedback-augmented
  retry, not a blind resend), for up to a capped number of total
  generate+evaluate cycles. On exhausting the cap, the highest-scoring
  attempt is returned, flagged as not having met the threshold rather than
  silently looking like a normal pass.
- **New files**, all under `llm_verdict/`:
  - `verdict_parser.py` — extracts strengths/weaknesses/verdict-text/grade
    from the verdict's free text. Strict heading match first, fuzzy
    line-by-line fallback second (handles the differing real formats
    actually observed, e.g. `**Weaknesses:**` vs `**[Weaknesses]**`), and a
    last-resort "treat the whole response as the weakness section" tier so a
    parsing miss degrades safely instead of raising.
  - `eval_prompt_compose.py` — builds the checker prompt from the four
    required inputs: the extracted weakness section, the question + student
    answer, the rubric, and the textbook/baseline answer(s).
  - `eval_parser.py` — parses the checker's `## SCORE` / `## CRITIQUE`
    response into a float in `[0.0, 1.0]` plus critique text; fails closed
    (score `0.0`, forces a retry) if no score can be found at all, rather
    than silently trusting an unparseable response.
  - `token_accounting.py` — local, `tiktoken`-based per-section prompt token
    counts (question / rubric / student answer / textbook answer /
    instructions), explicitly documented as an approximation since no single
    tokenizer matches every model reachable through OpenRouter.
  - `verdict_orchestrator.py` — `run_verdict_with_evaluation(...)`, the loop
    that ties the above together and records every attempt made.
- **Changed** `verdict_llm.py`: replaced the module-level `LLM_PROVIDER`/
  `LLM_MODEL`/etc. constants (read once at import time) with per-call config
  resolution, so the verdict call and the new checker call can each use a
  different provider/model/key. Added a shared `call_llm(...)` entry point
  used by both, returning a normalized `LLMCallResult(text, usage, provider,
  model)` where `usage` is the same shape regardless of whether it came from
  OpenRouter's `usage` field or Gemini's `usageMetadata`. `get_llm_verdict()`
  kept as a thin back-compat shim.
- **Changed** `prompt_compose.py`: output format tightened from loose
  `[Strengths]/[Weaknesses]/[Rubric-based verdict]` instructions to exact,
  parseable `## STRENGTHS` / `## WEAKNESSES` / `## VERDICT` headings plus a
  literal `Grade: A|B|C|D` line; added an instruction not to raise a rubric
  criterion as a weakness unless it's actually relevant to the question
  asked; added an optional `retry_feedback` param appended when regenerating
  after a failed check.
- **Changed** `api/schemas.py` / `api/main.py`: `/validate` now calls
  `run_verdict_with_evaluation(...)` instead of `get_llm_verdict(...)`
  directly. `ValidateResponse` gained `meets_quality_threshold`,
  `quality_score`, and `attempts` (one entry per cycle actually run, each
  with its verdict text, parsed grade, checker score/critique, and full
  token accounting for both LLM calls) — `verdict` and `exact_matches`
  kept backward compatible.
- **Added** `.env`/`.env.example` vars: `EVAL_THRESHOLD` (default `0.90`),
  `EVAL_MAX_ATTEMPTS` (default `3`), and optional `EVAL_LLM_PROVIDER` /
  `EVAL_LLM_MODEL` / `EVAL_LLM_PROVIDER_BASE_URL` / `EVAL_OPENROUTER_API_KEY`
  / `EVAL_GEMINI_API_KEY`, each falling back to the matching verdict `LLM_*`
  setting when unset so the feature works with zero new config.
- Added `tiktoken` to `requirements.txt` (previously only present
  transitively via other packages, never declared).
- **Changed** `tests/test_api.py`: `patch_llm` now mocks
  `verdict_orchestrator.generate_verdict_response` and
  `...generate_eval_response` (the orchestrator's own imported references,
  not `verdict_llm`'s — plain `monkeypatch.setattr(verdict_llm, ...)` doesn't
  reach a name that was imported via `from module import name` elsewhere).
  Added assertions on the new response fields and per-section token keys.
- Regenerated `qa.csv` from the live Qdrant collection's payloads so
  `tests/conftest.py`'s `sample_qa_df` fixture (which reads it directly) has
  a file to load — it was missing before this session for unrelated reasons
  and blocked `test_api_validate_returns_verdict` regardless of this change.
- **Verified**:
  - `pytest tests/test_api.py tests/test_prompt.py` — 3/3 pass.
  - Live run against the weak paraphrase answer used earlier in the session:
    3 attempts, scores `0.75 → 0.88 → 0.86`, none crossed `0.90` (correctly —
    the answer genuinely omits statutory citations), returned the `0.88`
    attempt with `meets_quality_threshold: false`.
  - Live run against the textbook answer copied verbatim — the direct
    regression test for failure mode (2) above: now scores `1.0` on the
    first attempt, with weaknesses correctly returned as "None identified."
    instead of manufactured-then-disclaimed criticism.
  - Token accounting present and sane on both calls, e.g. one verdict call:
    local per-section estimate `1078` tokens vs. `1146` provider-reported
    prompt tokens — close, as expected for an estimate.
  - A full `pytest tests/` run separately surfaced one pre-existing,
    unrelated failure — `test_ingest.py::test_upserted_payload_matches_csv`
    timed out against Qdrant under heavy concurrent load from its own
    re-ingestion fixture during a 41-minute full-suite run. Not caused by,
    or fixed by, this change.

## 11. Evaluation-layer model configured to Kimi K3; dead `PDF_OUTPUT_PATH` config removed

- **Changed** `.env`: set the weakness-evaluation checker (added in §10) to
  use a genuinely independent model from the verdict generator, instead of
  the same model grading itself:
  ```bash
  EVAL_LLM_PROVIDER=openrouter
  EVAL_LLM_MODEL=moonshotai/kimi-k3
  ```
  Verdict generation stays on `openai/gpt-4.1`; both share the existing
  `OPENROUTER_API_KEY`. Confirmed the exact model slug against OpenRouter's
  own model page before using it (`moonshotai/kimi-k3`, not `moonshot/...`,
  which 404s) rather than guessing.
- **Verified** live: a `/validate` call showed
  `verdict_token_accounting.local_prompt_breakdown.model_name = "openai/gpt-4.1"`
  and `eval_token_accounting.local_prompt_breakdown.model_name =
  "moonshotai/kimi-k3"` on the same response — confirming the two calls are
  actually hitting different models, not just configured to look like it.
  The Kimi K3 checker call also produced a substantive, on-target critique
  (flagged the verdict for penalizing a statutory-definition answer over
  missing case-law citation — exactly the failure mode this layer exists to
  catch).
- **Removed** `PDF_OUTPUT_PATH` (`.env`, `.env.example`) and its
  `config.yaml` counterpart `pdf.output_path` — confirmed via grep across
  the whole codebase that no Python code reads either one.
  `pdf_render/render_pdf.py`, the only script that writes a PDF, has always
  hardcoded its own output path (`out/qa.pdf`, plus `qa.csv`) and was never
  wired up to read either setting. The declared value
  (`./out/qa_content.pdf`) didn't even match what the script actually
  produces — it appears to have been copied from the *ingestion*-side
  `qa_content.pdf` filename elsewhere in the repo, not derived from
  `render_pdf.py`'s real behavior, which is further evidence it was added
  as documentation scaffolding (`CHANGES.md` §7) after `render_pdf.py`
  already existed, rather than being wired up at the same time.
- Also corrected `architecture.md`'s PDF-renderer section, which had
  documented the same fictional configurable path — now describes the
  actual hardcoded `out/qa.pdf` output.
- Confirmed with a repo-wide grep after the edits that no reference to
  `PDF_OUTPUT_PATH` remains anywhere.

## 12. Reliability hardening: real hard timeout, retry-with-backoff, temperature

- **Problem**: live testing surfaced a genuine hang — a real request to
  `deepseek/deepseek-v4-flash` ran 6+ minutes with no error, well past
  `requests.post`'s own `timeout=120`. Root cause: `requests`' `timeout=`
  only resets each time a byte arrives from the server; if a provider
  trickles keep-alive data while a model is still generating, the call can
  run indefinitely without that timeout ever firing.
- **Added** a real wall-clock deadline in `llm_verdict/verdict_llm.py`:
  every LLM call now runs in a background thread via
  `concurrent.futures.ThreadPoolExecutor`, and `call_llm()` waits on
  `future.result(timeout=LLM_CALL_TIMEOUT_SECONDS)` (default `150`,
  configurable in `.env`) — independent of whatever the network layer is
  doing underneath. On timeout, raises a new `LLMTimeoutError` naming the
  provider/model/duration; `executor.shutdown(wait=False)` so the caller
  isn't blocked waiting for the abandoned background thread (Python can't
  forcibly kill a running thread, so it may keep running in the
  background, but the request is no longer stuck on it).
- **Changed** `api/main.py`: catches `LLMTimeoutError` and returns a clean
  `504 Gateway Timeout` with a readable message, instead of an indefinite
  hang or an opaque unhandled-exception `500`.
- **Verified live**: forced a real timeout by restarting the server with
  `LLM_CALL_TIMEOUT_SECONDS=2` against a real ~45s call — came back as
  `HTTP 504` in `2.05s` with `"openrouter/moonshotai/kimi-k3 did not
  respond within 2s"`, confirmed in both the HTTP response and the server
  log (`504 Gateway Timeout`), then restored the real 150s setting.
- **Added** `llm_verdict/verdict_llm.py::_request_with_retry()`: retries a
  request on transient failures only — `429` (rate limit, hit repeatedly
  during this session's heavy testing volume) and `5xx` server errors —
  with exponential backoff and *full jitter* (`random.uniform(0, delay)`,
  not the delay itself, so many simultaneously-failing requests don't all
  retry in lockstep and hit the server again at once). Non-retryable
  errors (auth, bad request) raise immediately. Wired into both
  `_post_openrouter` and `_post_gemini` around just the HTTP
  call+status-check, so retries happen before the outer hard-timeout
  budget is spent.
- **Added** `LLM_TEMPERATURE` / `EVAL_LLM_TEMPERATURE` (both default `0`)
  after live testing showed the same question and answer, sent twice,
  produced not just different wording but different **grades** (`D` vs.
  `C`) — because nothing was telling either model to sample
  deterministically. Threaded through `call_llm()` into both providers'
  payloads (`temperature` for OpenRouter, `generationConfig.temperature`
  for Gemini's differently-shaped API). Not an ironclad determinism
  guarantee, but a large reduction in run-to-run variance.
- **Added** `tests/test_verdict_llm.py`: hard-timeout fires fast on a
  simulated hang and doesn't fire on a fast call; retry succeeds after
  transient 429s, never retries a non-retryable status, and gives up
  cleanly after the configured max retries.
- Diagnosed and ruled out, without a fix required: initial suspicion that
  a `0` weakness-evaluation score after a request might really be a
  disguised timeout — traced end-to-end and confirmed these are
  structurally separate code paths (a timeout raises and aborts the whole
  request with `504`; a `0` score only happens on a *successful* call
  whose text didn't parse) — the observed `0`→`1` score swings between
  identical-content retries were a real model-reliability issue
  (`deepseek-v4-pro` writing self-contradictory critiques, or ignoring the
  scoring format entirely), not a bug in this codebase.

## 13. Plain-English, accessibility-focused grading (phase-1 requirements)

- **Problem**: the target students are largely first-generation learners
  from rural backgrounds with limited exposure to formal English. The
  existing verdict prose ("the response demonstrates a correct but
  skeletal grasp...") is itself hard for that audience to read, and
  nothing checked the student's own spelling, grammar, or sentence
  formation.
- **Added** 3 new rubric criteria to `business_rules.yaml` — Spelling
  Accuracy, Grammatical Correctness, Sentence Formation — in the same
  `{id, name, description, weight}` shape as the existing 10, each
  instructing the model to quote the specific mistake rather than give a
  generic "there are errors" comment. These flow into the prompt
  automatically through the existing `rules_loader.py` pipeline, so
  language issues are graded and folded into Weaknesses like any other
  rubric item (affecting the overall grade, per requirement).
- **Changed** `llm_verdict/prompt_compose.py`'s `INSTRUCTIONS_BOILERPLATE`:
  added an explicit instruction to write the entire response — summary,
  strengths, weaknesses, verdict — in simple, plain English (short
  sentences, everyday words), while still naming the correct legal terms
  where relevant, rather than the previous formal "legal examiner" tone.
- **Added** a new required `## SUMMARY` heading (1–2 short sentences,
  plain English) to the output contract, appearing first, so a student can
  read just that line and understand the overall result.
- **Changed** `llm_verdict/verdict_parser.py`: `VerdictSections` gained a
  `summary` field; both the strict-heading and fuzzy-fallback parsing
  tiers now recognise `## SUMMARY` alongside the existing three headings.
- **Changed** `api/schemas.py` / `api/main.py`: `summary` surfaced both
  per-attempt (`VerdictAttempt.summary`) and at the top level
  (`ValidateResponse.summary`, mirroring how `verdict` already exposes the
  final/best attempt's text).
- **Changed** `tests/test_api.py`: mocked verdict text now includes all
  four headings (previously a bare string) so the new parsing/wiring is
  actually exercised end-to-end, not left to fall through the tier-3
  fallback untested; added assertions for `summary`, `strengths`,
  `weaknesses`, and `grade` extraction.
- **Verified live**: real response (verdict model switched to
  `gemini-2.5-pro` for this run) confirmed the plain-English rewrite
  working as intended — e.g. summary *"You have correctly identified the
  main differences between a private and a public company. However, your
  answer is too short and misses several important legal details..."* —
  second-person, short sentences, no dense legal-examiner phrasing — and
  the new language-quality criterion correctly firing when relevant
  (*"You have no spelling or grammar mistakes"*).
- Did **not** change `eval_prompt_compose.py` — the checker still audits
  only the Weaknesses section for groundedness/applicability, unchanged;
  the new language-quality criteria just become entries the verdict model
  can cite there like any other rubric item.
- Known, disclosed limitation left as-is: `business_rules.yaml`'s `weight`
  field is already dead code (`rules_loader.py` drops it before building
  the prompt — a pre-existing gap noted earlier, not introduced or fixed
  here), so the weights given to the 3 new criteria are cosmetically
  consistent with the existing 10 but don't functionally influence the
  model any more than the existing weights do.

## 14. Cost accuracy fix (Gemini "thinking" tokens) and cost/token breakdowns by model

- **Problem**: manually auditing the cost calculation (recomputing it by
  hand from raw token counts and confirmed OpenRouter pricing) turned up a
  real undercount. `gemini-2.5-pro` is a "thinking" model — it generates
  internal reasoning tokens before writing its visible answer, reported by
  Google as `thoughtsTokenCount` in `usageMetadata`, separate from
  `candidatesTokenCount` (visible output only). `_post_gemini()` only ever
  read `candidatesTokenCount`, so the true billed completion size was
  silently understated — confirmed live: one call's `prompt_tokens +
  completion_tokens` summed to `1644`, but Gemini's own `totalTokenCount`
  said `2782`, a gap of `1,138` real, billed tokens. Per Google's own docs
  ("response pricing is the sum of output tokens and thinking tokens"),
  this made the reported cost for that single call ~4.8x too low.
- **Added** `LLMUsage.thinking_tokens` (`llm_verdict/verdict_llm.py`),
  populated from `thoughtsTokenCount` in `_post_gemini()` only (OpenRouter
  calls don't have this concept). Kept separate from `completion_tokens`
  rather than silently merged in, so the split between visible output and
  reasoning tokens stays visible/auditable rather than hidden.
- **Changed** `llm_verdict/pricing.py::compute_cost()`: bills
  `completion_tokens + (thinking_tokens or 0)` at the completion rate,
  matching Google's actual billing behavior, while `completion_tokens`
  itself keeps its original meaning (visible output only) everywhere else.
- **Added** `cost_by_model` and `total_token_usage` / `tokens_by_model` to
  the `/validate` response (`verdict_orchestrator.py`, `api/schemas.py`,
  `api/main.py`) — cost and token usage (prompt/completion/thinking/total)
  summed both as one grand total across every call in the request, and
  broken down per model name, since verdict and eval frequently use
  different models. Same "don't silently understate" policy as the
  existing `total_cost_usd`: if any single call's usage is unavailable,
  the affected field comes back `None` rather than a partial number.
- **Added** `tests/test_pricing.py` (3 tests: normal cost calc, thinking-
  token billing, unpriced fallback) plus new assertions in
  `tests/test_api.py` for `cost_by_model`, `total_token_usage`, and
  `tokens_by_model` using two distinct mocked model names so the per-model
  grouping is actually exercised, not just merged into one key.
- **Verified live**, three independent ways that all agreed exactly: the
  app's reported totals, the sum of the per-model breakdown recomputed by
  hand, and a manual re-sum from the raw per-attempt provider data — e.g.
  `total_token_usage` `{prompt: 2585, completion: 3457, thinking: 1286,
  total: 7328}` matched the hand-summed `tokens_by_model` entries for
  `gemini-2.5-pro` and `deepseek/deepseek-r1` exactly, and post-fix, prompt
  + completion + thinking tokens for the Gemini call summed to exactly
  Gemini's own `totalTokenCount` (zero gap, versus the earlier 1,138-token
  discrepancy).

## 15. Retry logic extended to cover malformed JSON responses

- **Problem**: live testing surfaced a `JSONDecodeError` crashing a request
  outright — an OpenRouter call returned an apparently-successful response
  whose body wasn't valid JSON. `_request_with_retry()` (added earlier,
  §12) only caught `requests.exceptions.HTTPError` (bad status codes), so
  a malformed-but-"200-level" body fell straight through uncaught, since no
  `HTTPError` is raised when the status itself is fine.
- **Changed** `llm_verdict/verdict_llm.py::_request_with_retry()`: now also
  catches `requests.exceptions.JSONDecodeError` and retries it
  unconditionally (no status code to gate on — an unparseable body on an
  otherwise-successful request is inherently transient) using the same
  exponential-backoff-with-jitter as the status-code retries.
- **Added** 2 tests in `tests/test_verdict_llm.py`: retries past a
  malformed-JSON response and succeeds once a good one comes back; gives
  up cleanly and re-raises after exhausting max retries if it never
  resolves.
- All 13 tests across `test_verdict_llm.py`, `test_api.py`, `test_prompt.py`,
  `test_pricing.py` pass after both changes.

## 16. New `masterminds-test` collection, ingestion mapping verification, and a real fix for Qdrant data loss on every restart

- **Added** a second Qdrant collection, `masterminds-test`, ingested from
  the QP+SA pair already in the repo (`VOID AGREEMENTS(FREECONSENT)-QP.pdf`
  / `-SA.pdf`) via `ingest_cli.py --pair`, producing 13 records. Explained
  (not code, discussion only) how `COLLECTION_NAME` is read identically by
  both ingestion and retrieval, so switching collections is just an env
  var change, and how the existing content-hash-based dedup (`record_id()`
  in `ingestion/qdrant_upsert.py`, UUID5 of `question_text + answer_text +
  subject`) behaves when source content is edited: any change, even one
  character, produces an unrelated ID via the avalanche effect, so the
  old and new versions end up as two separate points rather than one
  being overwritten by the other.
- **Verified** the QP+SA ingestion mapped every sub-part to the correct
  answer, three independent ways: (1) manually read both source PDFs
  page-by-page and confirmed each question's fact pattern matches its
  answer's section citations; (2) re-ran `convert_qp_sa()` fresh and
  diffed every field against what's actually stored in Qdrant — 0
  mismatches across all 13 records; (3) printed the QP mark-sequence
  against the SA's `Question No. X(y)(z)` key-sequence side by side to
  confirm the underlying positional-matching algorithm itself is sound,
  not just coincidentally correct. Found and confirmed **one pre-existing
  typo in the source PDFs** (question 4(c) — the QP prints `[5M]`, the
  SA's own header prints `[3M]`), which the tool's existing `VERIFY`
  warning already flags correctly; content pairing is unaffected.
- **Root-caused and fixed the recurring "Qdrant data disappears after a
  restart" problem** (hit repeatedly all session — every prior recovery
  was reactive re-ingestion, never a real fix). Confirmed via
  `docker inspect`: the running container had **zero volume mounts**, so
  every collection lived only inside that one disposable container's own
  filesystem, gone the moment the container was removed (which this
  sandbox's Docker state appears to do periodically, observed multiple
  times this session).
- **Fixed** by recreating the container with a bind mount into a path
  that has reliably survived every reset this session
  (`/teamspace/studios/this_studio/`, not a plain Docker named volume,
  which would typically live under `/var/lib/docker/...` and likely get
  wiped along with everything else):
  ```bash
  docker run -d -p 6333:6333 -p 6334:6334 \
    -v /teamspace/studios/this_studio/qdrant_data:/qdrant/storage \
    --name rag_mm_qdrant \
    qdrant/qdrant
  ```
  Re-ingested both collections (`student_validator_qa`: 10 points,
  `masterminds-test`: 13 points) to restore what had been lost since the
  last reset.
- **Verified the fix actually works**, not just assumed it: confirmed real
  data files exist on the host filesystem at the mount path (552K,
  outside the container); ran `docker restart rag_mm_qdrant` and confirmed
  both collections came back with their exact original point counts
  afterward.
- Noted for future recovery: if the container is ever removed again, use
  `docker start rag_mm_qdrant` (reuses the same container + volume) rather
  than a fresh `docker run` (which would create a new, unnamed,
  unmounted container and repeat this exact problem) — only re-run the
  full `docker run -v ...` command if `docker ps -a` shows the
  `rag_mm_qdrant` container is gone entirely, not just stopped.
- **Re-verified the persistence fix under real conditions**: the sandbox
  wiped the container again mid-session (not simulated — the same
  recurring reset observed all along). Recreated it pointing at the same
  bind mount and both collections came back automatically with their
  exact original point counts, no re-ingestion needed — confirming the
  fix holds up against the actual failure mode it was built for, not just
  a manual `docker restart` test.

## 17. Eval checker now audits the full verdict, not just the isolated Weaknesses text

- **Problem raised**: the checker only ever received the extracted
  Weaknesses section in isolation — never the Strengths or Verdict/Grade.
  Its "grounded" check (is a weakness claim true of the student's answer)
  was already fully supported, since it separately receives the raw
  `student_answer` text. But it had no way to catch a *different* class of
  error: a weakness that contradicts something the same verdict's own
  Strengths section already credited the student for (a subjective,
  cross-section inconsistency, not a fact checkable against the student's
  raw answer alone).
- **Changed** `llm_verdict/eval_prompt_compose.py::compose_eval_prompt()`:
  signature now takes the full `VerdictSections` object instead of just
  the weaknesses string. The composed prompt shows Strengths and
  Verdict/Grade alongside Weaknesses, each labeled either "score this
  section" or "context only — do not score this section," so the checker
  gets the cross-reference material without its scope actually widening
  to critiquing Strengths/Grade themselves.
- Added a third check criterion, **(c) Internally consistent** — alongside
  the existing (a) grounded and (b) applicable — specifically for
  catching a weakness that contradicts the Strengths section.
- **Changed** `verdict_orchestrator.py`: passes the full `sections` object
  to `compose_eval_prompt(...)` instead of `sections.weaknesses`; the eval
  token-accounting breakdown gained two new tracked sections
  (`strengths_section`, `verdict_section`) alongside the existing ones, so
  the added context is visible in the per-call token/cost breakdown, not
  hidden inside a bigger number.
- **Changed** `tests/test_api.py`: updated the expected eval token-section
  key set to include the two new sections.
- **Verified live**: the eval token breakdown showed real non-zero counts
  for `strengths_section` (58) and `verdict_section` (56) — proof the
  checker is genuinely receiving that context now, not just configured to
  in theory. Confirmed correct behavior on a real case where Strengths
  credited the student for *identifying* two wagering exceptions while
  Weaknesses separately criticized the student for not *explaining* them
  — correctly scored `1.0`/"No issues found." rather than false-flagging
  identify-vs-explain as a contradiction. All 13 tests pass
  (`pytest tests/test_verdict_llm.py tests/test_api.py tests/test_prompt.py
  tests/test_pricing.py`).

## 18. Eval checker: stop padding out `## CRITIQUE` with unrequested
    explanation when `score == 1.00`

- **Problem observed live**: with `EVAL_LLM_MODEL=deepseek/deepseek-r1`, a
  perfect-score eval response correctly wrote `## SCORE\n1.00` but then
  wrote a full "Explanation of Weakness Evaluation:" breakdown under
  `## CRITIQUE` instead of the literal `"No issues found."` the prompt
  asked for. Parsing and scoring both still worked (`eval_parser.py`
  keeps everything after the heading verbatim, so it just passed the
  extra text through), but it wasted completion tokens/cost for no
  functional benefit and violated the prompt's own format contract.
- **Changed** `llm_verdict/eval_prompt_compose.py::EVAL_INSTRUCTIONS_BOILERPLATE`:
  reworded the `## CRITIQUE` instruction to explicitly forbid any content
  beyond the literal `"No issues found."` line when score is `1.00` —
  spelling out that per-claim reasoning belongs in the model's own
  thinking, not the output, and that any trailing text on a perfect score
  is a formatting violation.
- **Verified**: all 13 tests still pass. Live run against the
  `masterminds-test` collection (verbatim-textbook-answer case, 3
  attempts before crossing threshold) showed attempt 3 scoring `1.0` with
  `eval_critique` exactly `"No issues found."` — no trailing explanation.

## 19. Marks-based grading (replacing letter grades) + a third,
    independent "summarization model" for short feedback

- **New requirement**: `/validate` now grades against a caller-supplied
  `max_marks` instead of an abstract A/B/C/D letter grade, and produces
  a separate short, plain-English summary alongside the existing long
  feedback -- generated by a third model whose only job is summarizing,
  distinct from both the verdict model (grades) and the eval model
  (audits the grading).
- **Changed** `api/schemas.py::ValidateRequest`: added a required
  `max_marks: float` field (not `int` -- real exam marks are routinely
  fractional, e.g. 2.5, 0.5). Missing it on a request now fails fast with
  FastAPI's normal 422, rather than silently grading against nothing.
- **Changed** `llm_verdict/prompt_compose.py`: the verdict prompt now
  includes `**Maximum Marks for this Question:** {max_marks}` and a new
  instruction ("Grade strictly and fairly against the Maximum Marks
  given above... do not be generous... marks must never exceed the
  Maximum Marks"). The output contract's final line changed from
  `Grade: A/B/C/D` to `Marks: X/Y` (Y = max_marks, X may be a decimal,
  e.g. `Marks: 3.5/5`).
- **Changed** `llm_verdict/verdict_parser.py`: `VerdictSections.grade`
  (str) replaced with `.marks_awarded` / `.marks_out_of` (both
  `Optional[float]`), parsed from the `Marks: X/Y` line via a new
  `_MARKS_RE` regex (replacing `_GRADE_RE`).
- **Added** `llm_verdict/summary_prompt_compose.py`: a new, minimal
  prompt (no multi-heading parsing needed, since the output is a single
  short block of text) asking for a 2-3 sentence, plain-English
  distillation of the resolved long feedback (Strengths + Weaknesses +
  Verdict/Marks combined) -- explicitly "like a gunshot, not a lecture,"
  must always mention the marks awarded, and must lead with the single
  most important strength/weakness.
- **Added** `llm_verdict/verdict_llm.py::_resolve_summary_config()` /
  `generate_summary_response()`: a third model-config resolver, same
  shape as the verdict/eval resolvers, but deliberately does **not**
  fall back to `LLM_MODEL`/`EVAL_LLM_MODEL` -- it's a distinct
  "summarization model" role, defaulting to `openai/gpt-4o` via
  OpenRouter regardless of whatever verdict/eval models are configured,
  while still being fully overridable via new `SUMMARY_LLM_*` /
  `SUMMARY_OPENROUTER_API_KEY` / `SUMMARY_GEMINI_API_KEY` env vars
  (documented in `.env.example`).
- **Changed** `llm_verdict/verdict_orchestrator.py`:
  - `run_verdict_with_evaluation()` now takes `max_marks` and threads it
    into every verdict-prompt composition (including retries).
  - Restructured the attempt loop to resolve to a single `final_record`
    (via `break` on threshold-met, or a `for...else` fallback to the
    best-scoring attempt) **before** doing any post-loop work, instead
    of duplicating the same return logic in two places.
  - After the loop resolves, makes **one** summarization call on the
    winning attempt only -- never per attempt, since discarded interim
    attempts would otherwise waste summarization cost/latency for
    content nobody sees.
  - `_sum_cost()`, `_cost_by_model()`, `_sum_tokens()`,
    `_tokens_by_model()` all gained an `extra`/`extra_costs` parameter so
    the one-off summarization call's cost/tokens fold into the existing
    grand totals and per-model breakdowns rather than being invisible to
    them.
  - `OrchestrationResult` gained `max_marks`, `short_feedback`,
    `summary_token_accounting`, `summary_duration_seconds`,
    `summary_cost`.
- **Changed** `api/schemas.py` / `api/main.py`: `VerdictAttempt.grade`
  replaced with `marks_awarded`/`marks_out_of`; `ValidateResponse`
  gained `short_feedback`, `max_marks`, `summary_token_accounting`,
  `summary_duration_seconds`, `summary_cost`.
- **Verified live** against the `masterminds-test` collection with a
  real `max_marks: 5` request:
  - Decimal marks worked end-to-end: attempt 1 scored `2.5/5`, attempt 2
    scored `3.0/5.0` -- not rounded to whole numbers.
  - The eval-driven retry loop worked exactly as designed on this
    request: attempt 1's eval score was `0.8` (below the 0.90
    threshold) because the eval model correctly flagged one weakness
    ("numbering skipped (i) to (iii)") as inapplicable per the rubric;
    the critique was fed back in, and attempt 2 dropped that claim and
    scored `1.0`.
  - `short_feedback` came back clean from `gpt-4o` -- one short
    paragraph mentioning the marks, the top strength, and the top
    weakness, with no extra headings or padding.
  - Cost/token accounting was fully populated across all three models
    (verdict, eval, and summary) and the grand totals summed correctly.
  - Separately caught and fixed a related edge case: `max_marks` is
    currently un-validated at the request level, so a client sending
    `max_marks: 0` (e.g. an unfilled required field via `/docs`) got a
    self-contradictory response (`max_marks: 0` at the top level, but
    the verdict model invented its own denominator, e.g. `Marks: 3/10`,
    since it wasn't given a sane value to respect). **Not yet fixed** --
    proposed adding `Field(gt=0)` to `ValidateRequest.max_marks` so this
    fails fast with a 422 instead of producing a nonsensical response.
- All 13 tests pass (`pytest tests/test_verdict_llm.py tests/test_api.py
  tests/test_prompt.py tests/test_pricing.py`), updated for the new
  `max_marks` request field, `marks_awarded`/`marks_out_of` response
  fields, and the mocked third `generate_summary_response()` call.
