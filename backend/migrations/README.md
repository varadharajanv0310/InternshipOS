# Core schema migration 0001

`0001_initial_postgresql.sql` is the initial PostgreSQL schema for the 24 core
tables, generated from the SQLAlchemy metadata. Apply it once to an empty
PostgreSQL database in a transaction. The background-worker table is owned by
the jobs module and is added by the application bootstrap.

For a fresh local or deployed database, `internshipos.db.init_db()` performs
idempotent creation from the same metadata. It does not drop or silently alter
existing tables. `seed_database()` then imports verified company seed facts and
candidate source associations idempotently; it inserts no jobs or applicant
facts.

SQLite is the portable local fallback. Production URLs use
`postgresql+psycopg://…`; date columns retain timezone support, source IDs have
scoped unique constraints, and ingestion locks the source row on PostgreSQL.
SQLite uses foreign-key enforcement and a busy timeout.

This is a new schema, so there is no legacy application data conversion. Before
changing an already deployed schema, add a numbered migration with its data
conversion and rollback/backup procedure. `create_all()` is not an upgrade
engine. Restore tests and PostgreSQL runtime tests remain required before a
production deployment; the automated domain tests exercise SQLite and compile
the PostgreSQL DDL.
