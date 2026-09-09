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

## Engineering flow / process

Work is organized as GitHub issues, one at a time (see `_docs/process.md`).
Docs are chained together — following them in order gets you the full
picture of how a task should be implemented:

1. **`CLAUDE.md`** — points to `AGENTS.md`.
2. **`AGENTS.md`** — commands, the "don't add a dependency without asking"
   rule, and pointers to:
   - `_docs/process.md` — how work is organized
   - `_docs/testing-guidelines.md` — read before writing tests
   - `_docs/design-system.md` — read for anything touching the UI
3. **`_docs/process.md`** — explains tasks are GitHub issues, and that each
   role has its own doc under `_docs/team/`:
   - `_docs/team/pm.md` — grooms a task before implementation
   - `_docs/team/software-engineer.md` — implements one groomed task
   - `_docs/team/qa-engineer.md` — checks the result against acceptance
     criteria
4. **Role doc for the job at hand** — e.g. an engineer implementing a task
   reads `_docs/team/software-engineer.md`, which sets the definition of
   done: implement every acceptance criterion, write tests, commit
   regularly, leave the issue **open** with a comment describing what was
   done (never close it), and comment on the issue instead of silently
   reinterpreting a criterion that's wrong or contradictory.
5. **`_docs/task_template.md`** — the shape a groomed issue takes (Goal /
   Acceptance criteria / Out of scope / Constraints), useful context for
   reading any issue.

Only the docs relevant to your current role need to be read in full —
`_docs/testing-guidelines.md` and `_docs/design-system.md` are read
whenever they apply (tests / UI work), and the PM/QA docs only matter when
you're grooming or verifying a task rather than implementing it.
