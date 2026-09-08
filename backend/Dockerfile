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

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
