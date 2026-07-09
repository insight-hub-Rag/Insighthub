"""
Construction du prompt envoyé au LLM de génération.
Reçoit des RetrievedChunk (déjà filtrés par le Context Builder).
"""

from app.core.models import RetrievedChunk

SYSTEM_PROMPT = """Tu es InsightHub, un assistant interne d'entreprise.

Règles strictes :
- Réponds UNIQUEMENT à partir du contexte fourni
- Sois CONCIS : maximum 3-4 phrases
- Si la réponse n'est pas dans le contexte, dis : "Je n'ai pas trouvé d'information sur ce sujet dans les données disponibles."
- Cite toujours la source (ex: Jira IH-1, Confluence ...)
- Réponds en français
- Ne spécule pas, ne complète pas avec tes connaissances générales"""


def build_prompt(question: str, chunks: list[RetrievedChunk]) -> list[dict]:
    context = _build_context(chunks)

    user_message = f"""Contexte disponible :
{context}

Question : {question}

Réponds de façon courte et précise en citant la source."""

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


def _build_context(chunks: list[RetrievedChunk]) -> str:
    if not chunks:
        return "Aucun contexte disponible."

    parts = []
    for i, chunk in enumerate(chunks, 1):
        source_label = _source_label(chunk.source_type, chunk.document_id)
        parts.append(f"[{i}] {source_label}\n{chunk.content[:500]}")

    return "\n\n".join(parts)


def _source_label(source_type: str, document_id: str) -> str:
    labels = {
        "jira": f"Jira {document_id}",
        "confluence": f"Confluence {document_id}",
        "sharepoint": f"SharePoint {document_id}",
    }
    return labels.get(source_type, f"{source_type} {document_id}")