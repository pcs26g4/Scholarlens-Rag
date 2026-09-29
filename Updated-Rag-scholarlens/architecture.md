---

# RAG Student-Answer Validator: System Architecture Design

---

## 1. Module Layout

```
rag_qa_validator/
│
├── ingestion/
│   ├── ingest_md.py                # Ingest qa_content.md, parse Q/As, embed question, upsert to Qdrant
│   ├── ingest_csv.py               # Ingest CSV with Q/A/S, embed question, upsert to Qdrant
│   └── qadrant_init.py             # Qdrant local (docker or local_mode) bootstrap utility
│
├── retrieval/
│   ├── retriever.py                # Embedding + query top_k from Qdrant (used by API)
│
├── llm_verdict/
│   ├── rules_loader.py             # Load and parse business_rules.yaml
│   ├── prompt_compose.py           # Compose LLM system prompt/message
│   ├── verdict_llm.py              # Call OpenAI-compatible LLM via OpenRouter API
│
├── pdf_render/
│   ├── render_pdf.py               # Render qa_content.md to PDF
│
├── api/
│   ├── main.py                     # FastAPI app: /validate endpoint
│   ├── schemas.py                  # Pydantic request/response schemas
│
├── tests/
│   ├── test_ingest.py              # Ingestion routines
│   ├── test_retrieve.py            # Retrieval routines
│   ├── test_api.py                 # End-to-end API tests
│
├── qa_content.md                   # Source Q&A content
├── business_rules.yaml             # Assessment/business rules
├── config.yaml                     # Model and system config
├── .env                            # Holds secrets/env vars
└── README.md
```

---

## 2. Data Flow

1. **Ingestion**
    - Start/init local Qdrant server (container or memory mode).
    - Parse `qa_content.md`/CSV into structured records.
    - For each entry, embed `question_text` (only).
    - Upsert into Qdrant collection with vector and payload (`question_text`, `answer_text`, `subject`).

2. **PDF Generation**
    - Convert `qa_content.md` to styled PDF via `render_pdf.py`.

3. **Query/Validation**
    - `/validate` FastAPI endpoint receives JSON: `{student_answer, question}`.
    - Embed question, search Qdrant (top_k=2 by cosine similarity).
    - If top match sim > 0.8, aggregate all textbook answers, append student answer, load business rules.
    - Compose LLM prompt.
    - Call OpenRouter LLM API.
    - Return verdict from LLM in schema.

---

## 3. Embedding Strategy

- **Model:** Sentence-Transformers (configurable, default: `all-MiniLM-L6-v2`).
- **Text Embedded:** Only the canonical Q&A bank `question_text`.
- **Embedding Utility:** Through LlamaIndex embedding wrapper for consistency.
- **Dimensionality:** Set by model (e.g., 384).
- **Normalization:** Embeddings normalized for cosine similarity.

---

## 4. Qdrant Collection Schema

**Collection Name:** `student_validator_qa`

- **Vector size:** 384 (default for `all-MiniLM-L6-v2` – configurable)
- **Distance Metric:** Cosine

**Payload per point:**
```json
{
  "question_text": "<str>",
  "answer_text": "<str>",
  "subject": "<str>"
}
```
**Primary key:** Auto (Qdrant's UUID or insertion index).

---

## 5. Config/Environment Variables

**.env:**
```
OPENROUTER_API_KEY=sk-xxxxxxx
QDRANT_HOST=localhost
QDRANT_PORT=6333
EMBED_MODEL=all-MiniLM-L6-v2
COLLECTION_NAME=student_validator_qa
LLM_PROVIDER_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=openai/gpt-3.5-turbo-1106
TOP_K=2
```

**config.yaml:**
```yaml
embed_model: all-MiniLM-L6-v2
qdrant:
  host: localhost
  port: 6333
  collection_name: student_validator_qa
llm:
  base_url: https://openrouter.ai/api/v1
  model: openai/gpt-3.5-turbo-1106
retrieval:
  top_k: 2
  similarity_threshold: 0.8
pdf:
  output_path: ./out/qa_content.pdf
```

---

## 6. API Contract

**Request (`/validate`):**
```json
{
  "question": "What is the Goods and Services Tax (GST) in India? ...",
  "student_answer": "GST is the ... [student response]."
}
```

**Response:**
```json
{
  "verdict": "The student's answer is substantially correct. It identifies the nature of GST ...",
  "exact_matches": [
    {
      "question_text": "...",
      "answer_text": "...",
      "subject": "Indian Business Law",
      "similarity": 0.91
    },
    {
      "question_text": "...",
      "answer_text": "...",
      "subject": "Indian Business Law",
      "similarity": 0.84
    }
  ]
}
```

**Error Response:**
```json
{
  "detail": "No semantically similar question found in Q&A bank (similarity < 0.80)."
}
```

---

## 7. Qdrant Upsert Data Example

```python
point = {
    "id": "uuid-or-int",
    "vector": [float, ...],  # 384d
    "payload": {
        "question_text": "...",
        "answer_text": "...",
        "subject": "Indian Business Law"
    }
}
```

---

## 8. Prompt-Composition Logic

**Inputs:**

- `answer-textbook`: List of answers from all Qdrant matches with sim > 0.80
- `answer-student`: Student's answer input
- `rules-context`: YAML/markdown section with all rules from `business_rules.yaml`.

**System Prompt (Polished & Complete):**

```
You are a rigorous legal examiner for Indian Business Law. Your task is to compare a student's answer to a corresponding model textbook answer and evaluate the student's response according to an explicit assessment rubric.

**Textbook Answer(s):**
{answer-textbook}

**Student's Answer:**
{answer-student}

**Assessment Rubric:**
{rules-context}

Instructions:

1. Thoroughly compare the student's answer to the textbook answer(s), focusing not only on correctness, but also depth, clarity, structure, and accuracy according to the above rubric.
2. Explicitly reference relevant rubric criteria in your evaluation. Do not simply echo text; instead, identify strengths, weaknesses, missing elements, legal misapplications, or exemplary features.
3. Conclude by stating whether, under the rubric, the student answer would likely be marked as (A) Excellent, (B) Satisfactory, (C) Needs Improvement, or (D) Inadequate, with a concise justification.
4. Response structure: [Strengths], [Weaknesses], [Rubric-based verdict].

Maintain an objective, professional tone appropriate for formal legal assessment. Do not invent facts outside the supplied content.
```

**Prompt Assembly Logic:**

- For each returned match within sim > 0.8: collect `answer_text` → form `{answer-textbook}` (multi-answer possible).
- Load `business_rules.yaml`, flatten as markdown (names and descriptions under headings) → `{rules-context}`.
- Insert `student_answer` as `{answer-student}`.
- Fill the prompt template.
- Send as the system message (LLM API; no user role for this use case).

---

## 9. Testing Strategy (`tests/`)

- **test_ingest.py:** Validate correct Q&A parsing, vector dimensions, upserts, duplicate avoidance.
- **test_retrieve.py:** Retrieval with synthetic and real queries, sim score assertions, payload integrity, thresholding.
- **test_api.py:** Full API roundtrip: mock LLM, test verdict logic, payload/response validation, error conditions.
- **Fixtures:** Sample Q&A data, student answers (right/wrong), rules YAML, fastapi test client.

---

## 10. PDF Renderer

- **render_pdf.py:** 
    - Input: `qa_content.md`
    - Output: Styled PDF at the hardcoded path `out/qa.pdf`, plus `qa.csv`
    - Stack: markdown → HTML → PDF (`markdown`, `weasyprint`)

---

## 11. Extensibility/Wiring

- All component configs parameterized (`config.yaml` + `.env`).
- Model swap (embedding/LLM) via config alone.
- Qdrant can auto-launch (docker or local-mode) if not live, on first ingest.

---

## 12. Security/Secrets Handling

- No API keys checked into code.
- `.env` must be loaded by all scripts/services using secrets.

---

## 13. Edge Case Handling

- On retrieval, if top result sim < 0.8: API returns error, no LLM call.
- If multiple matches > 0.8: all are used in prompt's answer-textbook section.

---

**End of Design Doc**