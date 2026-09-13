# shop-api

Учебный сервис для отработки observability: генерирует реалистичный трафик метрик
и умеет ломаться по команде через chaos API.

- FastAPI + uvicorn, Python 3.12
- Postgres (SQLAlchemy 2.x async + asyncpg) — товары и заказы
- Redis (redis-py asyncio) — корзины (TTL 30 минут) и очередь задач
- Фоновый воркер в том же процессе: обрабатывает очередь, 3% задач падает с ретраем
- Метрики Prometheus объявлены вручную, без instrumentator
- Логи structlog в stdout, JSON

## Ручки

| Метод | Путь | Назначение |
| --- | --- | --- |
| POST | `/api/cart/{user_id}/items` | Добавить товар в корзину (Redis, TTL 30 мин) |
| GET | `/api/cart/{user_id}` | Текущая корзина |
| POST | `/api/checkout/{user_id}` | Создать заказ в Postgres и поставить задачу в очередь |
| GET | `/api/orders/{order_id}` | Заказ из Postgres |
| GET | `/api/products` | Каталог (200 товаров засеиваются при старте) |
| GET | `/healthz` | Liveness, 200 пока процесс жив |
| GET | `/readyz` | Readiness, 503 если недоступен Postgres или Redis |
| GET | `/metrics` | Экспорт Prometheus |
| GET/POST/DELETE | `/admin/chaos` | Управление поломками |

Описание метрик — в [docs/observability.md](../../docs/observability.md).

## Локальный запуск

Зависимости берутся из кластера через port-forward — отдельный Postgres/Redis поднимать не нужно:

```bash
kubectl -n sre-demo port-forward svc/postgres 5432:5432 &
kubectl -n sre-demo port-forward svc/redis 6379:6379 &
```

```bash
cd apps/shop-api
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
make run-local
```

Сервис поднимется на `http://localhost:8000`, при первом старте создаст таблицы
и засеет 200 товаров. Проверка:

```bash
curl -s localhost:8000/readyz | jq
curl -s 'localhost:8000/api/products?limit=3' | jq
curl -s -X POST localhost:8000/api/cart/u1/items -H 'Content-Type: application/json' -d '{"product_id": 7, "quantity": 2}' | jq
curl -s -X POST localhost:8000/api/checkout/u1 | jq
```

Конфигурация — только через переменные окружения с префиксом `SHOP_`
(`SHOP_POSTGRES_HOST`, `SHOP_REDIS_DB`, `SHOP_WORKER_FAILURE_RATE`, …),
полный список — в `app/config.py`. Строк подключения в коде нет.

## Тесты

```bash
cd apps/shop-api
make test
```

Это `pytest` (httpx AsyncClient, Postgres и Redis подменены на уровне
зависимостей FastAPI) и `mypy` в strict-режиме. Реальные Postgres и Redis
для тестов не нужны.

## Нагрузка

k6-скрипт — `loadgen/script.js`: 70% чтений, 25% добавлений в корзину, 5% checkout,
волна нагрузки с периодом 10 минут.

```bash
cd apps/shop-api
BASE_URL=http://localhost:8000 make load
```

В кластере то же самое крутит Deployment `shop-api-loadgen` (k6 в headless-режиме,
скрипт перезапускается в бесконечном цикле).

> Скрипт лежит в двух местах: `apps/shop-api/loadgen/script.js` — источник правды,
> `k8s/apps/shop-api/loadgen-configmap.yaml` — его копия для кластера
> (kustomize не умеет читать файлы за пределами своего каталога).
> После правки скрипта обнови ConfigMap.

## Сборка образа

```bash
cd apps/shop-api
make build IMAGE=ghcr.io/qwerfcxsssd/shop-api TAG=dev
```

В CI образ собирается под `linux/amd64` и `linux/arm64` и публикуется в
`ghcr.io/qwerfcxsssd/shop-api` с тегами `latest` и `<sha>`
(job `build-and-push-shop-api` в `.github/workflows/ci.yaml`).

## Деплой через ArgoCD

Манифесты — `k8s/apps/shop-api/` (kustomize, без Helm), Application — `k8s/argocd/shop-api-application.yaml`.

```bash
kubectl apply -f k8s/argocd/shop-api-application.yaml
kubectl -n argocd get application shop-api
kubectl -n sre-demo rollout status deploy/shop-api
```

Приложение синкается автоматически с `prune` и `selfHeal`, поэтому правки делаются
только в git. Существующее приложение `sre-demo-app` синкает `k8s/` без рекурсии
и подкаталог `k8s/apps/` не трогает.

Доступ к сервису для ручных проверок:

```bash
kubectl -n sre-demo port-forward svc/shop-api 8000:80
```

## Как воспроизвести инцидент

Состояние chaos живёт в памяти процесса: рестарт пода сбрасывает всё.
Так как реплик две, а port-forward идёт через Service, для предсказуемого
результата прокидывай порт напрямую в под:

```bash
POD=$(kubectl -n sre-demo get pod -l app.kubernetes.io/name=shop-api -o name | head -1)
kubectl -n sre-demo port-forward $POD 8000:8000
```

| Инцидент | Команда | Что происходит с сервисом |
| --- | --- | --- |
| Ровная деградация латентности | `curl -X POST localhost:8000/admin/chaos -H 'Content-Type: application/json' -d '{"latency_ms": 400}'` | Каждый ответ `/api/*` задерживается на 400 мс. `/healthz` и `/readyz` отвечают как раньше, под остаётся Ready. |
| Плавающая латентность | `curl -X POST localhost:8000/admin/chaos -H 'Content-Type: application/json' -d '{"latency_ms": 200, "latency_jitter_ms": 600}'` | Задержка размазывается от 200 до 800 мс, хвост распределения уезжает вправо. |
| Всплеск ошибок | `curl -X POST localhost:8000/admin/chaos -H 'Content-Type: application/json' -d '{"error_rate": 0.25}'` | Четверть запросов к `/api/*` отвечает 500 ещё до обработчика. Заказы не создаются, корзины не меняются. |
| Загруженный CPU | `curl -X POST localhost:8000/admin/chaos -H 'Content-Type: application/json' -d '{"cpu_burn": true}'` | Фоновый поток жжёт одно ядро, упираясь в лимит 500m. Обработка запросов замедляется, под продолжает проходить пробы. |
| Утечка памяти | `curl -X POST localhost:8000/admin/chaos -H 'Content-Type: application/json' -d '{"mem_leak_mb_per_min": 20}'` | Процесс накапливает по 20 МБ в минуту. При лимите 256Mi под уходит в OOMKilled примерно за 7–10 минут и перезапускается, chaos при этом сбрасывается. |
| Падение Postgres | `curl -X POST localhost:8000/admin/chaos -H 'Content-Type: application/json' -d '{"drop_postgres": true}'` | `/api/products`, `/api/orders/*` и checkout отвечают 503, `/readyz` становится 503 и под выводится из Service. Корзины в Redis продолжают работать. |
| Падение Redis | `curl -X POST localhost:8000/admin/chaos -H 'Content-Type: application/json' -d '{"drop_redis": true}'` | Корзины и checkout отвечают 503, воркер перестаёт разбирать очередь, `/readyz` — 503. Каталог из Postgres продолжает отдаваться. |
| Под «живой, но не готов» | `curl -X POST localhost:8000/admin/chaos -H 'Content-Type: application/json' -d '{"fail_readiness": true}'` | `/readyz` отдаёт 503 и под выпадает из эндпоинтов Service, но `/healthz` остаётся 200 — kubelet не перезапускает контейнер, трафик уходит на вторую реплику. |
| Взрыв кардинальности | `curl -X POST localhost:8000/admin/chaos -H 'Content-Type: application/json' -d '{"high_cardinality": true}'` | В `http_requests_total` добавляется лейбл `user_id`, и каждый пользователь из нагрузки начинает создавать собственные серии. Поведение API не меняется. |
| Сброс всего | `curl -X DELETE localhost:8000/admin/chaos` | Все инъекции выключаются, накопленная утечка освобождается, сервис возвращается в исходное состояние. |

Текущее состояние — `curl -s localhost:8000/admin/chaos | jq`.
Короткие обёртки: `make chaos-latency`, `make chaos-errors`, `make chaos-reset`
(переменная `BASE_URL`, по умолчанию `http://localhost:8000`).
