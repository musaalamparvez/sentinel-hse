Commands

- `uv sync` - install dependencies
- `docker compose up -d db` - start local Postgres
- `uv run python manage.py migrate` - apply migrations
- `uv run pytest` - the whole suite
- `uv run pytest core/tests.py` - one test file
- `uv run python manage.py runserver` - dev server

Rules

- Dependencies are added in `pyproject.toml`. Do not add one without asking

Documents

- `_docs/process.md` - how work is organized
- Before writing tests, read `_docs/testing-guidelines.md`
- For anything touching the UI, read `_docs/design-system.md`