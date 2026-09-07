# Built with build context = repo root (see docker-compose.yml's
# axo-vem service: context: ., dockerfile: axo_vem/Dockerfile)
# so axo_shared/ -- a sibling path dependency declared as
# axo_shared = {path = "../axo_shared", develop = true} in this project's own
# pyproject.toml -- is reachable from the build context, mirroring the exact
# on-disk repo layout (axo_shared/ next to axo_vem/).
ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim

WORKDIR /app
COPY axo_shared/ /app/axo_shared/

WORKDIR /app/axo_vem

# Copy lockfile + pyproject first, install deps -- axo_shared/ is already in
# place above so poetry can resolve the path dependency, but no other
# axo_vem source is needed yet (--no-root skips installing this
# project's own package, only its declared dependencies).
COPY axo_vem/pyproject.toml axo_vem/poetry.lock* ./
RUN pip install --no-cache-dir poetry \
    && poetry config virtualenvs.create false \
    && poetry install --without dev --no-root --no-interaction --no-ansi

COPY axo_vem/ ./
RUN poetry install --without dev --no-interaction --no-ansi \
    && pip uninstall -y poetry

EXPOSE 6000 8080

CMD ["python", "-m", "axo_vem"]
