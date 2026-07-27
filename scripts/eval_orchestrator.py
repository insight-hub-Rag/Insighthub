
import argparse
import asyncio
import sys
import time

sys.path.insert(0, ".")

from app.rag.orchestrator import Orchestrator

# Sous-ensemble volontairement plus restreint que eval_routing.py — on
# privilégie ici des questions dont TU connais la vraie réponse dans tes
# données de test (adapte ces questions à ce que tu as réellement
# synchronisé/seedé, sinon les réponses "je n'ai pas trouvé" sont
# normales et n'indiquent pas un bug de l'orchestrateur).
QUESTIONS = [
    "IH-2",
    "montre-moi les tickets urgents dans Jira",
    "combien de tickets non résolus a le projet InsightHub ?",
    "quel est le salaire de Karim Idrissi ?",
    "combien d'employés dans l'équipe DEV ?",
    "quoi de neuf sur Confluence à propos du process de sprint ?",
    "bonjour",
    "explique-moi la théorie de la relativité",
    "combien pèse une baleine bleue ?",
]


async def evaluate(limit: int | None = None) -> None:
    orchestrator = Orchestrator()
    questions = QUESTIONS[:limit] if limit else QUESTIONS

    for i, question in enumerate(questions, 1):
        print(f"\n{'=' * 100}")
        print(f"[{i}/{len(questions)}] Question : {question!r}")
        print("=" * 100)

        t0 = time.time()
        try:
            response = await orchestrator.ask(question)
        except Exception as e:
            print(f"❌ ERREUR pendant le pipeline : {e}")
            continue
        latency_ms = round((time.time() - t0) * 1000, 1)

        print(f"Réponse      : {response.answer}")
        print(f"Sources      : {response.sources}")
        print(f"Modèle       : {response.model}")
        print(f"Chunks vus   : {response.total_chunks_searched}")
        print(f"Latence      : {latency_ms} ms")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Ne tester que les N premières questions")
    args = parser.parse_args()

    asyncio.run(evaluate(limit=args.limit))