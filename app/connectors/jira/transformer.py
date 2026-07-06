from typing import Any, Optional

from app.core.base_transformer import BaseTransformer
from app.core.models import Chunk, RawRecord

MAX_CHUNK_CHARS = 1500
OVERLAP_CHARS   = 150


class JiraTransformer(BaseTransformer):

    def transform(self, record: RawRecord) -> list[Chunk]:
        normalized = self._normalize(record.raw_data)
        return self._chunk(normalized)

    @staticmethod
    def _normalize(issue: dict) -> dict:
        fields = issue["fields"]
        return {
            "external_id": issue["key"],
            "title":       fields.get("summary", ""),
            "description": JiraTransformer._adf_to_text(fields.get("description")),
            "status":      fields.get("status", {}).get("name", ""),
            "priority":    (fields.get("priority") or {}).get("name", ""),
            "assignee":    (fields.get("assignee") or {}).get("displayName", ""),
            "reporter":    (fields.get("reporter") or {}).get("displayName", ""),
            "issue_type":  fields.get("issuetype", {}).get("name", ""),
            "created_at":  fields.get("created"),
            "updated_at":  fields.get("updated"),
            "comments":    JiraTransformer._extract_comments(
                fields.get("comment", {}).get("comments", [])
            ),
        }

    @staticmethod
    def _chunk(normalized: dict) -> list[Chunk]:
        chunks      = []
        external_id = normalized["external_id"]

        metadata = {
            "status":     normalized["status"],
            "priority":   normalized["priority"],
            "assignee":   normalized["assignee"],
            "issue_type": normalized["issue_type"],
            "created_at": normalized["created_at"],
            "updated_at": normalized["updated_at"],
        }

        # Chunk principal — statut et assigné inclus dans le texte
        main_content = (
            f"[{external_id}] {normalized['title']}\n"
            f"Statut: {normalized['status']}\n"
            f"Priorité: {normalized['priority']}\n"
            f"Assigné à: {normalized['assignee'] or 'Non assigné'}\n"
            f"Type: {normalized['issue_type']}\n\n"
            f"{normalized['description']}"
        )

        for i, text in enumerate(JiraTransformer._split_text(main_content)):
            chunks.append(Chunk(
                chunk_id    = f"jira-{external_id}-{i}",
                document_id = external_id,
                source_type = "jira",
                content     = text,
                metadata    = {**metadata, "chunk_type": "body"},
            ))

        # Un chunk par commentaire
        for j, comment in enumerate(normalized["comments"]):
            text = (
                f"[{external_id}] Commentaire de {comment['author']}:\n"
                f"{comment['body']}"
            )
            chunks.append(Chunk(
                chunk_id    = f"jira-{external_id}-c{j}",
                document_id = external_id,
                source_type = "jira",
                content     = text[:MAX_CHUNK_CHARS],
                metadata    = {
                    **metadata,
                    "chunk_type":     "comment",
                    "comment_author": comment["author"],
                },
            ))

        return chunks

    @staticmethod
    def _split_text(
        text: str,
        max_chars: int = MAX_CHUNK_CHARS,
        overlap: int   = OVERLAP_CHARS,
    ) -> list[str]:
        """
        Recursive Character Text Splitting avec overlap.
        Ordre de priorité de coupure :
        1. paragraphes (\n\n)
        2. lignes (\n)
        3. phrases (. )
        4. mots (espace)
        Jamais de coupure en milieu de mot.
        """
        if len(text) <= max_chars:
            return [text]

        separators = ["\n\n", "\n", ". ", " "]

        def _recursive_split(t: str, seps: list[str]) -> list[str]:
            if len(t) <= max_chars:
                return [t]

            sep   = seps[0] if seps else " "
            parts = t.split(sep)

            current = ""
            result  = []

            for part in parts:
                candidate = current + sep + part if current else part

                if len(candidate) <= max_chars:
                    current = candidate
                else:
                    if current:
                        result.append(current)
                    if len(part) > max_chars and len(seps) > 1:
                        result.extend(_recursive_split(part, seps[1:]))
                        current = ""
                    else:
                        current = part

            if current:
                result.append(current)

            return result

        raw_chunks = _recursive_split(text, separators)

        # Ajouter l overlap entre chunks
        if overlap <= 0 or len(raw_chunks) <= 1:
            return raw_chunks

        overlapped = [raw_chunks[0]]
        for i in range(1, len(raw_chunks)):
            prev         = raw_chunks[i - 1]
            current      = raw_chunks[i]
            overlap_text = prev[-overlap:] if len(prev) > overlap else prev
            overlapped.append(overlap_text + " " + current)

        return overlapped

    @staticmethod
    def _extract_comments(comments: list) -> list[dict]:
        return [
            {
                "author":  (c.get("author") or {}).get("displayName", ""),
                "body":    JiraTransformer._adf_to_text(c.get("body")),
                "created": c.get("created"),
            }
            for c in comments
        ]

    @staticmethod
    def _adf_to_text(adf: Optional[Any]) -> str:
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