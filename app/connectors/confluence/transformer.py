"""
Transformer Confluence : convertit un RawRecord (page Confluence brute au
format storage / XHTML) en une liste de Chunk prêts à être vectorisés.

Respecte le contrat BaseTransformer et produit le Chunk générique partagé
(app.core.models), exactement comme JiraTransformer. Aucun appel réseau ici.

Le contenu Confluence "storage" est du XHTML : on en extrait le texte brut
avec html.parser (bibliothèque standard) pour éviter toute dépendance
supplémentaire.
"""

from html.parser import HTMLParser

from app.core.base_transformer import BaseTransformer
from app.core.models import Chunk, RawRecord

MAX_CHUNK_CHARS = 2000  # ~512 tokens approximatifs (aligné sur Jira)


class _HTMLTextExtractor(HTMLParser):
    """Extrait le texte brut d'un contenu XHTML Confluence, sans dépendance externe."""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        # Normalise les espaces multiples et les retours à la ligne.
        return " ".join(" ".join(self._parts).split())


class ConfluenceTransformer(BaseTransformer):

    def transform(self, record: RawRecord) -> list[Chunk]:
        normalized = self._normalize(record.raw_data)
        return self._chunk(normalized)

    # ── Normalisation ───────────────────────────────────────────────────

    @staticmethod
    def _normalize(page: dict) -> dict:
        """Extrait les champs utiles d'une page Confluence brute (API v2)."""
        body = ((page.get("body") or {}).get("storage") or {}).get("value", "")
        version = page.get("version") or {}
        return {
            "external_id": str(page["id"]),
            "title": page.get("title", ""),
            "space_id": str(page.get("spaceId", "")),
            "status": page.get("status", ""),
            "version": version.get("number"),
            "updated_at": version.get("createdAt"),
            "content": ConfluenceTransformer._html_to_text(body),
        }

    # ── Chunking ─────────────────────────────────────────────────────────

    @staticmethod
    def _chunk(normalized: dict) -> list[Chunk]:
        chunks: list[Chunk] = []
        external_id = normalized["external_id"]

        metadata = {
            "space_id": normalized["space_id"],
            "status": normalized["status"],
            "version": normalized["version"],
            "updated_at": normalized["updated_at"],
        }

        # Chunk principal : titre + corps de la page.
        # Le titre en première ligne permet à VectorStore._extract_title
        # de le retrouver (il lit la 1re ligne du chunk 'body').
        main_content = f"{normalized['title']}\n\n{normalized['content']}"
        for i, text in enumerate(ConfluenceTransformer._split_text(main_content)):
            chunks.append(Chunk(
                chunk_id=f"confluence-{external_id}-{i}",
                document_id=external_id,
                source_type="confluence",
                content=text,
                metadata={**metadata, "chunk_type": "body"},
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
    def _html_to_text(html: str) -> str:
        if not html:
            return ""
        parser = _HTMLTextExtractor()
        parser.feed(html)
        return parser.get_text()
