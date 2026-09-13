FROM python:3.14.5-slim
WORKDIR /app
ENV PYTHONPATH=/app
COPY pyproject.toml /app/
COPY historian /app/historian
RUN pip install --no-cache-dir '.[dev]'
COPY tests /app/tests
RUN mkdir -p /data/private /data/socket /data/corpus && chown -R 10000:10000 /data && chmod 700 /data/private /data/corpus
USER 10000:10000
CMD ["python", "-m", "historian.sqlite_store.service", "--database", "/data/private/historian.db", "--socket", "/data/socket/historian.sock", "--corpus", "/data/corpus"]
