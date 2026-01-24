from __future__ import annotations

from dataclasses import dataclass
import base64
from pathlib import Path
from uuid import uuid4

from skillos.tenancy import resolve_tenant_root

class AttachmentError(ValueError):
    pass


@dataclass(frozen=True)
class AttachmentInput:
    filename: str
    content_type: str
    data: bytes


_DEFAULT_MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
_ALLOWED_CONTENT_TYPES = {
    "application/json",
    "application/pdf",
    "text/plain",
    "text/csv",
    "text/markdown",
    "text/html",  # Careful with this one, but often needed
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}


@dataclass(frozen=True)
class AttachmentReference:
    attachment_id: str
    filename: str
    content_type: str
    size_bytes: int
    reference: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.attachment_id,
            "filename": self.filename,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "reference": self.reference,
        }


def default_attachments_path(root: Path) -> Path:
    root_path = resolve_tenant_root(root)
    return root_path / "attachments"


def ingest_attachments(
    raw: object,
    root: Path,
    *,
    request_id: str | None = None,
) -> list[AttachmentReference]:
    attachments = _parse_attachments(raw)
    if not attachments:
        return []

    root_path = Path(root)
    attachments_root = default_attachments_path(root_path)
    batch_id = request_id or uuid4().hex
    batch_dir = attachments_root / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)

    references: list[AttachmentReference] = []
    for attachment in attachments:
        attachment_id = uuid4().hex
        stored_name = f"{attachment_id}_{attachment.filename}"
        stored_path = batch_dir / stored_name
        stored_path.write_bytes(attachment.data)
        reference = (Path("attachments") / batch_id / stored_name).as_posix()
        references.append(
            AttachmentReference(
                attachment_id=attachment_id,
                filename=attachment.filename,
                content_type=attachment.content_type,
                size_bytes=len(attachment.data),
                reference=reference,
            )
        )
    return references


def _parse_attachments(raw: object) -> list[AttachmentInput]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise AttachmentError("invalid_attachments")

    attachments: list[AttachmentInput] = []
    for item in raw:
        attachments.append(_parse_attachment(item))
    return attachments


def _parse_attachment(item: object) -> AttachmentInput:
    if not isinstance(item, dict):
        raise AttachmentError("invalid_attachment")

    filename = _normalize_filename(item.get("filename") or item.get("name"))
    if not filename:
        raise AttachmentError("invalid_attachment_name")

    content_type = _normalize_content_type(
        item.get("content_type") or item.get("type")
    )
    if not content_type:
        raise AttachmentError("invalid_attachment_type")

    data = item.get("data")
    if not isinstance(data, (str, bytes)):
        raise AttachmentError("invalid_attachment_data")
    try:
        payload = data.encode("utf-8") if isinstance(data, str) else data
        decoded = base64.b64decode(payload, validate=True)
    except ValueError as exc:
        raise AttachmentError("invalid_attachment_data") from exc

    if not decoded:
        raise AttachmentError("invalid_attachment_data")

    _validate_attachment_limits(content_type, len(decoded))

    return AttachmentInput(
        filename=filename,
        content_type=content_type,
        data=decoded,
    )


def _validate_attachment_limits(
    content_type: str,
    data_len: int,
) -> None:
    if content_type not in _ALLOWED_CONTENT_TYPES:
        # Strict allowlist
        raise AttachmentError(f"invalid_attachment_type: {content_type}")

    max_size = _env_int("SKILLOS_ATTACHMENT_MAX_SIZE_BYTES", _DEFAULT_MAX_SIZE_BYTES)
    if data_len > max_size:
        raise AttachmentError("attachment_too_large")


def _env_int(name: str, default: int) -> int:
    import os
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


def _normalize_filename(value: object) -> str:
    if value is None:
        return ""
    name = str(value).strip()
    if not name:
        return ""
    return Path(name).name


def _normalize_content_type(value: object) -> str:
    if value is None:
        return ""
    content_type = str(value).strip().lower()
    return content_type
