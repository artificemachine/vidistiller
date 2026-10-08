"""Installed dependencies keep the database URLs the app and tests use working."""

from sqlalchemy import create_engine


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
