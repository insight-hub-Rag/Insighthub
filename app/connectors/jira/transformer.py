"""
Transformer Jira : convertit un RawRecord (issue Jira brute) en une liste
de Chunk prêts à être vectorisés.

La logique de parsing (ADF → texte, découpage en chunks) est reprise à
l'identique du code existant — seule l'interface change pour respecter
BaseTransformer et produire le Chunk générique partagé (app.core.models).
"""

from typing import Any, Optional

from app.core.base_transformer import BaseTransformer
from app.core.models import Chunk, RawRecord

MAX_CHUNK_CHARS = 2000  # ~512 tokens approximatifs


class JiraTransformer(BaseTransformer):

    def transform(self, record: RawRecord) -> list[Chunk]:
        normalized = self._normalize(record.raw_data)
        return self._chunk(normalized)

    # ── Normalisation ───────────────────────────────────────────────────

    @staticmethod
    def _normalize(issue: dict) -> dict:
        """Extrait les champs utiles d'une issue Jira brute (format API v3)."""
        fields = issue["fields"]
        return {
            "external_id": issue["key"],
            "title": fields.get("summary", ""),
            "description": JiraTransformer._adf_to_text(fields.get("description")),
            "status": fields.get("status", {}).get("name", ""),
            "priority": (fields.get("priority") or {}).get("name", ""),
            "assignee": (fields.get("assignee") or {}).get("displayName", ""),
            "reporter": (fields.get("reporter") or {}).get("displayName", ""),
            "issue_type": fields.get("issuetype", {}).get("name", ""),
            "created_at": fields.get("created"),
            "updated_at": fields.get("updated"),
            "comments": JiraTransformer._extract_comments(
                fields.get("comment", {}).get("comments", [])
            ),
        }

    # ── Chunking ─────────────────────────────────────────────────────────

    @staticmethod
    def _chunk(normalized: dict) -> list[Chunk]:
        chunks: list[Chunk] = []
        external_id = normalized["external_id"]

        metadata = {
            "status": normalized["status"],
            "priority": normalized["priority"],
            "assignee": normalized["assignee"],
            "issue_type": normalized["issue_type"],
            "created_at": normalized["created_at"],
            "updated_at": normalized["updated_at"],
        }

        # Chunk principal : titre + description
        main_content = f"[{external_id}] {normalized['title']}\n\n{normalized['description']}"
        for i, text in enumerate(JiraTransformer._split_text(main_content)):
            chunks.append(Chunk(
                chunk_id=f"jira-{external_id}-{i}",
                document_id=external_id,
                source_type="jira",
                content=text,
                metadata={**metadata, "chunk_type": "body"},
            ))

        # Un chunk par commentaire
        for j, comment in enumerate(normalized["comments"]):
            text = f"[{external_id}] Commentaire de {comment['author']}:\n{comment['body']}"
            chunks.append(Chunk(
                chunk_id=f"jira-{external_id}-c{j}",
                document_id=external_id,
                source_type="jira",
                content=text[:MAX_CHUNK_CHARS],
                metadata={**metadata, "chunk_type": "comment", "comment_author": comment["author"]},
            ))

        return chunks

    @staticmethod
    def _split_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
        if len(text) <= max_chars:
            return [text]
        parts = []
        while text:
            parts.append(text[:max_chars])
            text = text[max_chars:]
        return parts

    @staticmethod
    def _extract_comments(comments: list) -> list[dict]:
        result = []
        for c in comments:
            result.append({
                "author": (c.get("author") or {}).get("displayName", ""),
                "body": JiraTransformer._adf_to_text(c.get("body")),
                "created": c.get("created"),
            })
        return result

    @staticmethod
    def _adf_to_text(adf: Optional[dict | str]) -> str:
        """Convertit l'Atlassian Document Format en texte brut."""
        if adf is None:
            return ""
        if isinstance(adf, str):
            return adf

        texts: list[str] = []

        def traverse(node: Any) -> None:
            if isinstance(node, dict):
                if node.get("type") == "text":
                    texts.append(node.get("text", ""))
                for child in node.get("content", []):
                    traverse(child)

        traverse(adf)
        return " ".join(texts).strip()