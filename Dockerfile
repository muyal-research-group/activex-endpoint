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

RUN poetry install --no-root

COPY ./activexendpoint/ /app/activexendpoint
RUN poetry install
COPY ./activex.tar.gz .
RUN poetry remove activex && poetry add /app/activex.tar.gz
ENTRYPOINT [ "poetry", "run", "python3", "-m", "activexendpoint.main" ]
# WORKDIR /app

# 
# COPY ./requirements.txt /app/requirements.txt

# 
# RUN pip install -r /app/requirements.txt
#
# COPY ./activexendpoint . 

# CMD ["python3", "/app/main.py"]
# COPY ./mictlanxrouter/interfaces /app/interfaces 
# COPY ./mictlanxrouter/helpers /app/helpers

# 
# CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "60666"]
# CMD ["python3","./mictlanxrouter/server.py"]
# CMD ["sleep","infinity"]
# CMD ["uvicorn", "mictlanxrouter.server:app","--host",$MICTLANX_ROUTER_HOST,"--port",$MICTLANX_ROUTER_PORT]

