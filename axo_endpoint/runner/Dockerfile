ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim

WORKDIR /app

# Install build deps for packages that need compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml poetry.lock* ./
COPY axo_endpoint/ ./axo_endpoint/
COPY axo_shared/ ./axo_shared/

# Install dependencies only -- axo_endpoint/ is already copied in as plain
# files above and importable via WORKDIR, so there's no need for poetry to
# build/install it as a package too (which would also require README.md,
# never copied into this image). axo_shared/ is copied in for the same
# reason axo_endpoint's own code needs it: axo_endpoint imports axo_shared,
# and poetry install (below) needs the path dependency's directory present
# to resolve it, since it's declared in the root pyproject.toml.
RUN pip install --no-cache-dir poetry \
    && poetry config virtualenvs.create false \
    && poetry install --without dev --no-root --no-interaction --no-ansi \
    && pip uninstall -y poetry

EXPOSE 5600 8000

CMD ["python", "-m", "axo_endpoint.runner"]
