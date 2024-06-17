# 
FROM python:3.9

# 
WORKDIR /app
RUN pip3 install poetry

ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

COPY poetry.lock  .
COPY pyproject.toml  .
RUN touch README.md

RUN poetry config virtualenvs.create false && \
    poetry lock && \
    poetry install --no-root

COPY ./activexendpoint/ /app/activexendpoint
RUN poetry install
# COPY ./activex.tar.gz .
# RUN poetry remove activex && poetry add /app/activex.tar.gz
# CMD ["sleep","infinity"]
ENTRYPOINT [ "poetry", "run", "python3", "-m", "activexendpoint.main" ]