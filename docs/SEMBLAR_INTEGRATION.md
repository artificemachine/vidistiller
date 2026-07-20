# Vidistiller → Semblar Integration Plan

**Date**: 2026-04-28
**Status**: Proposed. No code changes yet.

---

## What Semblar needs from vidistiller

Semblar calls vidistiller's REST API to convert video URLs into transcripts and structured Markdown for use as **reference material** in article generation.

```
Semblar VM (10.0.181.30)
       │
       │  HTTP to vidistiller API
       ▼
vidistiller API (Proxmox VM 900 on the lab cluster)
       │
       │  POST /api/jobs  {"video_url": "..."}
       │  GET  /api/jobs/{job_id}/status   (poll)
       │  GET  /api/jobs/{job_id}/documents (fetch results)
       ▼
   transcript + structured Markdown → Semblar article pipeline
```

---

## Changes Needed in Vidistiller

### 1. Machine-to-Machine Auth (required)

**Current state**: All `/api/jobs` routes require `current_user = Depends(get_current_user_from_token)`, which extracts a JWT from a `Bearer` header. JWTs come from user login (`POST /auth/login`). There is no API key, service account, or long-lived token mechanism.

**Problem**: Semblar is a machine calling the API, not a human logging in. A login-based JWT expires every 30 minutes (`ACCESS_TOKEN_EXPIRE_MINUTES`). Semblar would need to store credentials and refresh tokens -- overkill for a LAN service call.

**Recommended fix: Shared secret API key**

Add a new env var and auth middleware:

```python
# In config: new setting
VIDISTILLER_API_KEY: str = ""  # shared secret for machine-to-machine clients

# In a new middleware or auth bypass:
from fastapi import Header

async def verify_api_key_or_jwt(
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    # Option A: API key header (machine-to-machine)
    if x_api_key:
        settings = get_settings()
        if not settings.vidistiller_api_key:
            raise AuthenticationException("API key auth not configured")
        if not secrets.compare_digest(x_api_key, settings.vidistiller_api_key):
            raise AuthenticationException("Invalid API key")
        # Return a synthetic "service user" or the system user
        return db.query(User).filter(User.username == "semblar").first()

    # Option B: standard JWT (human login)
    return get_current_user_from_token(authorization, db)
```

**Effort**: ~30 lines of code + one new env var + one new DB user row.

**Alternatives considered and rejected**:
- JWT with long expiry: Requires storing credentials on Semblar VM, adds refresh logic. More moving parts.
- IP-based allowlist (no auth for LAN IPs): Simple but fragile if IPs change. Not recommended.
- Dedicated `/internal/` route prefix with no auth: Simpler but less secure if network boundary is ever breached.

### 2. Service Account User (required if using API key approach)

Create a `semblar` user in vidistiller's database. This is the user that owns jobs created by Semblar. No password needed if API key auth is used. Just needs a row in the `users` table:

```sql
INSERT INTO users (username, email, hashed_password, created_at)
VALUES ('semblar', 'semblar@internal', '', NOW());
```

The API key middleware returns this user when `X-API-Key` matches.

### 3. CORS / Network Access (required if vidistiller uses CORS middleware for API calls from browser)

N/A for machine-to-machine. Semblar calls vidistiller directly via HTTP from Python -- no browser, no CORS. **No change needed** for this. The CORS middleware only applies to browser-based requests.

**Verify**: Semblar VM (10.0.181.30) can reach vidistiller API port (8000) on the LAN. Both are Proxmox VMs on the same cluster and should sit on reachable subnets.

### 4. Transcript Endpoint (nice-to-have, not required)

**Current state**: Transcript is embedded in the `GET /api/jobs/{job_id}` response as a nested `TranscriptResponse` object. The document (LLM-structured Markdown) is available at `GET /api/jobs/{job_id}/documents`.

**What Semblar actually needs**: The structured Markdown document (`GET /api/jobs/{job_id}/documents`) is the primary output. The raw transcript is a secondary source for deep reference. Both are already accessible via the existing API.

**Verdict**: No new endpoint needed. Semblar can call `GET /api/jobs/{job_id}` and extract transcripts from the response, or call `GET /api/jobs/{job_id}/documents` for the structured Markdown.

### 5. Polling-Friendly Status Endpoint (already exists)

`GET /api/jobs/{job_id}/status` returns a lightweight `JobStatusResponse` with `status`, `summarize_status`, and timestamps. Semblar can poll this every 10 seconds until status is `completed` or `failed`.

**No change needed.**

### 6. Environment Variables to Add

```bash
# In vidistiller/.env:
VIDISTILLER_API_KEY=semblar-shared-secret-abc123   # shared secret for Semblar
```

Add to `config.py`:

```python
class ApiKeySettings(BaseSettings):
    """Machine-to-machine API key for trusted internal services."""
    vidistiller_api_key: str = Field(default="", validation_alias="VIDISTILLER_API_KEY")
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
```

---

## Changes NOT Needed

| Thing | Why not needed |
|---|---|
| New CLI command | Semblar calls the REST API, same as it calls Claude/Gemini/OpenAI. |
| Python library export | Semblar does not import vidistiller as a Python dependency. |
| `services/llm/` extraction | vidistiller's LLM service is video-domain-specific. Semblar has its own LLM pipeline. |
| `crypto.py` extraction | That file does not exist. API key encryption is inline in the settings route. |
| Real-time streaming | Semblar needs the final output, not partial results. Polling is fine. |

---

## Summary of Required Changes

| # | Change | Effort | Priority |
|---|---|---|---|
| 1 | Add `VIDISTILLER_API_KEY` env var + config | 1 file, 5 lines | Required |
| 2 | Add API key auth middleware (or bypass) | 1 new middleware file, ~30 lines | Required |
| 3 | Create `semblar` service user in DB | 1 SQL INSERT or migration | Required |
| 4 | Wire API key auth into job route dependencies | Modify 1 import in `routes/jobs.py` | Required |
| 5 | Test: Semblar VM can reach vidistiller port | Network check | Required |

**Total effort**: ~1 hour. 2 files to create, 1 file to modify, 1 DB row to insert.

---

## After These Changes, Semblar's Integration Looks Like

```python
# In Semblar: src/semblar/services/vidistiller_client.py

class VidistillerClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.headers = {"X-API-Key": api_key}

    def submit_video(self, url: str) -> str:
        """Submit a video for processing. Returns job_id."""
        resp = requests.post(f"{self.base_url}/api/jobs", json={
            "video_url": url,
            "output_format": "markdown",
            "extract_snapshots": False,   # Semblar only needs text
            "is_slide_mode": False,
        }, headers=self.headers)
        resp.raise_for_status()
        return resp.json()["job_id"]

    def poll_until_complete(self, job_id: str, timeout: int = 600) -> str:
        """Poll job status. Returns 'completed' or 'failed'."""
        ...

    def get_documents(self, job_id: str) -> list[dict]:
        """Fetch generated Markdown documents for a completed job."""
        resp = requests.get(
            f"{self.base_url}/api/jobs/{job_id}/documents",
            headers=self.headers,
        )
        return resp.json()

    def get_transcript(self, job_id: str) -> str:
        """Extract transcript text from the full job response."""
        resp = requests.get(
            f"{self.base_url}/api/jobs/{job_id}",
            headers=self.headers,
        )
        job = resp.json()
        # Transcript text is in job["transcripts"][0]["full_text"]
        return "\n".join(t["full_text"] for t in job.get("transcripts", []))
```

~80 lines. No dependency on vidistiller's Python code. Clean contract.
