import re
from typing import Optional

from app.core.base_transformer import BaseTransformer
from app.core.models import Chunk, RawRecord

MAX_CHUNK_CHARS = 1500
OVERLAP_CHARS   = 150

# Une entrée de champ "journal" (comments / work_notes) ressemble à :
# "2024-01-15 09:23:11 - Jean Dupont (Work notes)\nTexte du commentaire"
_JOURNAL_ENTRY_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - "
    r"(?P<author>.+?) \((?P<kind>.+?)\)$"
)


class ServiceNowTransformer(BaseTransformer):

    def transform(self, record: RawRecord) -> list[Chunk]:
        normalized = self._normalize(record.raw_data)
        return self._chunk(normalized)

    @staticmethod
    def _normalize(item: dict) -> dict:
        return {
            "external_id": item.get("number", ""),
            "title":       item.get("short_description", ""),
            "description": item.get("description", "") or "",
            "state":       item.get("state", ""),
            "priority":    item.get("priority", ""),
            "category":    item.get("category", ""),
            "assigned_to": item.get("assigned_to", "") or "",
            "opened_by":   item.get("opened_by", "") or "",
            "created_at":  item.get("sys_created_on"),
            "updated_at":  item.get("sys_updated_on"),
            "resolved_at": item.get("closed_at") or "",
            "notes": (
                ServiceNowTransformer._parse_journal(item.get("comments", ""))
                + ServiceNowTransformer._parse_journal(item.get("work_notes", ""))
            ),
        }

    @staticmethod
    def _chunk(normalized: dict) -> list[Chunk]:
        chunks      = []
        external_id = normalized["external_id"]

        metadata = {
            "state":       normalized["state"],
            "priority":    normalized["priority"],
            "category":    normalized["category"],
            "assigned_to": normalized["assigned_to"],
            "created_at":  normalized["created_at"],
            "updated_at":  normalized["updated_at"],
            "resolved_at": normalized["resolved_at"],
        }

        main_content = (
            f"[{external_id}] {normalized['title']}\n"
            f"État: {normalized['state']}\n"
            f"Priorité: {normalized['priority']}\n"
            f"Catégorie: {normalized['category'] or 'Non catégorisé'}\n"
            f"Assigné à: {normalized['assigned_to'] or 'Non assigné'}\n"
            f"Ouvert par: {normalized['opened_by'] or 'Inconnu'}\n\n"
            f"{normalized['description']}"
        )

        for i, text in enumerate(ServiceNowTransformer._split_text(main_content)):
            chunks.append(Chunk(
                chunk_id    = f"servicenow-{external_id}-{i}",
                document_id = external_id,
                source_type = "servicenow",
                content     = text,
                metadata    = {**metadata, "chunk_type": "body"},
            ))

        for j, note in enumerate(normalized["notes"]):
            text = (
                f"[{external_id}] {note['kind']} de {note['author']} "
                f"({note['date']}):\n{note['body']}"
            )
            chunks.append(Chunk(
                chunk_id    = f"servicenow-{external_id}-n{j}",
                document_id = external_id,
                source_type = "servicenow",
                content     = text[:MAX_CHUNK_CHARS],
                metadata    = {
                    **metadata,
                    "chunk_type":  "comment",
                    "note_author": note["author"],
                    "note_kind":   note["kind"],
                },
            ))

        return chunks

    @staticmethod
    def _split_text(
        text: str,
        max_chars: int = MAX_CHUNK_CHARS,
        overlap: int   = OVERLAP_CHARS,
    ) -> list[str]:
        """Recursive Character Text Splitting avec overlap (même logique que Jira)."""
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
    def _parse_journal(raw: Optional[str]) -> list[dict]:
        """Parse un champ journal ServiceNow (comments / work_notes)."""
        if not raw or not raw.strip():
            return []

        entries: list[dict] = []
        current_header: Optional[re.Match] = None
        current_body: list[str] = []

        def flush():
            if current_header is not None:
                entries.append({
                    "date":   current_header.group("date"),
                    "author": current_header.group("author"),
                    "kind":   current_header.group("kind"),
                    "body":   "\n".join(current_body).strip(),
                })

        for line in raw.splitlines():
            match = _JOURNAL_ENTRY_RE.match(line.strip())
            if match:
                flush()
                current_header = match
                current_body = []
            elif line.strip():
                current_body.append(line.strip())
        flush()

        return entries