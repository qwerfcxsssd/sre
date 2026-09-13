IMAGE ?= ghcr.io/qwerfcxsssd/shop-api
TAG ?= dev
BASE_URL ?= http://localhost:8000
VERSION ?= $(TAG)
COMMIT ?= $(shell git rev-parse --short HEAD 2>/dev/null || echo unknown)

.PHONY: build run-local test load chaos-latency chaos-errors chaos-reset

build:
	docker build --build-arg VERSION=$(VERSION) --build-arg COMMIT=$(COMMIT) -t $(IMAGE):$(TAG) .

run-local:
	SHOP_POSTGRES_HOST=$${SHOP_POSTGRES_HOST:-localhost} \
	SHOP_POSTGRES_DB=$${SHOP_POSTGRES_DB:-sredb} \
	SHOP_POSTGRES_USER=$${SHOP_POSTGRES_USER:-sreuser} \
	SHOP_POSTGRES_PASSWORD=$${SHOP_POSTGRES_PASSWORD:-srepass} \
	SHOP_REDIS_HOST=$${SHOP_REDIS_HOST:-localhost} \
	SHOP_REDIS_DB=$${SHOP_REDIS_DB:-1} \
	SHOP_LOG_LEVEL=$${SHOP_LOG_LEVEL:-INFO} \
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --no-access-log

test:
	pytest -q
	mypy

load:
	BASE_URL=$(BASE_URL) k6 run loadgen/script.js

chaos-latency:
	curl -fsS -X POST $(BASE_URL)/admin/chaos \
		-H 'Content-Type: application/json' \
		-d '{"latency_ms": 400, "latency_jitter_ms": 200}' | tee /dev/stderr >/dev/null

chaos-errors:
	curl -fsS -X POST $(BASE_URL)/admin/chaos \
		-H 'Content-Type: application/json' \
		-d '{"error_rate": 0.25}' | tee /dev/stderr >/dev/null

chaos-reset:
	curl -fsS -X DELETE $(BASE_URL)/admin/chaos | tee /dev/stderr >/dev/null
