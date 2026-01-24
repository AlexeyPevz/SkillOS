from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Iterable, Mapping

import httpx
from dotenv import dotenv_values
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
import yaml

from skillos.telemetry import EventLogger, default_log_path, new_request_id
from skillos.tenancy import resolve_tenant_root


class ConnectorError(ValueError):
    pass


class ConnectorSchemaError(ConnectorError):
    def __init__(self, path: Path, errors: list[dict[str, object]]) -> None:
        super().__init__(f"Invalid connector definition in {path}: {errors}")
        self.path = path
        self.errors = errors


class SecretResolutionError(ConnectorError):
    pass


class RateLimitError(ConnectorError):
    pass


class ConnectorNotFoundError(ConnectorError):
    pass


_SECRET_PREFIX = "secret:"
_SECRET_ENV_PREFIX = "SKILLOS"


def _normalize_secret_token(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    return normalized.upper()


def build_secret_env_key(integration: str, key: str) -> str:
    integration_token = _normalize_secret_token(integration)
    key_token = _normalize_secret_token(key)
    if not integration_token or not key_token:
        raise SecretResolutionError("Secret key must include integration and key")
    return f"{_SECRET_ENV_PREFIX}_{integration_token}_{key_token}"


def default_connectors_path(root: Path) -> Path:
    root_path = resolve_tenant_root(root)
    return root_path / "connectors"


def default_secrets_path(root: Path) -> Path:
    root_path = resolve_tenant_root(root)
    return root_path / "secrets" / ".env"


@dataclass(frozen=True)
class SecretValue:
    key: str
    value: str
    source: str

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"SecretValue(key={self.key!r}, source={self.source!r}, value='[REDACTED]')"

    def __str__(self) -> str:
        return "[REDACTED]"


class SecretsStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        values = dotenv_values(self.path)
        return {key: value for key, value in values.items() if value is not None}


class SecretResolver:
    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        store: SecretsStore | None = None,
    ) -> None:
        self._env = env or os.environ
        self._store = store
        self._cached_store: dict[str, str] | None = None

    def resolve(self, key: str, *, integration: str | None = None) -> SecretValue:
        store_values = self._load_store()
        for candidate in _secret_key_candidates(key, integration):
            if candidate in self._env:
                return SecretValue(
                    key=candidate,
                    value=self._env[candidate],
                    source="env",
                )
            if candidate in store_values:
                return SecretValue(
                    key=candidate,
                    value=store_values[candidate],
                    source="store",
                )
        raise SecretResolutionError(f"Secret not found: {key}")

    def _load_store(self) -> dict[str, str]:
        if self._cached_store is not None:
            return self._cached_store
        if not self._store:
            self._cached_store = {}
        else:
            self._cached_store = self._store.load()
        return self._cached_store


def _is_secret_reference(value: str) -> bool:
    return value.startswith(_SECRET_PREFIX)


def _secret_key(value: str) -> str:
    return value[len(_SECRET_PREFIX) :].strip()


def _secret_key_candidates(key: str, integration: str | None) -> list[str]:
    candidates: list[str] = []
    if key.startswith(f"{_SECRET_ENV_PREFIX}_"):
        candidates.append(key)
    elif integration:
        candidates.append(build_secret_env_key(integration, key))
    candidates.append(key)
    return list(dict.fromkeys(candidates))


def collect_secret_refs(payload: object) -> set[str]:
    if isinstance(payload, str) and _is_secret_reference(payload):
        key = _secret_key(payload)
        return {key} if key else set()
    if isinstance(payload, dict):
        keys: set[str] = set()
        for value in payload.values():
            keys.update(collect_secret_refs(value))
        return keys
    if isinstance(payload, (list, tuple)):
        keys: set[str] = set()
        for value in payload:
            keys.update(collect_secret_refs(value))
        return keys
    return set()


def required_secrets_from_schema(root: Path, connector_id: str) -> set[str]:
    connectors_path = default_connectors_path(Path(root))
    if not connectors_path.exists():
        raise ConnectorNotFoundError(f"Unknown connector: {connector_id}")
    for file_path in _iter_connector_files(connectors_path):
        raw = _load_connector_file(file_path)
        if raw.get("id") != connector_id:
            continue
        return collect_secret_refs(raw)
    raise ConnectorNotFoundError(f"Unknown connector: {connector_id}")


def _resolve_secret_value(
    value: str,
    resolver: SecretResolver,
    *,
    integration: str | None = None,
) -> str | SecretValue:
    if _is_secret_reference(value):
        key = _secret_key(value)
        if not key:
            raise SecretResolutionError("Secret reference is missing a key")
        return resolver.resolve(key, integration=integration)
    return value


def _resolve_secret_mapping(
    payload: Mapping[str, object],
    resolver: SecretResolver,
    *,
    integration: str | None = None,
) -> dict[str, object]:
    resolved: dict[str, object] = {}
    for key, value in payload.items():
        if isinstance(value, str):
            resolved[key] = _resolve_secret_value(
                value,
                resolver,
                integration=integration,
            )
        elif isinstance(value, dict):
            resolved[key] = _resolve_secret_mapping(
                value,
                resolver,
                integration=integration,
            )
        elif isinstance(value, list):
            resolved[key] = _resolve_secret_sequence(
                value,
                resolver,
                integration=integration,
            )
        else:
            resolved[key] = value
    return resolved


def _resolve_secret_sequence(
    payload: Iterable[object],
    resolver: SecretResolver,
    *,
    integration: str | None = None,
) -> list[object]:
    resolved: list[object] = []
    for value in payload:
        if isinstance(value, str):
            resolved.append(
                _resolve_secret_value(
                    value,
                    resolver,
                    integration=integration,
                )
            )
        elif isinstance(value, dict):
            resolved.append(
                _resolve_secret_mapping(
                    value,
                    resolver,
                    integration=integration,
                )
            )
        elif isinstance(value, list):
            resolved.append(
                _resolve_secret_sequence(
                    value,
                    resolver,
                    integration=integration,
                )
            )
        else:
            resolved.append(value)
    return resolved


def resolve_secrets(
    payload: object,
    resolver: SecretResolver,
    *,
    integration: str | None = None,
) -> object:
    if isinstance(payload, str):
        return _resolve_secret_value(payload, resolver, integration=integration)
    if isinstance(payload, dict):
        return _resolve_secret_mapping(payload, resolver, integration=integration)
    if isinstance(payload, list):
        return _resolve_secret_sequence(payload, resolver, integration=integration)
    return payload


class HttpAuthSpec(BaseModel):
    type: str = Field(..., pattern="^(bearer|basic|header)$")
    token: str | None = None
    username: str | None = None
    password: str | None = None
    header: str | None = None
    value: str | None = None

    @model_validator(mode="after")
    def validate_required_fields(self) -> "HttpAuthSpec":
        if self.type == "bearer" and not self.token:
            raise ValueError("bearer auth requires token")
        if self.type == "basic" and (not self.username or not self.password):
            raise ValueError("basic auth requires username and password")
        if self.type == "header" and (not self.header or not self.value):
            raise ValueError("header auth requires header and value")
        return self


class HttpConnectorSpec(BaseModel):
    id: str = Field(..., min_length=2)
    type: str = Field("http", pattern="^http$")
    base_url: str
    headers: dict[str, str] = Field(default_factory=dict)
    auth: HttpAuthSpec | None = None
    timeout_seconds: float = 10.0
    rate_limit_per_minute: int | None = None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        if not value.startswith("http"):
            raise ValueError("base_url must start with http")
        return value.rstrip("/")

    @field_validator("rate_limit_per_minute")
    @classmethod
    def validate_rate_limit(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("rate_limit_per_minute must be positive")
        return value


class SqlConnectorSpec(BaseModel):
    id: str = Field(..., min_length=2)
    type: str = Field("sql", pattern="^sql$")
    driver: str = Field("sqlite", pattern="^(sqlite|postgres)$")
    dsn: str | None = None
    database_path: str | None = None

    @model_validator(mode="after")
    def validate_dsn(self) -> "SqlConnectorSpec":
        if self.driver == "postgres" and not self.dsn:
            raise ValueError("Postgres connectors require a DSN")
        return self


class VectorConnectorSpec(BaseModel):
    id: str = Field(..., min_length=2)
    type: str = Field("vector", pattern="^vector$")
    base_url: str
    api_key: str | None = None
    timeout_seconds: float = 10.0

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        if not value.startswith("http"):
            raise ValueError("base_url must start with http")
        return value.rstrip("/")


ConnectorSpec = HttpConnectorSpec | SqlConnectorSpec | VectorConnectorSpec


@dataclass
class RateLimiter:
    max_calls: int
    window_seconds: int = 60
    timestamps: deque[float] = field(default_factory=deque)

    def allow(self) -> bool:
        now = time.monotonic()
        while self.timestamps and now - self.timestamps[0] >= self.window_seconds:
            self.timestamps.popleft()
        if len(self.timestamps) >= self.max_calls:
            return False
        self.timestamps.append(now)
        return True


@dataclass
class HttpAuth:
    type: str
    token: str | SecretValue | None = None
    username: str | SecretValue | None = None
    password: str | SecretValue | None = None
    header: str | None = None
    value: str | SecretValue | None = None


@dataclass
class HttpConnector:
    connector_id: str
    base_url: str
    headers: dict[str, str | SecretValue]
    auth: HttpAuth | None
    timeout_seconds: float
    rate_limiter: RateLimiter | None = None
    connector_type: str = "http"
    root: Path | None = None
    logger: EventLogger | None = None

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        json: object | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        if self.rate_limiter and not self.rate_limiter.allow():
            self._log_call(
                status="rate_limited",
                latency_ms=0.0,
                method=method,
                url=self._build_url(path),
            )
            raise RateLimitError(f"Rate limit exceeded for {self.connector_id}")

        url = self._build_url(path)
        payload_headers = self._prepare_headers(headers)
        start = time.perf_counter()
        try:
            response = httpx.request(
                method,
                url,
                headers=payload_headers,
                params=params,
                json=json,
                timeout=timeout or self.timeout_seconds,
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            self._log_call(
                status="error",
                latency_ms=latency_ms,
                method=method,
                url=url,
                error_class=exc.__class__.__name__,
            )
            raise

        latency_ms = (time.perf_counter() - start) * 1000
        status = "success" if response.is_success else "error"
        self._log_call(
            status=status,
            latency_ms=latency_ms,
            method=method,
            url=url,
            status_code=response.status_code,
        )
        return response

    def _prepare_headers(self, overrides: dict[str, str] | None) -> dict[str, str]:
        merged = dict(self._materialize_headers(self.headers))
        if self.auth:
            merged.update(self._auth_headers(self.auth))
        if overrides:
            merged.update(overrides)
        return merged

    def _build_url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _materialize_headers(
        self, headers: Mapping[str, str | SecretValue]
    ) -> dict[str, str]:
        return {key: _materialize_secret(value) for key, value in headers.items()}

    def _auth_headers(self, auth: HttpAuth) -> dict[str, str]:
        if auth.type == "bearer":
            token = _materialize_secret(auth.token)
            return {"Authorization": f"Bearer {token}"}
        if auth.type == "basic":
            username = _materialize_secret(auth.username)
            password = _materialize_secret(auth.password)
            credentials = httpx.BasicAuth(username or "", password or "")
            return {"Authorization": credentials.auth_header}
        if auth.type == "header":
            header = auth.header or "Authorization"
            value = _materialize_secret(auth.value)
            return {header: value}
        return {}

    def _log_call(self, **fields: object) -> None:
        logger = self._resolve_logger()
        if not logger:
            return
        logger.log(
            "integration_call",
            connector_id=self.connector_id,
            connector_type=self.connector_type,
            **fields,
        )

    def _resolve_logger(self) -> EventLogger | None:
        if self.logger is not None:
            return self.logger
        if self.root is None:
            return None
        return EventLogger(default_log_path(self.root), request_id=new_request_id())


@dataclass
class VectorConnector:
    http: HttpConnector

    def request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        return self.http.request(method, path, **kwargs)

    def search(self, collection: str, payload: dict[str, object]) -> httpx.Response:
        return self.http.request(
            "POST",
            f"/collections/{collection}/points/search",
            json=payload,
        )

    def upsert(self, collection: str, payload: dict[str, object]) -> httpx.Response:
        return self.http.request(
            "PUT",
            f"/collections/{collection}/points",
            json=payload,
        )


@dataclass
class SqlConnector:
    connector_id: str
    driver: str
    dsn: str | SecretValue | None
    database_path: str | None
    root: Path | None = None
    logger: EventLogger | None = None

    def connect(self):
        start = time.perf_counter()
        try:
            if self.driver == "sqlite":
                db_path = self.database_path or ":memory:"
                connection = sqlite3.connect(db_path)
            else:
                dsn = _materialize_secret(self.dsn)
                try:
                    import psycopg
                except ImportError as exc:
                    raise ConnectorError("psycopg not installed") from exc
                if not dsn:
                    raise ConnectorError("Postgres DSN missing")
                connection = psycopg.connect(dsn)
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000
            self._log_call(
                status="error",
                latency_ms=latency_ms,
                operation="connect",
                error_class=exc.__class__.__name__,
            )
            raise

        latency_ms = (time.perf_counter() - start) * 1000
        self._log_call(
            status="success",
            latency_ms=latency_ms,
            operation="connect",
        )
        return connection

    def _log_call(self, **fields: object) -> None:
        logger = self._resolve_logger()
        if not logger:
            return
        logger.log(
            "integration_call",
            connector_id=self.connector_id,
            connector_type="sql",
            **fields,
        )

    def _resolve_logger(self) -> EventLogger | None:
        if self.logger is not None:
            return self.logger
        if self.root is None:
            return None
        return EventLogger(default_log_path(self.root), request_id=new_request_id())


def _materialize_secret(value: str | SecretValue | None) -> str:
    if isinstance(value, SecretValue):
        return value.value
    return "" if value is None else str(value)


class ConnectorRegistry:
    def __init__(
        self,
        root: Path,
        *,
        logger: EventLogger | None = None,
        request_id: str | None = None,
        env: Mapping[str, str] | None = None,
        secrets_path: Path | None = None,
    ) -> None:
        self.root = Path(root)
        self.logger = logger
        self.request_id = request_id
        secrets_file = secrets_path or default_secrets_path(self.root)
        self.resolver = SecretResolver(
            env=env,
            store=SecretsStore(secrets_file),
        )
        self._connectors: dict[str, object] = {}
        self._secret_refs: dict[str, set[str]] = {}

    def load_all(self, path: Path | None = None) -> dict[str, object]:
        connectors_path = Path(path) if path else default_connectors_path(self.root)
        self._connectors = {}
        self._secret_refs = {}
        if not connectors_path.exists():
            return self._connectors

        for file_path in _iter_connector_files(connectors_path):
            raw = _load_connector_file(file_path)
            try:
                spec = _validate_spec(raw)
            except ConnectorError as exc:
                raise ConnectorSchemaError(
                    file_path,
                    [
                        {
                            "loc": ("type",),
                            "msg": str(exc),
                            "input": raw.get("type"),
                        }
                    ],
                ) from exc
            except ValidationError as exc:
                raise ConnectorSchemaError(file_path, exc.errors()) from exc
            self._secret_refs[spec.id] = collect_secret_refs(raw)
            connector = self._build_connector(spec)
            self._connectors[spec.id] = connector
        return self._connectors

    def get(self, connector_id: str) -> object:
        connector = self._connectors.get(connector_id)
        if not connector:
            raise ConnectorNotFoundError(f"Unknown connector: {connector_id}")
        return connector

    def required_secrets(self, connector_id: str) -> set[str]:
        return set(self._secret_refs.get(connector_id, set()))

    def _build_connector(self, spec: ConnectorSpec) -> object:
        if isinstance(spec, HttpConnectorSpec):
            return self._build_http_connector(spec)
        if isinstance(spec, SqlConnectorSpec):
            return self._build_sql_connector(spec)
        if isinstance(spec, VectorConnectorSpec):
            return self._build_vector_connector(spec)
        raise ConnectorError(f"Unsupported connector type: {spec}")

    def _build_http_connector(self, spec: HttpConnectorSpec) -> HttpConnector:
        headers = {
            key: _resolve_secret_value(
                value,
                self.resolver,
                integration=spec.id,
            )
            for key, value in spec.headers.items()
        }
        auth = _resolve_auth(spec.auth, self.resolver, integration=spec.id)
        rate_limiter = (
            RateLimiter(spec.rate_limit_per_minute)
            if spec.rate_limit_per_minute
            else None
        )
        return HttpConnector(
            connector_id=spec.id,
            base_url=spec.base_url,
            headers=headers,
            auth=auth,
            timeout_seconds=spec.timeout_seconds,
            rate_limiter=rate_limiter,
            connector_type="http",
            root=self.root,
            logger=self._resolve_logger(),
        )

    def _build_vector_connector(self, spec: VectorConnectorSpec) -> VectorConnector:
        headers: dict[str, str | SecretValue] = {}
        if spec.api_key:
            headers["api-key"] = _resolve_secret_value(
                spec.api_key,
                self.resolver,
                integration=spec.id,
            )
        http_connector = HttpConnector(
            connector_id=spec.id,
            base_url=spec.base_url,
            headers=headers,
            auth=None,
            timeout_seconds=spec.timeout_seconds,
            rate_limiter=None,
            connector_type="vector",
            root=self.root,
            logger=self._resolve_logger(),
        )
        return VectorConnector(http=http_connector)

    def _build_sql_connector(self, spec: SqlConnectorSpec) -> SqlConnector:
        dsn = None
        if spec.dsn:
            dsn = _resolve_secret_value(
                spec.dsn,
                self.resolver,
                integration=spec.id,
            )
        return SqlConnector(
            connector_id=spec.id,
            driver=spec.driver,
            dsn=dsn,
            database_path=spec.database_path,
            root=self.root,
            logger=self._resolve_logger(),
        )

    def _resolve_logger(self) -> EventLogger | None:
        if self.logger is not None:
            return self.logger
        if self.request_id:
            return EventLogger(default_log_path(self.root), request_id=self.request_id)
        return None


def scaffold_connector(
    connector_id: str,
    root: Path,
    connector_type: str = "http",
) -> Path:
    root_path = Path(root)
    connectors_path = default_connectors_path(root_path)
    connectors_path.mkdir(parents=True, exist_ok=True)

    filename = f"{connector_id}.yaml"
    connector_file = connectors_path / filename
    if connector_file.exists():
        raise FileExistsError("Connector already exists")

    payload = _connector_template(connector_id, connector_type)
    connector_file.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )
    return connector_file


def resolve_skills_root(root: Path | None = None) -> Path:
    if root is not None:
        return Path(root)
    env_root = os.getenv("SKILLOS_ROOT")
    if env_root:
        return Path(env_root)
    from skillos.skills.paths import default_skills_root

    return default_skills_root()


def _connector_template(connector_id: str, connector_type: str) -> dict[str, object]:
    if connector_type == "http":
        return {
            "id": connector_id,
            "type": "http",
            "base_url": "https://api.example.com",
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": "secret:API_TOKEN"},
            "timeout_seconds": 10,
            "rate_limit_per_minute": 60,
        }
    if connector_type == "sql":
        return {
            "id": connector_id,
            "type": "sql",
            "driver": "sqlite",
            "database_path": ":memory:",
        }
    if connector_type == "vector":
        return {
            "id": connector_id,
            "type": "vector",
            "base_url": "http://localhost:6333",
            "api_key": "secret:QDRANT_API_KEY",
            "timeout_seconds": 10,
        }
    raise ConnectorError(f"Unsupported connector type: {connector_type}")


def _iter_connector_files(connectors_path: Path) -> Iterable[Path]:
    yaml_files = list(connectors_path.rglob("*.yaml"))
    yml_files = list(connectors_path.rglob("*.yml"))
    json_files = list(connectors_path.rglob("*.json"))
    return sorted(yaml_files + yml_files + json_files)


def _load_connector_file(path: Path) -> dict[str, object]:
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _validate_spec(raw: dict[str, object]) -> ConnectorSpec:
    connector_type = raw.get("type", "http")
    if connector_type == "http":
        return HttpConnectorSpec.model_validate(raw)
    if connector_type == "sql":
        return SqlConnectorSpec.model_validate(raw)
    if connector_type == "vector":
        return VectorConnectorSpec.model_validate(raw)
    raise ConnectorError("Unsupported connector type")


def _resolve_auth(
    auth: HttpAuthSpec | None,
    resolver: SecretResolver,
    *,
    integration: str | None = None,
) -> HttpAuth | None:
    if not auth:
        return None
    return HttpAuth(
        type=auth.type,
        token=_resolve_secret_value(
            auth.token,
            resolver,
            integration=integration,
        )
        if auth.token
        else None,
        username=_resolve_secret_value(
            auth.username,
            resolver,
            integration=integration,
        )
        if auth.username
        else None,
        password=_resolve_secret_value(
            auth.password,
            resolver,
            integration=integration,
        )
        if auth.password
        else None,
        header=auth.header,
        value=_resolve_secret_value(auth.value, resolver, integration=integration)
        if auth.value
        else None,
    )
