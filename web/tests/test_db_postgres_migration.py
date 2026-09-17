"""Postgres startup-migration regression test.

Restoring DATABASE_URL on 2026-09-17 crash-looped the container:
init_schema()'s google_sub migration swallowed the expected
DuplicateColumn error, but on PostgreSQL the failed ALTER aborts the
whole transaction, so the CREATE UNIQUE INDEX right after it died with
InFailedSqlTransaction and the instance never started. The fix rolls
back after the expected migration failure. This test emulates psycopg's
aborted-transaction behavior with a mock so the regression is pinned
without needing a live Postgres.
"""

import web.db as db


class _FakePgConn:
    """Emulates psycopg: a failed statement aborts the transaction until
    rollback() is called."""

    def __init__(self):
        self.aborted = False
        self.statements = []

    def execute(self, stmt, params=()):
        self.statements.append(stmt)
        if self.aborted:
            raise Exception(
                "current transaction is aborted, "
                "commands ignored until end of transaction block"
            )
        if "ADD COLUMN google_sub" in stmt:
            self.aborted = True
            raise Exception(
                'column "google_sub" of relation "users" already exists'
            )
        return self

    def rollback(self):
        self.aborted = False

    def commit(self):
        pass

    def close(self):
        pass


def test_init_schema_survives_existing_google_sub_column(monkeypatch):
    """The migration must roll back after the expected duplicate-column
    failure so the index creation below it can run."""
    conn = _FakePgConn()
    monkeypatch.setattr(db, "connect", lambda: conn)
    db.init_schema()  # must not raise
    assert any("CREATE UNIQUE INDEX" in s for s in conn.statements)
    assert not conn.aborted


def test_unexpected_migration_error_still_raises(monkeypatch):
    class _BoomConn(_FakePgConn):
        def execute(self, stmt, params=()):
            if "ADD COLUMN google_sub" in stmt:
                raise Exception("permission denied for table users")
            return super().execute(stmt, params)

    monkeypatch.setattr(db, "connect", _BoomConn)
    try:
        db.init_schema()
    except Exception as exc:
        assert "permission denied" in str(exc)
    else:
        raise AssertionError("unexpected migration errors must propagate")
