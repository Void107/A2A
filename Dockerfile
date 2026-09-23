FROM python:3.12.14-slim
WORKDIR /hub
COPY requirements-hub.lock ./
RUN --mount=type=cache,id=a2a-hub-pip,target=/root/.cache/pip pip install --retries 8 --disable-pip-version-check -r requirements-hub.lock
COPY app app
COPY sdk sdk
COPY examples examples
COPY policies policies
COPY scripts scripts
COPY docs/implementation/examples docs/implementation/examples
COPY alembic alembic
COPY alembic.ini ./
ENV PYTHONPATH=/hub PYTHONUNBUFFERED=1
CMD ["python", "scripts/local_entrypoint.py", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
