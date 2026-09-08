# Python 3.11 to match Rules.md 4.1. Slim base keeps the image reasonably
# small; the sentence-transformers/torch stack in requirements.txt still
# makes this a large image regardless of base — that weight is inherent to
# the approved dependency set, not something the Dockerfile can trim away.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Created before any COPY so --chown below has a target user/group that
# already exists. /app itself (the directory entry, not just what's copied
# into it) is chowned separately and non-recursively — COPY --chown only
# owns the files it places, and appuser still needs write access to /app
# itself to lazily mkdir "storage/" at request time (app/utils/files.py).
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin appuser \
    && chown appuser:appuser /app

# Dependency layer first, app code last — requirements.txt changes far less
# often than application source, so this layer stays cached across ordinary
# code edits (Phases.md Phase 16 acceptance).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code, owned by appuser as it's copied in rather than a
# separate chown -R pass afterwards. .dockerignore keeps .env, storage/,
# __pycache__, the local venv, and test caches out of the build context and
# therefore the image.
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser alembic ./alembic
COPY --chown=appuser:appuser alembic.ini .

USER appuser

EXPOSE 8000

# Shell-form CMD, deliberately not the exec-form array this used to be —
# exec-form ["cmd", "arg", ...] is passed straight to the kernel with no
# shell involved, so it can neither interpret "&&" as a command separator
# nor expand "${PORT:-8000}"; a platform-injected $PORT would be passed
# through as the literal four characters "$PORT". Docker runs a bare-string
# CMD as `/bin/sh -c "<this>"` automatically, which is what makes both work.
# `exec` before uvicorn replaces that shell with the uvicorn process once
# migrations succeed, so uvicorn becomes PID 1 and receives a platform's
# SIGTERM directly for a clean shutdown, rather than an intermediate shell
# swallowing it.
#
# This has no ENTRYPOINT, on purpose. Some platforms let you override a
# container's start command from their own dashboard/config — if that
# override is applied without a shell (i.e. split on whitespace and exec'd
# directly, the way `docker run <image> <args...>` does), then typing
# "alembic upgrade head && uvicorn ..." into that field reproduces exactly
# the failure this fixes: "&&" and everything after it arrive as literal,
# unrecognized arguments to `alembic` itself, because nothing ever
# interpreted "&&" as a separator. The fix is to leave that platform's
# command override unset so this image's own shell-form CMD runs — not to
# hardcode `alembic` as the ENTRYPOINT and hope a platform appends the rest
# correctly, which has the identical failure mode. See docs/SETUP.md.
CMD alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
