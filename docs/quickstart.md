# Быстрый старт

## Требования

- Python 3.11+
- Poetry

## Установка

```bash
pip install poetry
poetry install
```

## Первый навык

```bash
poetry run skillos add-skill ops/hello --root ./skills
```

Откройте `skills/implementations/ops/hello.py` и измените логику при необходимости.

## Запуск запроса

```bash
poetry run skillos run "Hello" --root ./skills
```

## Композиция (последовательно и параллельно)

```bash
poetry run skillos compose-skill ops/plan --root ./skills \
  --step ops/hello \
  --step ops/hello

# параллельная группа (A|B)
poetry run skillos compose-skill ops/parallel --root ./skills \
  --step ops/hello|ops/hello
```

## Вебхук

1. Создайте триггер в `skills/triggers/webhooks.json`:

```json
{
  "webhooks": [
    {"id": "sample-hook", "skill_id": "ops/hello"}
  ]
}
```

2. Отправьте payload:

```bash
poetry run skillos webhook handle --id sample-hook --path ./payload.json --root ./skills \
  --signature "t=...,v1=..."
```

## API

```bash
poetry run uvicorn skillos.api:app --host 0.0.0.0 --port 8000
```

```bash
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{"query":"Hello","execute":false}'
```
