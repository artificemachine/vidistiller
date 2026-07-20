# Security Policy

## Supported Versions

Security fixes are applied to the latest release on `main`. Older tags are not patched.

## Reporting a Vulnerability

Please do **not** open a public GitHub issue for security vulnerabilities.

Report privately via [GitHub Security Advisories](https://github.com/artificemachine/vidistiller/security/advisories/new). Include:

- A description of the vulnerability and its impact
- Steps to reproduce (proof of concept if possible)
- Affected version(s)

You can expect an acknowledgement within 7 days. If the report is confirmed, a fix will be released and credited (unless you prefer to remain anonymous).

## Scope Notes

Vidistiller is designed for **self-hosted, single-operator** deployments. The default `.env.example` contains placeholder credentials (`JWT_SECRET_KEY`, database passwords) that **must** be replaced before any deployment reachable by other users or networks. Never expose the API or frontend directly to the public internet without authentication and TLS in front of it.
