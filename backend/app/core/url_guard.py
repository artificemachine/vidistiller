"""Validation for user-supplied URLs that the backend itself will fetch.

The backend runs inside a private network and fetches URLs that users submit,
which is the precondition for SSRF. Two different policies are needed, because
the two classes of URL have opposite requirements:

* ``validate_fetch_target`` guards ``video_url``. There is no legitimate reason
  to distill a video from a loopback or link-local address, so private
  destinations are denied outright.

* ``validate_llm_endpoint`` guards the LLM and vLLM endpoints. Those point at
  private addresses *by design* (a local Ollama, an on-prem vLLM fleet), so a
  denylist would break the product's local-first path. They are restricted to an
  operator-controlled allowlist instead, which defaults to loopback only.

Known limitation: validation happens before the request is issued, so a DNS
entry that resolves to a public address here and a private one at connect time
(DNS rebinding), or a redirect chain terminating on a private address, is not
covered. Closing that requires pinning the connection to the validated IP. The
checks below reduce the attack surface substantially but are not a complete
SSRF defense on their own.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Iterable
from urllib.parse import urlparse

_ALLOWED_SCHEMES = ("http", "https")


def _resolved_addresses(hostname: str) -> list[ipaddress._BaseAddress]:
    """Resolve a hostname to every address it maps to.

    Every result is checked, not just the first: a host with one public and one
    private record would otherwise pass while still being usable to reach the
    private one.
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host '{hostname}'") from exc

    addresses = []
    for info in infos:
        raw = info[4][0]
        # Strip any IPv6 zone index (e.g. "fe80::1%eth0") before parsing.
        raw = raw.split("%", 1)[0]
        try:
            addresses.append(ipaddress.ip_address(raw))
        except ValueError:
            continue
    if not addresses:
        raise ValueError(f"Could not resolve host '{hostname}'")
    return addresses


def _is_internal(address: ipaddress._BaseAddress) -> bool:
    """True if the address is anything other than an ordinary public one."""
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def _parse(url: str) -> tuple[str, str]:
    """Return (scheme, hostname), rejecting anything malformed."""
    candidate = (url or "").strip()
    parsed = urlparse(candidate)

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise ValueError("URL must start with http:// or https://")
    if not parsed.hostname:
        raise ValueError("Invalid URL: missing or malformed host")
    return parsed.scheme.lower(), parsed.hostname


def validate_fetch_target(url: str) -> str:
    """Guard a URL the backend will fetch on the user's behalf.

    Rejects destinations that resolve to private, loopback, link-local,
    reserved, multicast or unspecified addresses. Applied to ``video_url``.
    """
    _, hostname = _parse(url)

    for address in _resolved_addresses(hostname):
        if _is_internal(address):
            # Deliberately does not echo the resolved address back: that would
            # turn the error message into an internal-network disclosure.
            raise ValueError(
                "URL resolves to a non-public address, which is not allowed"
            )

    return url.strip()


def validate_llm_endpoint(url: str, allowed_hosts: Iterable[str]) -> str:
    """Guard an operator-configured LLM or vLLM endpoint.

    Private addresses are expected here, so the host is matched against an
    operator-controlled allowlist rather than screened by range.
    """
    _, hostname = _parse(url)

    permitted = {h.strip().lower() for h in allowed_hosts if h and h.strip()}
    if hostname.lower() not in permitted:
        raise ValueError(
            f"Host '{hostname}' is not in the LLM endpoint allowlist. "
            "Add it to ALLOWED_LLM_HOSTS to permit it."
        )

    return url.strip()
