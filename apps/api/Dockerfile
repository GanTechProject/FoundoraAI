FROM python:3.13.15-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY pyproject.toml requirements.lock alembic.ini ./
COPY alembic ./alembic
COPY src ./src
RUN python -m pip install --no-cache-dir -r requirements.lock \
    && python -m pip install --no-cache-dir --no-deps .

FROM base AS development
COPY requirements-dev.lock ./
COPY tests ./tests
RUN python -m pip install --no-cache-dir -r requirements-dev.lock
CMD ["pytest"]

FROM base AS runtime
RUN groupadd --system --gid 10001 foundora && useradd --system --uid 10001 --gid foundora foundora \
    && chown -R foundora:foundora /app
USER foundora
EXPOSE 8000
CMD ["uvicorn", "foundora.main:app", "--host", "0.0.0.0", "--port", "8000"]
