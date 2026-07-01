from typing import Any

from app.core.base_transformer import BaseTransformer
from app.core.models import Chunk, RawRecord


class SharePointTransformer(BaseTransformer):

    def transform(self, record: RawRecord) -> list[Chunk]:
        normalized = self._normalize(record.raw_data)
        return self._chunk(normalized)

    @staticmethod
    def _normalize(item: dict[str, Any]) -> dict[str, Any]:
        external_id = str(item.get("Id") or item.get("GUID") or item.get("UniqueId") or "")
        title = str(item.get("Title") or item.get("FileLeafRef") or external_id)

        metadata = {
            "list_title": item.get("ParentList") or item.get("ListId") or None,
            "created_at": item.get("Created"),
            "modified_at": item.get("Modified"),
            "author": SharePointTransformer._format_value(item.get("Author")),
            "editor": SharePointTransformer._format_value(item.get("Editor")),
            "file_ref": item.get("FileRef") or item.get("FileLeafRef"),
        }

        body_parts = [f"Title: {title}"]
        for key, value in item.items():
            if key in {"Title", "Id", "GUID", "UniqueId", "ParentList", "ListId", "Created", "Modified", "Author", "Editor", "FileRef", "FileLeafRef"}:
                continue
            if value is None:
                continue
            if isinstance(value, str) and value.strip():
                body_parts.append(f"{key}: {value}")
            elif isinstance(value, (int, float, bool)):
                body_parts.append(f"{key}: {value}")
            elif isinstance(value, dict):
                body_parts.append(f"{key}: {SharePointTransformer._format_value(value)}")

        return {
            "external_id": external_id,
            "title": title,
            "body": "\n\n".join(body_parts).strip(),
            "metadata": {k: v for k, v in metadata.items() if v is not None},
        }

    @staticmethod
    def _chunk(normalized: dict[str, Any]) -> list[Chunk]:
        content = f"[{normalized['external_id']}] {normalized['title']}\n\n{normalized['body']}"
        return [
            Chunk(
                chunk_id=f"sharepoint-{normalized['external_id']}-0",
                document_id=normalized["external_id"],
                source_type="sharepoint",
                content=content,
                metadata={**normalized["metadata"], "chunk_type": "body"},
            )
        ]

    @staticmethod
    def _format_value(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, dict):
            return ", ".join(
                f"{k}={v}" for k, v in value.items() if v is not None
            )
        return str(value)
