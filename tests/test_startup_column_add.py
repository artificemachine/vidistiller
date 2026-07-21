"""Regression: startup column-add must not be poisoned by an already-existing column.

On Postgres, an ALTER that fails because the column already exists aborts the
current transaction. The startup loop used a single shared connection, so the
first already-exists ALTER poisoned every later one — which is how a live deploy
ended up missing the users.token_version column and broke login. Each statement
now runs in its own transaction and rolls back on failure.
"""

from sqlalchemy import text


def _column_exists(conn, table, column) -> bool:
    dialect = conn.dialect.name
    if dialect == "postgresql":
        row = conn.execute(
            text(
                "select 1 from information_schema.columns "
                "where table_name=:t and column_name=:c"
            ),
            {"t": table, "c": column},
        ).fetchone()
        return row is not None
    # sqlite
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == column for r in rows)


def test_new_column_added_even_after_an_already_exists_failure(test_db):
    # Use the same database the test fixture is bound to (sqlite locally,
    # Postgres in CI — where the poison-transaction behaviour actually occurs).
    engine = test_db.get_bind()
    # A brand-new column that should get created despite an earlier ALTER in the
    # batch failing on an already-existing column.
    statements = [
        # This one already exists (create_all made it) -> fails, must not poison.
        "ALTER TABLE processing_jobs ADD COLUMN caption_language VARCHAR(10)",
        # This one is new -> must still be applied.
        "ALTER TABLE processing_jobs ADD COLUMN _regression_probe VARCHAR(5)",
    ]
    try:
        for stmt in statements:
            with engine.connect() as conn:
                try:
                    conn.execute(text(stmt))
                    conn.commit()
                except Exception:
                    conn.rollback()

        with engine.connect() as conn:
            assert _column_exists(conn, "processing_jobs", "_regression_probe")
    finally:
        with engine.connect() as conn:
            try:
                conn.execute(text("ALTER TABLE processing_jobs DROP COLUMN _regression_probe"))
                conn.commit()
            except Exception:
                conn.rollback()
