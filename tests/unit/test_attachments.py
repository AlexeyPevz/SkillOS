import base64
from pathlib import Path

import pytest

from skillos.attachments import AttachmentError, ingest_attachments


def test_ingest_attachments_extracts_metadata(tmp_path: Path) -> None:
    payload = base64.b64encode(b"hello").decode("ascii")
    attachments = ingest_attachments(
        [
            {
                "filename": "note.txt",
                "content_type": "Text/Plain",
                "data": payload,
            }
        ],
        tmp_path,
        request_id="req-123",
    )

    assert len(attachments) == 1
    attachment = attachments[0]
    assert attachment.filename == "note.txt"
    assert attachment.content_type == "text/plain"
    assert attachment.size_bytes == 5
    stored = tmp_path / attachment.reference
    assert stored.exists()
    assert stored.read_bytes() == b"hello"


def test_ingest_attachments_rejects_invalid_payload(tmp_path: Path) -> None:
    with pytest.raises(AttachmentError):
        ingest_attachments(
            [{"filename": "note.txt", "content_type": "text/plain", "data": "@@"}],
            tmp_path,
        )
