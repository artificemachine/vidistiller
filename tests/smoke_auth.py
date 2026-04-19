#!/usr/bin/env python3
"""
Live smoke test — login and register against the running API.

Usage:
    python tests/smoke_auth.py [--base-url http://localhost:8000]

Exits 0 on pass, 1 on any failure.
"""

import argparse
import os
import sys
import time
import requests

BASE_URL = os.getenv("SMOKE_BASE_URL", "http://localhost:8000")
TIMEOUT = 10


def check(label: str, condition: bool, detail: str = "") -> bool:
    status = "PASS" if condition else "FAIL"
    msg = f"  [{status}] {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    return condition


def run(base: str) -> bool:
    api = f"{base}/api"
    ok = True
    ts = int(time.time())
    test_user = f"smoketest_{ts}"
    test_email = f"{test_user}@example.com"
    test_pass = "SmokeTest1!"

    print("\n=== register ===")

    # Happy path
    r = requests.post(f"{api}/auth/register", json={
        "username": test_user,
        "email": test_email,
        "password": test_pass,
    }, timeout=TIMEOUT)
    ok &= check("register 201", r.status_code == 201, f"got {r.status_code}: {r.text[:120]}")
    ok &= check("no password_hash in response", "password_hash" not in r.json())

    # Duplicate username
    r2 = requests.post(f"{api}/auth/register", json={
        "username": test_user,
        "email": f"other_{ts}@example.com",
        "password": test_pass,
    }, timeout=TIMEOUT)
    ok &= check("duplicate username 400/422", r2.status_code in (400, 422), f"got {r2.status_code}")

    # Weak password (no uppercase)
    r3 = requests.post(f"{api}/auth/register", json={
        "username": f"weak_{ts}",
        "email": f"weak_{ts}@example.com",
        "password": "weakpassword1",
    }, timeout=TIMEOUT)
    ok &= check("weak password rejected 422", r3.status_code == 422, f"got {r3.status_code}")

    print("\n=== login ===")

    # Valid login
    r = requests.post(f"{api}/auth/login", json={
        "username": test_user,
        "password": test_pass,
    }, timeout=TIMEOUT)
    ok &= check("login 200", r.status_code == 200, f"got {r.status_code}: {r.text[:120]}")
    token = None
    if r.status_code == 200:
        data = r.json()
        token = data.get("access_token")
        ok &= check("access_token present", bool(token))
        ok &= check("token_type bearer", data.get("token_type") == "bearer")
        ok &= check("expires_in positive", (data.get("expires_in") or 0) > 0)

    # Wrong password
    r2 = requests.post(f"{api}/auth/login", json={
        "username": test_user,
        "password": "WrongPass1",
    }, timeout=TIMEOUT)
    ok &= check("wrong password 401", r2.status_code == 401, f"got {r2.status_code}")

    # Non-existent user
    r3 = requests.post(f"{api}/auth/login", json={
        "username": "nobody_xyzzy_99",
        "password": "SomePass1",
    }, timeout=TIMEOUT)
    ok &= check("unknown user 401", r3.status_code == 401, f"got {r3.status_code}")

    print("\n=== /me ===")
    if token:
        r = requests.get(f"{api}/auth/me",
                         headers={"Authorization": f"Bearer {token}"},
                         timeout=TIMEOUT)
        ok &= check("/me 200", r.status_code == 200, f"got {r.status_code}")
        ok &= check("/me returns username", r.json().get("username") == test_user)

    print()
    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=BASE_URL)
    args = parser.parse_args()

    print(f"Smoke-testing {args.base_url}")
    passed = run(args.base_url)
    print("RESULT:", "ALL PASSED" if passed else "FAILURES DETECTED")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
