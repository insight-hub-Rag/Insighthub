"""
Construction du prompt envoyé au LLM de génération.
Reçoit des RetrievedChunk (déjà filtrés par le Context Builder).
"""

from app.core.models import RetrievedChunk

SYSTEM_PROMPT = """Tu es InsightHub, un assistant interne d'entreprise.

Règles strictes :
- Réponds UNIQUEMENT à partir du contexte fourni
- Sois CONCIS : maximum 3-4 phrases
- Le message "Je n'ai pas trouvé d'information sur ce sujet dans les
  données disponibles." ne doit être utilisé QUE si AUCUN bloc de
  contexte ci-dessous ne répond à la question. Si au moins un bloc
  [n] est pertinent, ne dis JAMAIS cette phrase — réponds avec ce que
  tu as, même si ce n'est qu'un seul élément parmi plusieurs.
- Si PLUSIEURS blocs de contexte sont pertinents (ex: plusieurs
  tickets, plusieurs documents), énumère-les TOUS dans ta réponse,
  sous forme de liste courte, chacun avec sa propre citation — ne
  choisis pas d'en résumer un seul en ignorant les autres.
- Cite toujours la source EXACTEMENT comme elle est écrite entre crochets au début du bloc de contexte correspondant (ex: "[1] Jira IH-4" -> cite "Jira IH-4"). N'invente et ne modifie JAMAIS ce libellé, ne le remplace par aucun autre système ou identifiant que tu connaîtrais par ailleurs.
- Réponds en français
- Ne spécule pas, ne complète pas avec tes connaissances générales, n'invente aucun identifiant ou nom de système absent du contexte fourni"""


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
        "sql": "Données internes (base RH/projets)",
    }
    return labels.get(source_type, f"{source_type} {document_id}")