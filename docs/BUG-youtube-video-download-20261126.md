# Bug: YouTube video download and snapshot capture fail

Found: 2026-11-26. Affected: backend images that ship `yt-dlp` 2026.8.19, observed on the production deployment.

## Symptoms

- `POST /api/snapshots/capture` returns 503. The API logs `On-demand video download failed`.
- Video download tasks fail after 4 attempts with `Requested format is not available`.
- Earlier in the same log:

```
Error solving n challenge request using "deno" provider
TypeError: a.addOnDisposeCallback is not a function
n challenge solving failed: Some formats may be missing
Only images are available for download
```

- Jobs submitted with snapshots off still complete, because captions need no video file. Their `download` and `snapshots` steps are `skipped`, so the failure appears only when a capture is requested.

The last two messages hide the cause: `Requested format is not available` is the result, the solver crash is the reason.

## Root cause

1. YouTube requires yt-dlp to solve a JavaScript challenge taken from the current player (`b485e332` at the time). The solver in the shipped release crashed on that player, so only storyboard images were offered.
2. `backend/requirements.txt` declared `yt-dlp>=2024.0.0`. The image froze the release available on its build day and kept it until the next build and deployment.
3. The `default` extra was not requested, so `yt-dlp-ejs` (the solver script) was not installed and part of the solver was downloaded from GitHub at run time.

## Fix

`backend/requirements.txt` pins `yt-dlp[default]==2026.11.23`. `tests/test_dependency_contract.py` fails if the pin is loosened, moved below that release, or loses the `default` extra.

The fix reaches production only after a new image is built and promoted.

## Known limitation

With the `mweb` client used in `backend/app/services/video.py`, some formats are skipped (`missing a URL`, YouTube's SABR-only experiment). On the video used for diagnosis the best selectable format was 640x360, below the requested 720p. Slide OCR quality may suffer.

## This will happen again

The pin does not protect against the next YouTube player change. It makes the shipped release visible and the repair short.

### Diagnose

Run on the host of the running stack. It downloads no video:

```bash
docker exec tutorial_celery_worker python3 -m yt_dlp -v --simulate --no-cache-dir \
  --remote-components ejs:github \
  --extractor-args "youtube:player_client=mweb" \
  --extractor-args "youtubepot-bgutilhttp:base_url=http://tutorial_bgutil_provider:4416" \
  -f "best[height<=720][ext=mp4]/best" \
  --print "SELECTED %(format_id)s %(width)sx%(height)s" \
  "https://www.youtube.com/watch?v=<VIDEO_ID>"
```

A `SELECTED` line means extraction works. `n challenge solving failed` means the solver is broken again.

To check whether a newer release fixes it before touching the project:

```bash
uvx --from "yt-dlp[default,deno]==<NEW_VERSION>" yt-dlp --ignore-config --no-cache-dir --simulate \
  --remote-components ejs:github --extractor-args "youtube:player_client=mweb" \
  -f "best[height<=720][ext=mp4]/best" --print "SELECTED %(format_id)s %(width)sx%(height)s" \
  "https://www.youtube.com/watch?v=<VIDEO_ID>"
```

### Repair

1. Raise the pin in `backend/requirements.txt` and `OLDEST_WORKING_YT_DLP` in `tests/test_dependency_contract.py`.
2. Build the image and run the diagnose command inside it.
3. Merge, then promote the new candidate (see `VM_DEPLOYMENT.md`).

## Not yet done

- No scheduled check detects the next breakage. A daily run of the diagnose command with an alert would; any new scheduled task has to be registered in the automation registry before it is installed.
- The earlier related failure (no JavaScript runtime in the image) was fixed by adding Deno in pull request 228.
