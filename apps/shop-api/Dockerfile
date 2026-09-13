FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY pyproject.toml ./
COPY app ./app

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install .

FROM python:3.12-slim AS runtime

ARG VERSION=0.0.0
ARG COMMIT=unknown

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SHOP_VERSION=${VERSION} \
    SHOP_COMMIT=${COMMIT}

RUN useradd --uid 10001 --user-group --create-home --shell /usr/sbin/nologin shop

COPY --from=builder /opt/venv /opt/venv

WORKDIR /srv
USER 10001
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
