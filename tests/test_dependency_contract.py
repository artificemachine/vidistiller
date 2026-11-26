"""Installed dependencies keep the database URLs and YouTube downloads working."""

from pathlib import Path

import yaml
from packaging.requirements import Requirement
from packaging.version import Version
from sqlalchemy import create_engine

BACKEND_REQUIREMENTS = Path(__file__).resolve().parents[1] / "backend" / "requirements.txt"
# First release verified to solve YouTube player b485e332.
OLDEST_WORKING_YT_DLP = Version("2026.11.23")
DEPENDABOT_CONFIG = BACKEND_REQUIREMENTS.parents[1] / ".github" / "dependabot.yml"
# A full queue silently stops new update pull requests, yt-dlp included.
SMALLEST_PIP_QUEUE = 15


def _requirements_named(name: str) -> list[Requirement]:
    lines = (line.split("#", 1)[0].strip() for line in BACKEND_REQUIREMENTS.read_text().splitlines())
    parsed = (Requirement(line) for line in lines if line and not line.startswith("-"))
    return [requirement for requirement in parsed if requirement.name.lower() == name]


def test_yt_dlp_is_pinned_to_a_working_release_with_its_challenge_solver():
    """The image must ship an exact, recent yt-dlp together with yt-dlp-ejs.

    Regression (docs/BUG-youtube-video-download-20261126.md): `yt-dlp>=2024.0.0`
    froze whatever release existed on image build day (2026.8.19). YouTube then
    changed its player, the n challenge solver crashed, only storyboard images
    were offered, and every video download and snapshot capture failed.
    """
    requirements = _requirements_named("yt-dlp")
    assert len(requirements) == 1
    requirement = requirements[0]

    # The `default` extra installs yt-dlp-ejs, the challenge solver script.
    assert "default" in requirement.extras

    # An exact pin makes the shipped release visible and every bump a reviewed PR.
    pins = [spec.version for spec in requirement.specifier if spec.operator == "=="]
    assert len(pins) == 1 and len(requirement.specifier) == 1
    assert Version(pins[0]) >= OLDEST_WORKING_YT_DLP


def test_plain_postgresql_url_resolves_to_an_installed_driver():
    """`postgresql://` must map to a DBAPI that requirements.txt installs.

    Regression: requirements.txt allowed any SQLAlchemy >= 2.0.23, CI picked up
    2.1.4, whose default PostgreSQL driver for `postgresql://` is psycopg (v3)
    instead of psycopg2. Only psycopg2-binary is installed, so every
    Postgres-backed test failed at collection with
    "ModuleNotFoundError: No module named 'psycopg'".
    """
    engine = create_engine("postgresql://user:password@localhost:5432/db")
    try:
        assert engine.dialect.driver == "psycopg2"
        assert engine.dialect.dbapi is not None
    finally:
        engine.dispose()


def test_dependabot_pip_queue_leaves_room_for_downloader_updates():
    """Five open pip pull requests blocked every yt-dlp proposal for months."""
    updates = yaml.safe_load(DEPENDABOT_CONFIG.read_text())["updates"]
    pip_entries = [entry for entry in updates if entry["package-ecosystem"] == "pip"]
    assert len(pip_entries) == 1
    assert pip_entries[0]["open-pull-requests-limit"] >= SMALLEST_PIP_QUEUE
