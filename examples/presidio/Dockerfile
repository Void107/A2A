FROM python:3.12.14-slim
WORKDIR /hub
COPY requirements-presidio.lock ./
RUN --mount=type=cache,id=a2a-presidio-pip,target=/root/.cache/pip pip install --retries 8 --disable-pip-version-check -r requirements-presidio.lock
COPY examples/presidio examples/presidio
COPY app/profile.py app/profile.py
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "uvicorn", "examples.presidio.service:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
