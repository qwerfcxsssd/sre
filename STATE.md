# SRE-стенд: что построено и как это работает

Документ описывает текущее состояние локального стенда на 13 сентября 2026.
Положить в репозиторий как `docs/STATE.md`.

---

## 1. Общая картина

Есть локальный Kubernetes-кластер, внутри него три слоя:

1. Инфраструктура кластера (k3s и его системные компоненты)
2. Слой доставки (ArgoCD, который приводит кластер в состояние, описанное в гите)
3. Полезная нагрузка: два приложения и стек мониторинга

Всё, что деплоится, описано в репозитории `github.com/qwerfcxsssd/sre`.
Кластер это следствие содержимого гита, а не самостоятельная сущность.
Потерять кластер не страшно, потерять репозиторий страшно.

---

## 2. Ноды

Кластер `mycluster`, поднят через k3d. k3d это обёртка, которая запускает
k3s внутри Docker-контейнеров. То есть "нода" здесь это не виртуальная машина,
а контейнер на твоём макбуке.

| Нода | Роль | Что делает |
|---|---|---|
| k3d-mycluster-server-0 | control-plane | API-сервер, etcd (в k3s это sqlite), scheduler, controller-manager. Тоже запускает поды. |
| k3d-mycluster-agent-0 | worker | Только запускает поды |
| k3d-mycluster-agent-1 | worker | Только запускает поды |

Версия: k3s v1.35.5+k3s1, архитектура arm64.

Плюс отдельный контейнер `k3d-mycluster-serverlb`. Это не нода, а haproxy,
который принимает трафик с хоста и раздаёт его на ноды. Через него проброшен
порт 8080 твоего мака на порт 80 внутри кластера.

Важная особенность k3s: kube-scheduler, kube-controller-manager и kube-proxy
не работают отдельными подами, они вкомпилированы в один бинарь k3s.
Поэтому метрики с них по стандартным адресам не снимаются, и в values
мониторинга они отключены. Вместо etcd в k3s используется встроенный sqlite.

---

## 3. Namespace и поды

### kube-system, системное

| Под | Назначение |
|---|---|
| coredns | DNS внутри кластера. Именно он превращает `shop-api` в IP-адрес сервиса. Если он лежит, всё разваливается непредсказуемым образом. |
| local-path-provisioner | Динамически создаёт PersistentVolume на диске ноды. Благодаря ему PVC Prometheus на 5Gi получил хранилище без внешнего стораджа. |
| metrics-server | Отдаёт метрики для `kubectl top` и HorizontalPodAutoscaler. К Prometheus отношения не имеет, это другой механизм. |
| traefik | Ingress-контроллер, идёт в составе k3s. Принимает HTTP снаружи и маршрутизирует по Ingress-ресурсам. Пока не используешь. |
| svclb-traefik (3 штуки) | По одному на ноду. Это DaemonSet, который эмулирует LoadBalancer: слушает порт на ноде и проксирует в сервис traefik. |
| helm-install-traefik (Completed) | Разовая job, которая установила traefik при создании кластера. Висит в списке навсегда, это нормально. |

### argocd, слой доставки

| Под | Назначение |
|---|---|
| argocd-application-controller | Мозг. Сравнивает желаемое состояние (гит) с фактическим (кластер) и устраняет расхождение. Именно он делает sync и selfHeal. |
| argocd-repo-server | Клонирует репозиторий и рендерит манифесты: прогоняет kustomize или helm и отдаёт контроллеру готовый YAML. |
| argocd-server | API и веб-интерфейс. |
| argocd-redis | Кеш для repo-server, чтобы не рендерить манифесты на каждый цикл. |
| argocd-applicationset-controller | Генерация Application по шаблону. Пока не используешь. |
| argocd-notifications-controller | Уведомления в Slack и прочее. Пока не используешь. |
| argocd-dex-server | SSO через внешних провайдеров. На локальном стенде не нужен, но входит в стандартную установку. |

Два Application:

- `sre-demo-app` управляет старым приложением (api, postgres, redis)
- `shop-api` управляет новым сервисом и генератором нагрузки

Оба в статусе Synced/Healthy.

### monitoring, стек наблюдаемости

Установлен helm-релизом `monitoring`, чарт kube-prometheus-stack 91.2.0,
prometheus-operator v0.94.0.

| Под | Назначение |
|---|---|
| prometheus-...-prometheus-0 (2/2) | Сам Prometheus плюс сайдкар config-reloader, который перечитывает конфиг без рестарта. Хранит метрики 24 часа на PVC 5Gi. |
| monitoring-kube-prometheus-operator | Оператор. Следит за ресурсами ServiceMonitor, PodMonitor, PrometheusRule и превращает их в конфиг Prometheus. Без него ты бы правил prometheus.yml руками. |
| monitoring-kube-state-metrics | Опрашивает API Kubernetes и выдаёт метрики о состоянии объектов: сколько реплик хочет Deployment, сколько готово, в каком поде какой статус. Это метрики про Kubernetes, а не про железо. |
| monitoring-prometheus-node-exporter (3 штуки) | DaemonSet, по одному на ноду. Метрики хоста: CPU, память, диск, сеть, загрузка. |
| monitoring-grafana (3/3) | Grafana плюс два сайдкара: один подхватывает дашборды из ConfigMap с лейблом `grafana_dashboard`, второй датасорсы. |
| alertmanager-...-0 (2/2) | Принимает сработавшие алерты от Prometheus, группирует, дедуплицирует, подавляет и рассылает. Prometheus сам ничего не отправляет, он только вычисляет правила. |

### sre-demo, приложения

| Под | Назначение |
|---|---|
| api (2 реплики) | Старое учебное приложение на FastAPI. Работает 48 дней. |
| postgres | Одна база `sredb` на оба приложения. Таблицы shop-api отдельные. |
| redis | Общий. shop-api использует базу с индексом 1, чтобы ключи не пересекались со старым api. |
| shop-api (2 реплики) | Новый сервис, подробно ниже. |
| shop-api-loadgen | k6 в бесконечном цикле, генерирует трафик по shop-api. |

---

## 4. Что делает shop-api

Это не продукт, это тренажёр. Задача сервиса: выдавать реалистичные метрики
и ломаться по команде, чтобы на нём можно было тренировать алерты, SLO
и расследование инцидентов.

### Бизнес-логика

Упрощённый интернет-магазин:

- `GET /api/products` отдаёт каталог из Postgres, при старте засеивается 200 товаров
- `POST /api/cart/{user_id}/items` кладёт товар в корзину в Redis, TTL 30 минут
- `GET /api/cart/{user_id}` читает корзину
- `POST /api/checkout/{user_id}` превращает корзину в заказ в Postgres и ставит задачу в очередь (список в Redis)
- `GET /api/orders/{order_id}` отдаёт заказ

Внутри того же процесса крутится фоновый воркер: раз в секунду забирает
задачу из очереди, обрабатывает 50-400 мс, примерно 3% задач падает
и уходит в ретрай. Это сделано специально, чтобы очередь не была всегда
пустой, а на графиках был живой шум.

### Служебные ручки

- `/healthz` liveness. Отвечает 200, пока процесс жив. Kubelet по нему решает, надо ли перезапустить контейнер.
- `/readyz` readiness. Отвечает 503, если Postgres или Redis недоступны. Kubelet по нему решает, слать ли в под трафик. Под при этом остаётся жив.
- `/metrics` экспорт для Prometheus в текстовом формате.

Разница между liveness и readiness принципиальна. Liveness лечит зависший
процесс перезапуском. Readiness убирает под из балансировки, пока он не готов.
Путать их опасно: если повесить liveness на проверку базы, то при падении
Postgres кластер начнёт бесконечно перезапускать все реплики приложения
и добьёт то, что ещё работало.

Отдельное решение в коде: миграции вынесены в фоновую задачу. Если гонять
их в lifespan, приложение не слушает порт до их завершения, liveness успевает
три раза не достучаться и убивает под. Получается crash loop при недоступной
базе. Теперь порт открывается сразу, а трафик не пускает readiness.

### Метрики

| Метрика | Тип | Что показывает |
|---|---|---|
| http_requests_total{method, route, status} | counter | Сколько запросов обработано. Основа для RPS и доли ошибок. |
| http_request_duration_seconds{method, route} | histogram | Распределение времени ответа. Из неё считаются перцентили. |
| http_requests_in_flight | gauge | Сколько запросов обрабатывается прямо сейчас. |
| app_orders_created_total{result} | counter | Бизнес-метрика: заказы успешные и упавшие. |
| app_order_amount_rubles | histogram | Распределение сумм заказов. |
| app_queue_depth | gauge | Длина очереди в Redis, обновляется раз в 5 секунд. |
| app_worker_jobs_total{result} | counter | Обработка задач: success, retry, dead. |
| app_worker_job_duration_seconds | histogram | Время обработки задачи. |
| app_dependency_up{dependency} | gauge | Доступность Postgres и Redis, проверка раз в 10 секунд. |
| app_cache_operations_total{operation, result} | counter | Попадания и промахи кеша. |
| app_db_pool_connections{state} | gauge | Занятые и свободные соединения в пуле. |
| app_build_info{version, commit, python_version} | gauge | Всегда 1. Способ протащить версию сборки в метрики. |

Три типа метрик, которые надо различать:

counter только растёт, его значение само по себе бессмысленно, смотреть
надо производную через `rate()`. gauge может расти и падать, его смотрят
как есть. histogram раскладывает наблюдения по корзинам и позволяет
посчитать перцентиль через `histogram_quantile()`.

Бакеты в `http_request_duration_seconds` выбраны от 5 мс до 10 с
неравномерно, с уплотнением в районе 50-250 мс. Там живут реальные
значения, и там нужна точность. Перцентиль на гистограмме считается
интерполяцией внутри бакета, поэтому в плотной зоне бакеты должны быть
частыми, иначе p99 будет врать.

### Chaos API

Роутер `/admin/chaos`, без аутентификации, это локальный стенд.

| Параметр | Эффект | Что тренирует |
|---|---|---|
| latency_ms, latency_jitter_ms | Искусственная задержка на всех `/api` | Алерты на перцентили, разница между средним и p99 |
| error_rate | Доля ответов 500 | Error budget, burn rate |
| cpu_burn | Фоновый поток жжёт ядро | Троттлинг по CPU limit, разница между requests и limits |
| mem_leak_mb_per_min | Утечка памяти | OOMKilled, поведение при memory limit |
| drop_postgres, drop_redis | Обращения к зависимости падают | Каскадные отказы, readiness |
| fail_readiness | 503 на /readyz при живом поде | Как Service выкидывает под из эндпоинтов |
| high_cardinality | Добавляет лейбл user_id в http_requests_total | Взрыв кардинальности, деградация Prometheus |

Состояние живёт в памяти процесса и сбрасывается при рестарте. Реплик две,
поэтому curl через port-forward попадёт только в одну из них.

`http_requests_total` реализована не обычным Counter, а кастомным коллектором:
у Counter набор лейблов фиксируется при создании, а режим high_cardinality
должен добавлять лейбл на лету в то же семейство метрик.

### Генератор нагрузки

Отдельный Deployment с k6. Профиль: 70% чтений, 25% добавлений в корзину,
5% checkout. Нагрузка идёт волнами с периодом 10 минут через
ramping-arrival-rate, VU плавают в диапазоне до 20. Волны нужны, чтобы
графики не были плоской линией и на них было видно суточные паттерны
в миниатюре.

Текущая интенсивность около 22 итераций в секунду.

---

## 5. Как это всё связано

### Путь изменения в GitOps

```
правка в репозитории
  -> git push
  -> argocd-repo-server клонирует и рендерит kustomize
  -> argocd-application-controller видит расхождение
  -> применяет манифесты в кластер
  -> ресурсы обновляются
```

Из этого следует правило: руками в кластер не лезем. Если сделать
`kubectl scale`, контроллер с включённым selfHeal вернёт как в гите.
Это не баг, это смысл GitOps. Единственный источник правды один.

### Путь метрики

```
приложение считает метрику в памяти
  -> отдаёт текстом на /metrics
  -> Prometheus раз в 15 секунд делает HTTP-запрос на этот эндпоинт (scrape)
  -> сохраняет точку в TSDB
  -> Grafana выполняет PromQL-запрос к Prometheus и рисует
  -> Prometheus раз в интервал вычисляет правила алертов
  -> сработавшие уходят в Alertmanager
  -> Alertmanager группирует и отправляет наружу
```

Ключевой момент: Prometheus ходит за метриками сам (pull), приложение
никуда ничего не отправляет. Поэтому Prometheus должен знать, куда ходить.
Этим занимается service discovery.

### Две группы метрик, которые легко перепутать

Инфраструктурные метрики про shop-api уже есть в Grafana, потому что
kubelet со встроенным cAdvisor снимает CPU и память с любого контейнера
в кластере, а kube-state-metrics знает о статусе любого пода. Для этого
от приложения ничего не требуется.

Прикладные метрики (http_requests_total и остальные) Prometheus пока
не собирает. Аннотации `prometheus.io/scrape` в deployment на
prometheus-operator не действуют, это механизм из другой схемы установки.
Оператору нужен ресурс ServiceMonitor.

Проверяется одной командой в Explore:

```
up{job="shop-api"}
```

Пусто значит таргета нет.

---

## 6. Что уже сделано

- Кластер k3d на три ноды, порт 8080 проброшен
- ArgoCD, два Application, оба Synced/Healthy
- CI в GitHub Actions, образы в ghcr.io/qwerfcxsssd
- Старое приложение api + postgres + redis, работает 48 дней
- Сервис shop-api: код, тесты (19 штук), Dockerfile, kustomize-манифесты
- Генератор нагрузки k6, трафик идёт постоянно
- kube-prometheus-stack: Prometheus, Alertmanager, Grafana, node-exporter, kube-state-metrics
- Values мониторинга в репозитории, отключены отсутствующие в k3s компоненты
- Проброс Grafana через port-forward, дефолтные дашборды работают

## 7. Что дальше

По возрастанию сложности:

1. ServiceMonitor для shop-api. Пока его нет, вся прикладная часть невидима.
2. Первый простой алерт в PrometheusRule. Что-нибудь вроде ShopApiDependencyDown.
3. Свой дашборд в Grafana: RED-метрики по route. Собрать в UI, экспортировать json, положить в репозиторий.
4. Recording rules и SLO 99.5% с multi-window burn rate.
5. Runbooks на каждый алерт с командой воспроизведения через chaos API.
6. Ingress через traefik вместо port-forward.
7. Loki для логов, structlog уже пишет JSON в stdout.
8. Chaos Mesh для отказов на уровне инфраструктуры, а не приложения.

## 8. Открытые вопросы к текущей конфигурации

Три места, которые стоит поправить осознанно:

1. Postgres один на два приложения. Ошибка в миграции shop-api уронит и старое api. Правильно развести по разным базам.
2. Скрипт k6 продублирован: оригинал в `apps/shop-api/loadgen/script.js`, копия в ConfigMap. Разъедется. Лечится configMapGenerator в kustomize.
3. Стек мониторинга поставлен руками через helm, а не через ArgoCD. На этапе настройки так удобнее, но потом надо завести под GitOps, иначе в кластере есть состояние, которого нет в гите.

---

## 9. Шпаргалка по командам

Кластер:

```
k3d cluster list
k3d cluster start mycluster
kubectl get nodes
kubectl get pods -A
```

ArgoCD:

```
kubectl -n argocd get applications
kubectl -n argocd describe app shop-api | tail -30
kubectl -n argocd port-forward svc/argocd-server 8081:443
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
```

Мониторинг:

```
kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80
kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-prometheus 9090:9090
kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-alertmanager 9093:9093
helm -n monitoring list
```

Итоговый конфиг Prometheus, который собрал оператор:

```
kubectl -n monitoring get secret prometheus-monitoring-kube-prometheus-prometheus \
  -o jsonpath='{.data.prometheus\.yaml\.gz}' | base64 -d | gunzip
```

Приложение:

```
kubectl -n sre-demo get pods
kubectl -n sre-demo logs deploy/shop-api --tail=50
kubectl -n sre-demo logs deploy/shop-api-loadgen --tail=20
kubectl -n sre-demo port-forward svc/shop-api 8000:80
curl -s localhost:8000/metrics | grep '^app_'
```

Хаос:

```
curl -s -X POST localhost:8000/admin/chaos -H 'Content-Type: application/json' -d '{"latency_ms": 500}'
curl -s localhost:8000/admin/chaos
curl -s -X DELETE localhost:8000/admin/chaos
```
