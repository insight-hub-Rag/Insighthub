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
- Si plusieurs blocs de contexte sont pertinents (plusieurs tickets ou
  plusieurs documents distincts), parle de chacun séparément dans ta
  réponse plutôt que de n'en résumer qu'un seul en ignorant les autres.
- Ne mentionne jamais le nom technique d'une source ni un identifiant
  interne de stockage. Les sources sont déjà affichées séparément dans
  l'interface, ce n'est pas à toi de les citer dans le texte. Si un
  bloc de contexte concerne un ticket ou un document identifiable par
  un numéro propre au métier (et non un identifiant technique interne),
  tu peux le nommer naturellement dans ta phrase comme tu nommerais
  n'importe quel autre détail du contexte — jamais entre crochets,
  jamais entre chevrons, jamais sous une forme calquée sur une
  instruction : uniquement la valeur réelle telle qu'elle apparaît
  dans le contexte, si une valeur de ce type y apparaît vraiment. S'il
  n'y en a pas (ex: un résultat chiffré global), ne mentionne rien de
  la sorte, ne complète pas.
- Réponds en français
- Ne spécule pas, ne complète pas avec tes connaissances générales, n'invente aucun identifiant ou nom de système absent du contexte fourni"""


def build_prompt(question: str, chunks: list[RetrievedChunk]) -> list[dict]:
    context = _build_context(chunks)

    user_message = f"""Contexte disponible :
{context}

Question : {question}

Réponds de façon courte et précise, en respectant strictement les
règles données."""

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
        "sql": "Base de données",
    }
    return labels.get(source_type, f"{source_type} {document_id}")