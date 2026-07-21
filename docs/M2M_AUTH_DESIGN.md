# Machine-to-Machine Auth Design

**Status**: Implemented (`backend/app/core/api_key_auth.py`).

Design notes for the API key authentication path used by non-interactive clients (automation, internal services) that need to call the API without a human login.

---

## Problem

All `/api/jobs` routes required `current_user = Depends(get_current_user_from_token)`, which extracts a JWT from a `Bearer` header. JWTs come from user login (`POST /auth/login`).

A machine calling the API isn't a human logging in. A login-based JWT expires every 30 minutes (`ACCESS_TOKEN_EXPIRE_MINUTES`). A non-interactive client would need to store credentials and refresh tokens — overkill for a trusted server-to-server call.

## Design: shared-secret API key

```python
async def get_current_user(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> User:
    # Option A: API key header (machine-to-machine)
    if x_api_key and configured_key:
        if not secrets.compare_digest(x_api_key, configured_key):
            raise AuthenticationException("Invalid API key")
        return _get_or_create_service_user(db, M2M_SERVICE_USERNAME)

    # Option B: standard JWT (human login)
    return get_current_user_from_token(authorization, db)
```

A configured `VIDISTILLER_API_KEY` unlocks the `X-API-Key` header path; a synthetic service user (`M2M_SERVICE_USERNAME`) owns any jobs the key creates, so ownership checks work the same as for a real user. If `VIDISTILLER_API_KEY` is unset, the header path is silently skipped and only JWT auth is used — no behavior change for anyone not using it.

### Alternatives considered and rejected
- **JWT with long expiry**: requires the client to store credentials and implement refresh logic. More moving parts for no real benefit over a static key on a trusted path.
- **IP-based allowlist (no auth for known IPs)**: simple but fragile if the calling host's address changes; doesn't survive NAT/proxying.
- **Dedicated `/internal/` route prefix with no auth**: simpler, but relies entirely on network boundary — no defense if that boundary is ever breached.

## Result

`secrets.compare_digest` is used for the key comparison to avoid timing attacks. The service user has no password (`password_hash=""`) — API-key-only auth, cannot log in via `/auth/login`.
