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

## Deploying to production

Deploy config is a plain `Dockerfile` + `Procfile` (#12) — no
platform-specific config (`heroku.yml`, `railway.json`, `render.yaml`, ...)
is committed, so this works on any host that can build a Dockerfile and run
Procfile-style processes (Heroku, Railway, Render, Fly.io, ...) with at
most minor host-specific glue.

### Required environment variables

| Variable | Purpose |
| --- | --- |
| `DJANGO_SECRET_KEY` | Django's `SECRET_KEY`. **Required** in production — generate a unique, random value per environment (e.g. `python -c "import secrets; print(secrets.token_urlsafe(50))"`) and never commit it. |
| `DJANGO_DEBUG` | Set to `False` in production. Defaults to `True`, so local dev is unaffected if unset. |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated list of hostnames Django will serve, e.g. `myapp.example.com`. Required whenever `DJANGO_DEBUG=False` (Django rejects requests with an unrecognized `Host` header otherwise). |
| `DATABASE_URL` | Single Postgres connection string, e.g. `postgres://user:pass@host:5432/dbname`. Most hosts (Heroku, Railway, Render) inject this automatically when you attach a Postgres addon/database. |
| `DJANGO_EMAIL_BACKEND` / `DJANGO_EMAIL_HOST*` | Optional — SMTP config for outgoing mail (see #7). Defaults to the console backend if unset. |
| `DJANGO_ACCESS_CODES` | Optional — comma-separated access codes gating the dashboard/report pages (see #10). |
| `PORT` | The port the app should listen on. Most hosts (Heroku, Railway, Render) set this automatically; the `Procfile`'s `web` process binds to it. |

Copy `.env.example` as a starting point for which variables exist; in
production these are set via the host's environment/config-vars UI, not a
committed `.env` file.

### Static files

Static files are served in-process via [whitenoise](https://whitenoise.readthedocs.io/)
— no separate static file host/CDN is required. The `Dockerfile` runs
`python manage.py collectstatic --noinput` at build time, so this doesn't
need to happen again at deploy/runtime.

### Running migrations in production

The `Procfile` declares a `release` process (`python manage.py migrate
--noinput`) that hosts supporting Heroku-style release phases (Heroku,
some Railway/Render setups) run automatically before each deploy's `web`
process starts. On a host without release-phase support, run it manually
against the new release once, e.g.:

```bash
docker run --rm -e DATABASE_URL=... -e DJANGO_SECRET_KEY=... <image> \
  python manage.py migrate --noinput
```

### Building and running the image locally

To verify the production image works before deploying:

```bash
docker build -t hse-tool .
docker run --rm -p 8000:8000 \
  -e DJANGO_SECRET_KEY=some-random-value \
  -e DJANGO_DEBUG=False \
  -e DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1 \
  -e DATABASE_URL=postgres://hse_tool:hse_tool@host.docker.internal:5432/hse_tool \
  hse-tool
```

(`host.docker.internal` lets the container reach the `docker compose up -d
db` Postgres running on the host — a real deploy points `DATABASE_URL` at
the host's managed Postgres instead.) Then confirm
http://127.0.0.1:8000/health/ responds `{"status": "ok"}`.

### Triggering a deploy

How a deploy is actually triggered (git push, CLI, CI pipeline) is
host-specific and out of scope for this repo's config — see the chosen
host's docs for connecting it to this `Dockerfile`/`Procfile`. Choosing
which host to use, and zero-downtime/rollback tooling, are also out of
scope for now (see #12).

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

For example, the chain for implementing this issue was:

```
CLAUDE.md → AGENTS.md → _docs/process.md → _docs/team/software-engineer.md
```

with `_docs/testing-guidelines.md` and `_docs/design-system.md` as
required-but-empty side branches off `AGENTS.md` (read because the rules
say to, but both files were empty at the time).
