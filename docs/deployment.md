# Деплой и эксплуатация

## Режим хранения

### File (по умолчанию)
Подходит для локальной разработки и одиночных инстансов.

### Postgres (рекомендуется)

```bash
export SKILLOS_STORAGE_BACKEND=postgres
export SKILLOS_POSTGRES_DSN=postgresql://user:pass@host:5432/skillos
export SKILLOS_POSTGRES_SCHEMA=skillos
```

## Redis и rate limit

Если вы запускаете несколько инстансов или хотите строгий лимит:

```bash
export SKILLOS_RATE_LIMIT_STRICT=1
export SKILLOS_REDIS_URL=redis://localhost:6379/0
```

В strict-режиме Redis обязателен.

## Безопасность

- `SKILLOS_JWT_*` для JWT авторизации
- `SKILLOS_APPROVAL_TOKEN` для approvals
- `SKILLOS_WEBHOOK_SECRET` для вебхуков

## Health checks

`GET /health` возвращает `healthy/degraded/unhealthy` и ставит HTTP 503 при `unhealthy`.

## Пример systemd (опционально)

```ini
[Unit]
Description=SkillOS API
After=network.target

[Service]
User=skillos
WorkingDirectory=/opt/skillos
Environment=SKILLOS_ROOT=/opt/skillos/skills
ExecStart=/opt/skillos/.venv/bin/uvicorn skillos.api:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

## Docker (быстрый старт)

```bash
docker build -t skillos .
docker run --rm -p 8000:8000 -v "$PWD/skills:/app/skills" skillos
```

## Релизный минимум

1. `poetry run pytest -q`
2. `powershell -ExecutionPolicy Bypass -File scripts/smoke_v1.ps1`
3. `powershell -ExecutionPolicy Bypass -File scripts/smoke_postgres.ps1`
