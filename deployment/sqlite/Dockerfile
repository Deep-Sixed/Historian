# Profile v4 certified runtime: Python 3.14.5 with stdlib sqlite3 on SQLite 3.46.1.
# The base image is pinned by digest and named in the profile (CERTIFIED_IMAGE in
# historian/sqlite_store/profile.py); tests/test_release_evidence.py keeps them equal.
# The proof suite also fails closed if this image provides any other runtime.
FROM python:3.14.5-slim@sha256:c845af9399020c7e562969a13689e929074a10fd057acd1b1fad06a2fb068e97
WORKDIR /app
ENV PYTHONPATH=/app
COPY pyproject.toml /app/
COPY historian /app/historian
RUN pip install --no-cache-dir '.[dev]'
COPY tests /app/tests
RUN mkdir -p /data/private /data/socket /data/corpus && chown -R 10000:10000 /data && chmod 700 /data/private /data/corpus
USER 10000:10000
CMD ["python", "-m", "historian.sqlite_store.service", "--database", "/data/private/historian.db", "--socket", "/data/socket/historian.sock", "--corpus", "/data/corpus"]
