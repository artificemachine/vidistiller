# Plan: Presentation Mode Hardening

**Status:** Draft — approved 2026-06-09
**Source docs:** `docs/AUDIT-presentation-mode.md`, HANDOFF.md open items (2026-06-09)

---

## 1. Scope Summary

Hardening the `slide_aware` pipeline that shipped in v1.8.3/v1.9.0. The LLM routing is live and verified (ICM confirmed). This plan closes four remaining gaps:

1. A correctness bug: `cancel_check` in `process_slides` checks `job.status == FAILED`, but the cancel route sets `status = CANCELLED` (not `FAILED`). The check never fires from user cancellation and would only trigger incorrectly if something else sets `FAILED` externally mid-run.
2. Three untested pipeline steps: `ssim_transition_scan`, `layout_detection` (contour-voting path), and `run_full_pipeline` orchestration.
3. Two minor reliability issues: `video_duration` derived from unreliable `CAP_PROP_FRAME_COUNT`; OCR runs twice on ambiguous frames (once in `_add_ocr_context_to_transitions`, once in `final_state_capture`).
4. Frontend toggle sends `is_slide_mode: true` but `Home.test.tsx` has no assertion for it.

**NOT building:** vision pre-pass (`describe_image()` Celery wiring), Next.js CVE upgrade, staging docker-compose topology fix, Alembic wiring.

**Smallest v1:** fix the cancel_check only (Iteration 1). Iterations 2-5 are additive test/reliability work; each ships independently.

---

## 2. Prerequisites

**Dependencies (all already installed):**
- `pytest`, `pytest-mock` -- mocking `cv2.VideoCapture`
- `numpy` -- synthetic frame generation in tests
- Vitest + React Testing Library -- frontend toggle test

**Existing code the work touches:**

| Path | Reason |
|------|--------|
| `backend/app/tasks.py:640-730` | `process_slides` task -- cancel_check lives here |
| `backend/app/routes/jobs.py:827-884` | cancel endpoint -- sets `CANCELLED`, not `FAILED` |
| `backend/app/db/models.py:77` | `slide_status` field on `ProcessingJob` |
| `backend/app/services/slide_detection.py` | All pipeline steps being tested |
| `tests/test_slide_detection.py` | Existing test file -- new classes go here |
| `backend/app/core/config.py:319-327` | SSIM threshold config values used in tests |
| `frontend/app/page.tsx:51,80` | `slideMode` state + `is_slide_mode` in API call |
| `frontend/__tests__/pages/Home.test.tsx` | Existing home test -- add slide toggle test here |

**Risks:**
- Mocking `cv2.VideoCapture` requires patching `app.services.slide_detection.cv2.VideoCapture` -- verify the patch target in iteration 2.
- SIGTERM from Celery revoke kills the process before `_finish()` runs, so `slide_status` may be left in "processing" after a user cancel. Iteration 1 fix doesn't address this (it's a separate concern -- post-cancel cleanup job or a Celery signal handler).

---

## 3. Iterations

#### Iteration 1 - Fix cancel_check signal

**Goal:** Replace `status == FAILED` with `status == CANCELLED` in `process_slides` cancel_check so the check correctly fires on user cancellation and never misfires on genuine failures.

**Shippable on its own?** Yes -- single-line change in one function with targeted tests.

**Source references:**
- `backend/app/tasks.py:681-686` -- current cancel_check body
- `backend/app/routes/jobs.py:878` -- confirms cancel sets `ProcessingStatus.CANCELLED`
- `backend/app/tasks.py:719-727` -- `except Exception` branch that handles genuine failures

**Files touched:**
- `backend/app/tasks.py` (modified)
- `tests/test_process_slides_task.py` (new)

**Commit message:**
`fix(slides): cancel_check must signal on CANCELLED status not FAILED`

**TDD cycle:**
- RED:
  - `tests/test_process_slides_task.py::test_cancel_check_returns_false_during_normal_run` -- mock DB job with `status = PROCESSING`; assert cancel_check returns False
  - `tests/test_process_slides_task.py::test_cancel_check_returns_true_when_user_cancels` -- mock DB job with `status = CANCELLED`; assert cancel_check returns True
  - `tests/test_process_slides_task.py::test_genuine_failure_does_not_trigger_cancel_check` -- run_full_pipeline raises `RuntimeError`; assert `except Exception` branch taken (not `CancelledException`); assert return value is `{"error": ...}`
  - `tests/test_process_slides_task.py::test_failed_status_does_not_trigger_cancel_check` -- mock DB job with `status = FAILED`; assert cancel_check returns False (regression guard for old bug)
- GREEN:
  - Change `cancel_check` body: `return j.status == ProcessingStatus.FAILED` → `return j.status == ProcessingStatus.CANCELLED`
- REFACTOR:
  - Extract `_is_slide_cancelled(db, job_id)` helper mirroring `_is_cancelled` used by the summarization task

**Test pyramid for this iteration:**
- Smoke: 1 -- import `process_slides` task without error
- Unit: 4 (the RED list above) using mock DB session, no real Celery
- Integration: N/A
- State machine: covers 4 status states: PROCESSING (false), CANCELLED (true), FAILED (false), missing job (true)
- Contract: N/A
- Regression: `test_failed_status_does_not_trigger_cancel_check` -- explicit guard against the old bug
- Chaos: N/A
- E2E: N/A
- Performance: N/A
- TDD Parity: 4 tests for 1 modified function + 1 extracted helper = 100%
- Coverage delta: +1%

**Acceptance criteria (binary):**
- [ ] `cancel_check()` returns True only when `status == CANCELLED`
- [ ] `cancel_check()` returns False when `status == FAILED`
- [ ] Genuine pipeline exception routes to `except Exception` branch, not `except CancelledException`
- [ ] All 4 new tests pass; existing test suite green

**Estimated effort:** S

**Blocked by:** None

---

#### Iteration 2 - Unit tests for ssim_transition_scan and layout_detection

**Goal:** Cover the two previously untested pipeline steps with synthetic-frame unit tests, eliminating the largest test gap in the service.

**Shippable on its own?** Yes -- pure test additions, no production code change.

**Source references:**
- `backend/app/services/slide_detection.py:96-159` -- `ssim_transition_scan`
- `backend/app/services/slide_detection.py:37-90` -- `layout_detection`
- `backend/app/core/config.py:319-327` -- threshold values used in assertions
- `tests/test_slide_detection.py:48-69` -- existing `_compute_ssim` tests as pattern for synthetic numpy frames

**Files touched:**
- `tests/test_slide_detection.py` (modified -- add two new test classes)

**Commit message:**
`test(slides): unit coverage for ssim_transition_scan and layout_detection`

**TDD cycle:**
- RED (`ssim_transition_scan`):
  - `TestSSIMTransitionScan::test_identical_frames_produce_no_transitions` -- mock cap returning duplicate frames; assert `transitions == []`
  - `TestSSIMTransitionScan::test_large_change_produces_transition_classification` -- frame pair with SSIM below threshold; assert `classification == "transition"`
  - `TestSSIMTransitionScan::test_ambiguous_range_produces_ambiguous_classification` -- frame pair with SSIM in `[ssim_ambiguous_low, ssim_ambiguous_high]`; assert `classification == "ambiguous"`
  - `TestSSIMTransitionScan::test_cannot_open_video_raises` -- mock `cap.isOpened()` → False; assert `SlideDetectionException`
  - `TestSSIMTransitionScan::test_frame_skip_respects_fps` -- assert `frames_sampled` count matches expected at given fps
- RED (`layout_detection` contour voting):
  - `TestLayoutDetection::test_pip_speaker_box_returns_pip_layout` -- mock `cv2.findContours` to return contours that vote pip; assert result == "pip_speaker"
  - `TestLayoutDetection::test_split_panel_contour_returns_split_layout` -- mock contours that vote split; assert "split_panel"
  - `TestLayoutDetection::test_full_frame_is_default_when_no_votes` -- empty contour list → "full_frame"
- GREEN: no production changes; tests pass against existing implementation
- REFACTOR: None

**Test pyramid for this iteration:**
- Smoke: 1 import check
- Unit: 8 new tests (5 SSIM scan + 3 layout)
- Integration: N/A
- State machine: N/A
- Contract: N/A
- Regression: N/A
- Chaos: `test_cannot_open_video_raises` -- bad video path chaos for ssim_transition_scan
- E2E: N/A
- Performance: N/A
- TDD Parity: 8 tests cover 2 previously zero-coverage public methods = 100%
- Coverage delta: +3%

**Acceptance criteria (binary):**
- [ ] 8 new tests present and green
- [ ] No real cv2 video I/O in any test (all mocked)
- [ ] Existing 351+ slide detection tests unchanged and passing

**Estimated effort:** M

**Blocked by:** None (Iteration 1 not required)

---

#### Iteration 3 - Integration test for run_full_pipeline orchestration

**Goal:** Test the full pipeline orchestrator end-to-end with mocked steps, proving correct stage ordering, incremental-build DB linking, and `slide_status` persistence.

**Shippable on its own?** Yes -- pure test addition.

**Source references:**
- `backend/app/services/slide_detection.py:439-581` -- `run_full_pipeline`
- `backend/app/db/models.py:334-360` -- `Slide` and `SlideDetectionMetadata` models
- `tests/test_slide_detection.py` -- existing `service` fixture pattern

**Files touched:**
- `tests/test_slide_detection.py` (modified -- add `TestRunFullPipeline` class)

**Commit message:**
`test(slides): integration tests for run_full_pipeline orchestration`

**TDD cycle:**
- RED:
  - `TestRunFullPipeline::test_pipeline_calls_all_steps_in_order` -- mock each stage method; assert call order via `call_args_list`
  - `TestRunFullPipeline::test_incremental_builds_linked_via_parent_slide_id` -- stub `slide_grouping` to return one non-incremental + one incremental slide; assert `parent_slide_id` FK is set on the persisted `Slide` object
  - `TestRunFullPipeline::test_cancel_mid_pipeline_raises_cancelled_exception` -- inject `cancel_check` returning True after step 2; assert `CancelledException` propagates
  - `TestRunFullPipeline::test_missing_video_raises_slide_detection_exception` -- job with no `video_file_path`; assert `SlideDetectionException`
  - `TestRunFullPipeline::test_metadata_row_committed` -- after a clean run, assert `SlideDetectionMetadata` was added and `db.commit()` was called
- GREEN: no production changes; tests pass against existing orchestrator
- REFACTOR: None

**Test pyramid for this iteration:**
- Smoke: 1 import check
- Unit: N/A (this is integration-level by nature)
- Integration: 5 new tests -- full orchestration path with mocked sub-services and mocked DB session
- State machine: happy path + cancel path covered
- Contract: `test_metadata_row_committed` verifies `SlideDetectionMetadata` DB contract
- Regression: `test_missing_video_raises_slide_detection_exception` -- guards early-exit path
- Chaos: `test_cancel_mid_pipeline_raises_cancelled_exception` -- mid-pipeline cancellation injection
- E2E: N/A
- Performance: N/A
- TDD Parity: 5 tests for 1 previously untested public method = 100%
- Coverage delta: +4%

**Acceptance criteria (binary):**
- [ ] 5 new tests present and green
- [ ] No real DB, no real video I/O in any test
- [ ] `parent_slide_id` FK population explicitly asserted
- [ ] Full test suite green

**Estimated effort:** M

**Blocked by:** Iteration 1 (cancel_check fix changes what signals to simulate in `test_cancel_mid_pipeline`)

---

#### Iteration 4 - video_duration reliability fix + OCR dedup cache

**Goal:** Fix `video_duration` for containers where `CAP_PROP_FRAME_COUNT` reports zero, and eliminate the redundant second OCR pass on ambiguous frames.

**Shippable on its own?** Yes -- self-contained correctness/perf fixes.

**Source references:**
- `backend/app/services/slide_detection.py:484` -- `video_duration = CAP_PROP_FRAME_COUNT / FPS`
- `backend/app/services/slide_detection.py:634-661` -- `_add_ocr_context_to_transitions` (first OCR pass)
- `backend/app/services/slide_detection.py:393-398` -- `final_state_capture` OCR (second pass)
- `backend/app/services/slide_detection.py:439-581` -- `run_full_pipeline` orchestrator (wires the cache)

**Files touched:**
- `backend/app/services/slide_detection.py` (modified)
- `tests/test_slide_detection.py` (modified -- 2 regression tests)

**Commit message:**
`fix(slides): reliable video_duration fallback + OCR frame-index cache`

**TDD cycle:**
- RED:
  - `TestRunFullPipeline::test_video_duration_nonzero_when_frame_count_zero` -- mock `CAP_PROP_FRAME_COUNT = 0`, mock `CAP_PROP_POS_MSEC = 60000`; assert `video_duration == 60.0`
  - `TestAddOcrContext::test_ocr_not_called_twice_for_ambiguous_frame` -- call `_add_ocr_context_to_transitions` then `final_state_capture` with the same frame index; assert `_extract_ocr_text` called once, not twice
- GREEN:
  - Extract `_get_video_duration(cap)`: try `CAP_PROP_FRAME_COUNT / FPS`; if result is 0, seek to end via `cap.set(CAP_PROP_POS_AVI_RATIO, 1.0)` and read `CAP_PROP_POS_MSEC / 1000.0`
  - `_add_ocr_context_to_transitions` returns a `Dict[int, Optional[str]]` frame_ocr_cache keyed by frame_index
  - `run_full_pipeline` passes the cache into `final_state_capture`; `final_state_capture` accepts optional `frame_ocr_cache` kwarg and skips re-OCR for cached indices
- REFACTOR:
  - `_get_video_duration(cap)` is the only new private method -- already cleanly named

**Test pyramid for this iteration:**
- Smoke: 1 import check
- Unit: 2 regression tests
- Integration: N/A
- State machine: N/A
- Contract: N/A
- Regression: both tests are regression guards for the two bugs
- Chaos: `test_video_duration_nonzero_when_frame_count_zero` -- pathological container input
- E2E: N/A
- Performance: `test_ocr_not_called_twice` validates the OCR halving (implicitly a perf test)
- TDD Parity: 2 tests for 2 modified methods = 100%
- Coverage delta: +1%

**Acceptance criteria (binary):**
- [ ] `video_duration` is non-zero when `CAP_PROP_FRAME_COUNT == 0` and `CAP_PROP_POS_MSEC` is available
- [ ] `_extract_ocr_text` called at most once per frame index across the full pipeline run
- [ ] 2 new tests present and green
- [ ] Full test suite green

**Estimated effort:** S

**Blocked by:** Iteration 3 (reuses `TestRunFullPipeline` fixture class)

---

#### Iteration 5 - Frontend slide mode toggle test

**Goal:** Assert that clicking the slide mode toggle and submitting the form sends `is_slide_mode: true` in the API payload.

**Shippable on its own?** Yes -- pure test addition.

**Source references:**
- `frontend/app/page.tsx:51` -- `const [slideMode, setSlideMode] = useState(false)`
- `frontend/app/page.tsx:80` -- `is_slide_mode: slideMode` in the `POST /api/jobs` body
- `frontend/__tests__/pages/Home.test.tsx` -- existing home tests as pattern

**Files touched:**
- `frontend/__tests__/pages/Home.test.tsx` (modified)

**Commit message:**
`test(frontend): assert slide mode toggle sets is_slide_mode in API payload`

**TDD cycle:**
- RED:
  - `Home.test.tsx::test_slide_mode_toggle_off_by_default` -- render home page; assert slide toggle is unchecked/off by default
  - `Home.test.tsx::test_slide_mode_sends_is_slide_mode_true` -- mock `fetch`; click slide toggle; submit form; assert `fetch` called with body containing `"is_slide_mode": true`
  - `Home.test.tsx::test_no_slide_mode_sends_is_slide_mode_false` -- same without clicking toggle; assert body contains `"is_slide_mode": false`
- GREEN: no production changes; tests pass against existing implementation
- REFACTOR: None

**Test pyramid for this iteration:**
- Smoke: 1 -- home page renders without error
- Unit: 3 new tests (the RED list)
- Integration: N/A
- State machine: toggle off → on transition covered
- Contract: `test_slide_mode_sends_is_slide_mode_true` verifies the API contract shape
- Regression: N/A
- Chaos: N/A
- E2E: N/A
- Performance: N/A
- TDD Parity: 3 tests for 1 previously untested toggle path = 100%
- Coverage delta: +1% frontend

**Acceptance criteria (binary):**
- [ ] Slide toggle is off by default
- [ ] After clicking the toggle, the API call body contains `is_slide_mode: true`
- [ ] Without clicking the toggle, the API call body contains `is_slide_mode: false`
- [ ] 3 new tests present and green; existing home tests unchanged

**Estimated effort:** S

**Blocked by:** None

---

## 4. Test Inventory Summary

| Iter | Smoke | Unit | Integration | State machine | Contract | Regression | Chaos | E2E | Performance | TDD Parity | Coverage delta |
|------|-------|------|-------------|---------------|----------|------------|-------|-----|-------------|------------|----------------|
| 1 | 1 | 4 | 0 | 4 | 0 | 1 | 0 | 0 | 0 | 100% | +1% |
| 2 | 1 | 8 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 100% | +3% |
| 3 | 1 | 0 | 5 | 2 | 1 | 1 | 1 | 0 | 0 | 100% | +4% |
| 4 | 1 | 2 | 0 | 0 | 0 | 2 | 1 | 0 | 1 | 100% | +1% |
| 5 | 1 | 3 | 0 | 1 | 1 | 0 | 0 | 0 | 0 | 100% | +1% |

Total new tests: 23 backend + 3 frontend = 26. Estimated backend coverage delta: ~+9%.

---

## 5. End-to-End Definition of Done

**Acceptance criteria (deduplicated):**
- [ ] `cancel_check()` returns True only when `status == CANCELLED`; returns False on FAILED
- [ ] Genuine pipeline exception routes to `except Exception` branch, not `CancelledException`
- [ ] `ssim_transition_scan` covered for all 3 SSIM bands + bad-video path
- [ ] `layout_detection` contour-voting paths covered (pip, split, full_frame)
- [ ] `run_full_pipeline` orchestration test verifies step ordering and incremental-build FK linking
- [ ] `video_duration` is non-zero for containers where `CAP_PROP_FRAME_COUNT` returns 0
- [ ] OCR called at most once per frame index across the full pipeline run
- [ ] Frontend toggle is off by default; toggling it causes `is_slide_mode: true` in the API call
- [ ] All 26 new tests pass; existing test suite unchanged

**Demo script:**
1. Submit a presentation-style YouTube URL with the slide mode toggle ON.
2. Poll `GET /api/jobs/{id}/status` until `slide_status == "completed"`.
3. Confirm `GET /api/jobs/{id}/slides` returns slides with `is_incremental_build: false` for real transitions and `true` for bullet-reveal slides, each with `parent_slide_id` set.
4. Cancel a running slide job via the UI; confirm `status == "cancelled"`, not `"failed"`.

**Test commands:**
```bash
# Backend
PYTHONPATH=backend .venv/bin/python -m pytest \
  tests/test_slide_detection.py \
  tests/test_process_slides_task.py \
  -v --tb=short

# Frontend
cd frontend && npm test -- --run __tests__/pages/Home.test.tsx
```

---

## 6. Out of Scope

| Item | Reason |
|------|--------|
| Vision pre-pass (`describe_image()` Celery wiring) | Separate feature, tracked in HANDOFF |
| Next.js 7 moderate CVEs | Requires major version bump, separate PR |
| Staging docker-compose topology | Only relevant if staging is stood back up |
| Alembic wiring | Schema built via `create_all()`; no migration needed for this work |
| Tesseract GPU / performance | Deployment-level concern, not addressable in the service |
| Post-SIGTERM slide_status cleanup | Celery revoke kills the process; `_finish()` never runs. Fix requires a Celery signal handler or a startup-time recovery scan. Deferred. |

---

## 7. Open Questions

None -- all resolved during plan authoring.

- Cancel signal: route sets `CANCELLED` (not `FAILED`). cancel_check fix is `status == CANCELLED`.
- Frontend toggle: `app/page.tsx:51,80`. Test goes in `__tests__/pages/Home.test.tsx`.
