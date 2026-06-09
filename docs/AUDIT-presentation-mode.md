# Presentation Mode — Code Review

Review of the `slide_aware` processing pipeline ("presentation mode").

## Overview

The chain works end to end:

```
home toggle → is_slide_mode → processing_mode="slide_aware"
  → process_slides task
  → SlideDetectionService.run_full_pipeline
      layout detection
      → SSIM transition scan
      → LLM disambiguation
      → slide grouping
      → final-state frame capture + OCR
      → transcript alignment
      → persist slides + metadata
  → SlidesGallery in the job view
```

The SSIM / grouping / alignment core is sound and well-tested. One finding guts the feature in production.

## 🔴 Critical — the LLM disambiguation step is dead in prod

Same root cause as the summarization bug fixed earlier in the session.

`slide_detection.py:181` — `llm_ambiguity_classification` calls `self.settings.ollama.base_url`, which defaults to `http://localhost:11434` (`config.py:35`), via Ollama's `/api/generate`. In the container there is no localhost Ollama, so:

- Every `requests.post` throws → caught at `slide_detection.py:227` → silently falls back to `"transition"`.
- Net effect: **every incremental build (bullets revealed one-by-one) is misclassified as a brand-new slide** → slide explosion, near-duplicate slides. The entire purpose of the LLM step (INCREMENTAL vs TRANSITION) is nullified, silently.
- Two more reasons it cannot work even if pointed at the fleet:
  - default model is `"mistral"` (fleet runs `gemma4-31b`)
  - `/api/generate` is Ollama-specific — it 404s against vLLM's OpenAI-compatible `/v1`. It bypasses the `llm_providers.py` abstraction entirely.

**Fix:** route this through `build_provider()` / the fleet like summarization, not a hand-rolled Ollama call.

## 🟠 Design

- **Dead config + dead code path.** `incremental_ssim_threshold = 0.95` is never read. It was presumably meant to be the cheap non-LLM fallback ("SSIM ≥ 0.95 → incremental") that would have made the critical bug above non-fatal. It was never wired.
- **`parent_slide_number` / `is_incremental_build` are never populated.** `slide_grouping` *drops* incrementals (`continue` at line 255), so the parent-linking block at `slide_detection.py:515-519` and the `parent_slide_id` schema column are dead. Incremental builds vanish instead of becoming children.
- **Failure is indistinguishable from success.** `process_slides` swallows all errors and marks the job `COMPLETED` (`tasks.py:666-679`). Reasonable ("slides are optional enrichment"), but there is no `slide_status`, so a fully-failed slide run looks identical to a clean one in the UI.
- **Cancellation overloads `FAILED`.** `cancel_check` treats `status == FAILED` as the cancel signal — collides with genuine failures.

## 🟡 Performance / minor

- `final_state_capture` + `_add_ocr_context_to_transitions` use repeated `cap.set(POS_FRAMES)` random seeks (slow and keyframe-imprecise on compressed video); ambiguous frames get OCR'd twice (no cache). Tesseract is the bottleneck.
- `video_duration` relies on `CAP_PROP_FRAME_COUNT` — unreliable across codecs / containers.

## Test gaps

The fragile, network-dependent parts are exactly what is untested:

- `llm_ambiguity_classification` — 0 tests
- `ssim_transition_scan` — untested
- `run_full_pipeline` orchestration — untested
- `layout_detection` contour-voting — only the invalid-video default is tested
- Frontend has no test asserting the toggle sends `is_slide_mode: true`
