# SkillOS

[![Tests](https://github.com/AlexeyPevz/SkillOS/actions/workflows/tests.yml/badge.svg)](https://github.com/AlexeyPevz/SkillOS/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)


Фреймворк для оркестрации навыков (skills) с политиками доступа, утверждениями, бюджетами, дедупликацией и безопасными вебхуками. Проект рассчитан на self-hosted развертывание.

## Что внутри

- **Маршрутизация запросов** к навыкам (keywords/embeddings + веса).
- **Композиции** и **пайплайны** с параллельными группами.
- **Политики доступа** (roles/permissions) и **утверждения** на рискованные действия.
- **Бюджетирование** и контроль затрат.
- **Вебхуки** с проверкой подписи и вложениями.
- **Идемпотентность**, **джобы**, **расписания**.
- **Health checks**, метрики и трассировка.

## Быстрый старт

```bash
pip install poetry
poetry install

# создать навык
poetry run skillos add-skill travel/search_flights --root ./skills

# запустить запрос
poetry run skillos run "Find flights to Sochi" --root ./skills
```

Запуск API:

```bash
poetry run uvicorn skillos.api:app --host 0.0.0.0 --port 8000
```

## Архитектура и структура каталога

```
skills/
  metadata/         # YAML-описания навыков
  implementations/  # Python-реализации навыков
  policies/         # approval/permission политики
  runtime/          # служебные файлы (circuit breaker, idempotency и др.)
  attachments/      # файлы вложений вебхуков
  triggers/         # webhook-триггеры
  connectors/       # определения коннекторов
  secrets/          # секреты (например, .env)
```

## Основные понятия

- **Skill** — атомарное действие с YAML-метаданными и Python-реализацией.
- **Composition** — набор шагов (skills) с последовательным или параллельным исполнением.
- **Pipeline** — оркестрация набора шагов, включая параллельные группы (`skillA|skillB`).
- **Policies** — правила доступа и утверждений.
- **Budget** — лимиты на стоимость запросов.

## CLI (основные команды)

```bash
# оркестратор
poetry run skillos run "Find flights to Sochi" --root ./skills --execute

# пайплайн
poetry run skillos pipeline run --root ./skills --step ops/first --step ops/second --payload "start"

# вебхук
poetry run skillos webhook handle --id sample-hook --path ./payload.json --signature "t=...,v1=..." --root ./skills
```

Полный список и примеры: см. `docs/cli.md`.

## API

- `GET /health` — статус системы (возвращает 503 при `unhealthy`).
- `POST /run` — выполнение запроса.
- `POST /validate` — валидация навыков.
- `POST /skills/{id}/deprecate` — депрекейт.
- `POST /skills/{id}/undeprecate` — отмена депрекейта.

Пример:

```bash
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{"query":"Find flights to Sochi","execute":false}'
```

## Вебхуки и вложения

- Подписи HMAC обязательны по умолчанию. Можно разрешить unsigned через `SKILLOS_WEBHOOK_ALLOW_UNSIGNED=1`.
- Вложения передаются как base64 и сохраняются в `attachments/`.

Пример payload:

```json
{
  "payload": "hello",
  "attachments": [
    {
      "filename": "image.png",
      "content_type": "image/png",
      "data": "<base64>"
    }
  ]
}
```

Ограничения:
- Допустимые content-type включают: `application/json`, `application/pdf`, `text/plain`, `text/csv`, `text/markdown`, `text/html`, `image/*`.
- Максимальный размер: `SKILLOS_ATTACHMENT_MAX_SIZE_BYTES` (по умолчанию 10MB).

## Рейт-лимит

Есть два режима:

- **Best-effort** (по умолчанию): без обязательного Redis.
- **Strict**: атомарный Redis-лимитер, включается `SKILLOS_RATE_LIMIT_STRICT=1`.

В strict-режиме нужен Redis (`SKILLOS_REDIS_URL`/`REDIS_URL`). Если Redis не настроен — ошибка.

## Хранилище

Два варианта:

- `file` (по умолчанию) — локальные JSON/SQLite файлы.
- `postgres` — прод-режим с изоляцией по tenant.

Переменные:

- `SKILLOS_STORAGE_BACKEND=postgres`
- `SKILLOS_POSTGRES_DSN` или `DATABASE_URL`
- `SKILLOS_POSTGRES_SCHEMA` (опционально)

## Безопасность

- JWT: `SKILLOS_JWT_*` (алгоритм, issuer, audience, clock skew).
- Approval policies: `policies/approval_policies.json`.
- Permission policies: `policies/permission_policies.json`.

## Production чеклист (кратко)

1. Выбрать backend (`file`/`postgres`).
2. Настроить секреты и политики.
3. Включить строгий rate-limit при необходимости.
4. Прогнать тесты: `poetry run pytest -q`.
5. Запустить API.

Подробно: `docs/deployment.md`.

## Документация

- `docs/quickstart.md` — быстрый старт.
- `docs/concepts.md` — концепции и архитектура.
- `docs/deployment.md` — прод-обкатка и настройки.
- `docs/cli.md` — справочник по CLI.

## Вклад

См. `CONTRIBUTING.md` и `CODE_OF_CONDUCT.md`.

## Лицензия

MIT — см. `LICENSE`.
