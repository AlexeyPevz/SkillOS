# CLI справочник

## Навыки

```bash
poetry run skillos add-skill travel/search_flights --root ./skills
poetry run skillos run-skill travel/search_flights --root ./skills
```

## Оркестрация

```bash
poetry run skillos run "Find flights to Sochi" --root ./skills
poetry run skillos run "Delete records" --root ./skills --execute --approval approved
poetry run skillos run "Delete records" --root ./skills --execute --dry-run --plan-path ./plan.json
```

## Пайплайн

```bash
poetry run skillos pipeline run --root ./skills --step ops/first --step ops/second --payload "start"
poetry run skillos pipeline run --root ./skills --step ops/first|ops/second --payload "start"
```

## Вебхуки

```bash
poetry run skillos webhook handle --id sample-hook --path ./payload.json --signature "t=...,v1=..." --root ./skills
```

## Джобы и расписания

```bash
poetry run skillos job enqueue travel/search_flights --root ./skills --payload "ok" --max-retries 2
poetry run skillos job work --root ./skills
poetry run skillos schedule add travel/search_flights --run-at 2026-01-18T08:00:00+03:00 --root ./skills
poetry run skillos schedule tick --root ./skills
```

## Метрики и тесты

```bash
poetry run skillos metrics --root ./skills --golden tests/fixtures/golden_queries.json
poetry run skillos test travel/search_flights --root ./skills
poetry run skillos validate --root ./skills
```

## Депрекейты

```bash
poetry run skillos deprecate-skill travel/search_flights --reason "use travel/search_hotels" --replacement travel/search_hotels --root ./skills
poetry run skillos undeprecate-skill travel/search_flights --root ./skills
```
