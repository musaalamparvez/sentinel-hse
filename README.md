# Near-Miss Reporting Tool

Django + Postgres monolith. See `_docs/plan.md` for the product spec and
`_docs/tasks.md` for the build backlog.

## Local development setup

1. Install dependencies (requires [uv](https://docs.astral.sh/uv/)):

   ```bash
   uv sync
   ```

2. Start Postgres via Docker Compose:

   ```bash
   docker compose up -d db
   ```

3. Copy the example env file and adjust if needed:

   ```bash
   cp .env.example .env
   ```

   `DATABASE_URL` defaults to matching the `docker-compose.yml` Postgres
   service, so the default values work out of the box.

4. Run migrations:

   ```bash
   uv run python manage.py migrate
   ```

5. Run the dev server:

   ```bash
   uv run python manage.py runserver
   ```

   The app will be available at http://127.0.0.1:8000/, with a health-check
   endpoint at http://127.0.0.1:8000/health/.

## Running tests

```bash
uv run pytest
```

or, equivalently:

```bash
uv run python manage.py test
```

Tests run against a temporary Postgres test database created/destroyed
automatically by Django's test runner, using the same `DATABASE_URL`.
