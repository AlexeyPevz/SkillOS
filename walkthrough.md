# Production Readiness Walkthrough

Краткий обзор изменений, которые доводят SkillOS до production-ready состояния.

## 1. Безопасность

### Лимиты вложений

- Максимальный размер: `SKILLOS_ATTACHMENT_MAX_SIZE_BYTES` (по умолчанию 10MB).
- Разрешенные типы: `application/json`, `application/pdf`, `text/plain`, `text/csv`, `text/markdown`, `text/html`, `image/*`.

### JWT

В проде (`SKILLOS_ENV=prod`) запрещены неподписанные токены независимо от флагов.

### Вебхуки

- Подпись HMAC обязательна по умолчанию.
- Опционально можно разрешить unsigned: `SKILLOS_WEBHOOK_ALLOW_UNSIGNED=1`.

### Rate limiting

- Best-effort режим доступен без Redis.
- Strict режим (`SKILLOS_RATE_LIMIT_STRICT=1`) использует Redis + атомарный Lua.
- Ключи scoped по tenant: `tenant:{tenant_id}:webhook:{trigger_id}`.

## 2. Надежность

### DLQ Recovery

Метод `requeue_dead_letters` переводит `failed` задания обратно в `queued` и увеличивает `max_retries`.

### Порядок бюджетных проверок

Бюджет списывается только после Permission/Approval/Circuit, чтобы не списывать за запрещенные запросы.

### Circuit Breaker

Запись состояния теперь защищена файловым локом при параллельном исполнении.

## 3. Операционная готовность

### Health checks

`/health` возвращает `healthy|degraded|unhealthy` и выставляет HTTP 503 при `unhealthy`.
Проверки включают диск, базу и кэш.

### Централизованный config

`skillos/config.py` — единая точка чтения ключевых env-настроек.

## 4. Тестовая инфраструктура

Фикстуры генерируют dummy-реализации для entrypoint'ов из `golden_skill_catalog.json`.

## Валидация

- `pytest -q` — все тесты проходят локально.
- Основные кейсы: security, DLQ, вебхуки, пайплайны, health.
