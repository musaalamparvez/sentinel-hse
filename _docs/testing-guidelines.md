Testing Guidelines

- Tests live in each app's `tests.py` (or `test_*.py` alongside it) — see `core/tests.py`
- Tests run against a real Postgres database (via `DATABASE_URL`), created and torn down per run — no SQLite, no mocking the DB
- Cover both success and failure cases for new features/bug fixes
