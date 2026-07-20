# PLAN — Two-Pass JSON Parsing Bug Fix

> Generated 2026-06-08. Executed with `/plan-implement docs/PLAN-two-pass-json-fix.md`.

## 1. Scope summary

Fix the two-pass summarization pipeline so Pass 1 (`_analyze_transcript`) succeeds instead of always raising `json.JSONDecodeError: Extra data` and falling back to the lower-quality single-pass pipeline. The root cause is that `_parse_analysis_response()` calls `json.loads()` on the LLM's raw response, but the LLM frequently appends trailing text (explanations, pleasantries) after the closing `]` of the JSON array. The fix extracts just the JSON array substring before parsing, making Pass 1 robust to real LLM output patterns.

**Smallest v1:** Update `_parse_analysis_response()` to find the outermost `[` / `]` pair and parse only that substring, falling through to the existing error handling if no valid array is extractable.

**Not in scope:** Prompt engineering to prevent trailing text (the LLM is chatty by nature — extraction is cheaper and more reliable than prompt whack-a-mole). Not touching Pass 2 or the fallback pipeline. Not fixing the vision pre-pass. Not touching the Next.js CVEs.

**Source design:** HANDOFF.md line 44 — "Two-pass summarization JSON parsing bug — Pass 1 always returns 'Extra data' error, falls back to single-pass. Pre-existing, not investigated."

## 2. Prerequisites

**Dependencies:** None. The fix is pure Python string manipulation in the existing `json` module.

**Existing code touched:**

| File | Why |
|------|-----|
| `backend/app/services/llm.py` (lines 899–944) | `_parse_analysis_response()` — the buggy method |
| `tests/test_llm_two_pass.py` (lines 90–154) | `TestParseAnalysisResponse` — needs new test cases |
| `HANDOFF.md` (line 44) | Strike the open follow-up after fix verified |

**Risks:**
- LLM might return nested JSON objects inside the array (e.g., `{"items": [...]}`) where a naive bracket-pair scan picks the wrong `[`. Mitigation: scan for the outermost JSON array character by tracking nesting depth, not by `str.find("]")`.
- The LLM might return array fragments or malformed JSON where extraction still fails — that's fine, existing fallback already handles it.

## 3. Iterations

### Iteration 1 — Extract JSON array before parsing

**Goal:** `_parse_analysis_response()` handles trailing text after valid JSON arrays by extracting the `[...]` substring before calling `json.loads()`.

**Shippable on its own?** Yes — Pass 1 succeeds where it previously failed, the two-pass pipeline activates, summarize quality improves immediately.

**Source references:**
- `backend/app/services/llm.py:899–944` — current `_parse_analysis_response()` implementation
- `tests/test_llm_two_pass.py:90–154` — existing parsing tests to extend

**Files touched:**
- `backend/app/services/llm.py` (modified) — `_parse_analysis_response()`
- `tests/test_llm_two_pass.py` (modified) — new test cases in `TestParseAnalysisResponse`
- `HANDOFF.md` (modified) — remove line 44

**Commit message:**
`fix(llm): extract JSON array from Pass 1 response before parsing to handle trailing text`

**TDD cycle:**

- **RED** (failing tests to write first):
  - `tests/test_llm_two_pass.py::TestParseAnalysisResponse::test_trailing_text_after_json` — valid JSON array followed by `"\nHere is the analysis."` parses successfully, returns correct `SectionAnalysis`
  - `tests/test_llm_two_pass.py::TestParseAnalysisResponse::test_fenced_json_with_trailing_text` — `` ```json\n[...]\n```\nHope this helps! `` parses successfully
  - `tests/test_llm_two_pass.py::TestParseAnalysisResponse::test_nested_objects_in_array` — array containing objects with nested `{}` still extracts the correct outer `[...]`
  - `tests/test_llm_two_pass.py::TestParseAnalysisResponse::test_no_brackets_falls_through` — response with zero brackets still raises `ValueError` ("invalid JSON"), not `IndexError` or crash

- **GREEN** (minimal implementation):
  - Add a helper `_extract_json_array(text: str) -> str` that scans character-by-character tracking bracket nesting depth (`[` → depth++, `]` → depth--) and returns `text[start_idx:end_idx+1]` where depth first reached 0
  - In `_parse_analysis_response()`, after stripping code fences, call `_extract_json_array(cleaned)` before `json.loads()`
  - If extraction returns empty string, fall through to existing `json.loads(cleaned)` which will raise `json.JSONDecodeError` → caught by existing `except` → raises `ValueError`
  - Keep all existing stripping logic (code fences, whitespace) unchanged

- **REFACTOR** (cleanup after GREEN):
  - Move `_extract_json_array` to a module-level helper (it's stateless and only depends on `str`)
  - Rename local `cleaned` to `stripped` inside `_parse_analysis_response` to distinguish from extracted

**Test pyramid for this iteration:**
- **Smoke:** Import `LLMService` and call `_parse_analysis_response('[{"title":"Test","start_timestamp":"00:00:00","end_timestamp":"00:01:00","content_type":"intro","key_topics":[]}]')` — returns a list of 1 `SectionAnalysis` without error
- **Unit:** 4 tests (listed in RED above) + 7 existing tests in `TestParseAnalysisResponse` remain green
- **Integration:** Existing `TestFallbackToSinglePass::test_pass1_invalid_json_falls_back` and `test_pass1_failure_falls_back` in `test_llm_two_pass.py` remain green — proves the full pipeline still works end-to-end
- **State machine:** N/A — no state machine in JSON parsing
- **Contract:** N/A — no new env vars or config keys
- **Regression:** Verify existing `TestSummarizeTranscriptSections::test_two_pass_pipeline_success` in `test_llm_two_pass.py:367` passes with updated parser (this test mocks LLM to return valid JSON → must still produce two-pass output)
- **Chaos:** `test_no_brackets_falls_through` (listed in RED) covers the empty/missing-bracket case; `test_non_json_raises` (existing) covers garbage input
- **E2E:** N/A — this is a parsing fix, verified by integration tests
- **Performance:** N/A — bracket scanning is O(n) on response size (typically <5 KB), no measurable latency impact
- **TDD Parity:** 100% — all new parsing behavior has a direct test; `_extract_json_array` helper tested indirectly through `_parse_analysis_response` (acceptable since it's a private helper)
- **Coverage:** +1% → lines 899–944 gain full branch coverage for the new extraction path

**Acceptance criteria (binary):**
- [ ] `_parse_analysis_response('[{"title":"X","start_timestamp":"00:00:00","end_timestamp":"00:01:00","content_type":"intro","key_topics":[]}]\nExtra text here.')` returns one `SectionAnalysis` with title "X" — no exception
- [ ] `` _parse_analysis_response('```json\n[...]\n```\nThank you!') `` returns valid result (fenced + trailing)
- [ ] `_parse_analysis_response('not json at all')` still raises `ValueError` — existing error contract preserved
- [ ] `test_pass1_invalid_json_falls_back` still passes — fallback pipeline untouched
- [ ] `pytest tests/test_llm_two_pass.py -v` — all tests green (existing + new)

**Estimated effort:** S (<2h)

**Blocked by:** None

## 4. Test inventory summary

| Iter | Smoke | Unit | Integration | State machine | Contract | Regression | Chaos | E2E | Performance | TDD Parity | Coverage Δ |
|------|-------|------|-------------|---------------|----------|------------|-------|-----|-------------|------------|------------|
| 1    | 1     | 4    | 1           | 0             | 0        | 1          | 1     | 0   | 0           | 100%       | +1% → 74%  |

## 5. End-to-end definition of done

**Deduplicated acceptance criteria:**
1. Trailing text after valid JSON array parses successfully
2. Fenced JSON with trailing text parses successfully
3. Nested objects inside the array don't confuse bracket extraction
4. Responses with no brackets still raise `ValueError`
5. Existing two-pass pipeline integration tests pass
6. Fallback pipeline behavior unchanged (invalid JSON still falls back to single-pass)

**Demo script** (manual verification on production):
1. Submit a job to vidistiller with a short YouTube video
2. Click "Summarize"
3. Inspect the Celery worker logs — verify `"Starting LLM summarization..."` appears followed by `"Summarization completed"` (no `"Two-pass pipeline failed, falling back to single-pass"` warning)
4. Verify the summary output contains structured section headers (`## Section Title`) with paragraph + bullet content — not raw timestamped transcript lines

**Test command that must return green:**
```bash
PYTHONPATH=backend pytest tests/test_llm_two_pass.py -v
```

## 6. Out of scope

| Item | Reason |
|------|--------|
| Prompt engineering to suppress trailing text | LLMs are inherently chatty; extraction is more robust and maintainable |
| Fixing Pass 2 (`_summarize_section_adaptive`) failures | Separate issue — Pass 2 failures are LLM timeout/quality, not parsing |
| Vision pre-pass (`describe_image()` wiring) | Separate feature — needs its own plan |
| Next.js CVE bump | Separate maintenance task — needs its own plan |
| Making two-pass pipeline async/non-blocking | Already handled by Celery task |

## 7. Open questions

None — the bug is understood, the fix is mechanical, the tests have clear boundaries.
