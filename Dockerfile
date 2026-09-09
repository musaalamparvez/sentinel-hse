# Generic, platform-agnostic image for the HSE reporting tool.
#
# Works as-is on any host that can run a Dockerfile against a Procfile-style
# process (Heroku container/Procfile deploys, Railway, Render, Fly.io, ...).
# No platform-specific config (heroku.yml, railway.json, render.yaml, ...)
# is committed here on purpose — see README.md "Deploying to production"
# for the env vars each host needs to be given.

FROM python:3.12-slim

# Faster, more predictable Python behaviour in a container.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local

WORKDIR /app

# System deps needed to build/run psycopg + friends.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Install uv (used for dependency resolution/locking in dev; here it just
# installs the locked, production dependency set into the system env).
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv

# Install dependencies first for better layer caching.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

# Now copy the rest of the application code.
COPY . .
RUN uv sync --locked --no-dev

# Collect static assets into STATIC_ROOT at build time so the running
# container never needs write access to the image / a build step in prod.
# DJANGO_SECRET_KEY is only required so settings.py can import cleanly;
# collectstatic doesn't touch the database, so DATABASE_URL isn't needed.
# DJANGO_DEBUG=False selects whitenoise's manifest storage backend
# (config/settings.py), matching how the app actually runs in prod.
RUN DJANGO_SECRET_KEY=build-time-placeholder-not-used-at-runtime \
    DJANGO_DEBUG=False \
    python manage.py collectstatic --noinput

EXPOSE 8000

# The Procfile is the source of truth for how each process type is run;
# this default CMD lets `docker run` boot the web process directly too.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
