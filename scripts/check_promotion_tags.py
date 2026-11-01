#!/usr/bin/env python3
"""Refuse promotion when either stable-version image tag already exists."""

import argparse
import re
import subprocess
import sys

STABLE_VERSION = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


class TagCheckError(Exception):
    """A safe-to-report promotion tag check failure."""


def _lookup_tag(image_ref: str) -> None:
    try:
        result = subprocess.run(
            ["docker", "buildx", "imagetools", "inspect", image_ref],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise TagCheckError(
            "registry lookup timed out while checking promotion tags"
        ) from exc
    except OSError as exc:
        raise TagCheckError(
            "Docker CLI could not be started while checking promotion tags"
        ) from exc
    if result.returncode == 0:
        raise TagCheckError(
            f"refusing promotion: target tag already exists: {image_ref}"
        )
    output = (result.stdout + "\n" + result.stderr).lower()
    refs = _docker_reference_aliases(image_ref)
    without_refs = output
    for ref in refs:
        without_refs = without_refs.replace(ref.lower(), "")
    if any(
        marker in without_refs for marker in ("unauthorized", "forbidden", "denied")
    ) or re.search(r":\s*(?:401|403)\b", without_refs):
        raise TagCheckError(
            "registry authentication or authorization failed while checking promotion tags"
        )
    ref_not_found = any(
        re.search(
            rf"(?:^|\n)(?:error:\s*)?(?:reference\s+)?{re.escape(ref.lower())}:?\s+not found(?:\s|$)",
            output,
        )
        for ref in refs
    )
    registry_manifest_unknown = any(
        _output_mentions_ref(output, ref.lower()) for ref in refs
    ) and any(
        marker in output
        for marker in (
            "manifest_unknown",
            "manifest unknown",
            "name_unknown",
            "name unknown",
        )
    )
    if ref_not_found or registry_manifest_unknown:
        return
    raise TagCheckError(
        f"registry lookup failed while checking promotion tags (exit code {result.returncode})"
    )


def _docker_reference_aliases(image_ref: str) -> tuple[str, ...]:
    refs = [image_ref]
    first_component = image_ref.split("/", 1)[0]
    if first_component == "docker.io":
        refs.append("index.docker.io/" + image_ref[len("docker.io/") :])
    elif first_component == "index.docker.io":
        refs.append("docker.io/" + image_ref[len("index.docker.io/") :])
    elif (
        "/" in image_ref
        and "." not in first_component
        and ":" not in first_component
        and first_component != "localhost"
    ):
        refs.extend(("docker.io/" + image_ref, "index.docker.io/" + image_ref))
    return tuple(refs)


def _output_mentions_ref(output: str, image_ref: str) -> bool:
    return (
        re.search(
            rf"(?<![a-z0-9._/-]){re.escape(image_ref)}(?![a-z0-9._-])",
            output,
        )
        is not None
    )


def check_tags(
    namespace: str, version: str, backend_ref: str, frontend_ref: str
) -> None:
    if not STABLE_VERSION.fullmatch(version):
        raise TagCheckError(
            "version must be stable vMAJOR.MINOR.PATCH with no leading zeroes"
        )
    if not namespace.strip():
        raise TagCheckError("Docker image namespace is required")
    for role, ref in (("backend", backend_ref), ("frontend", frontend_ref)):
        name, separator, digest = ref.partition("@")
        expected_name = f"{namespace}/vidistiller-{role}"
        if not separator or not digest or name != expected_name:
            raise TagCheckError(
                f"candidate {role} image does not match the configured image namespace"
            )
        target = f"{name}:{version}"
        _lookup_tag(target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--backend-ref", required=True)
    parser.add_argument("--frontend-ref", required=True)
    args = parser.parse_args()
    try:
        check_tags(args.namespace, args.version, args.backend_ref, args.frontend_ref)
    except TagCheckError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("OK: both promotion tags are absent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
