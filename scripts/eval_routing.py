"""
Script d'évaluation du ROUTAGE — pas un test pytest, un script à lancer
à la main pour mesurer la qualité réelle du Rule Router + LLM Router
sur un jeu de questions diverses, avec de VRAIS appels à ton backend
(Bedrock si USE_BEDROCK=true dans le .env, sinon Groq).

Usage :
    python scripts/eval_routing.py

Pour chaque question : montre quel router a tranché (rule/llm), les
sources choisies, in_scope, la confiance, et le raisonnement donné par
le LLM. Compare à une attente ("expected") quand elle est raisonnable à
fixer à l'avance, et calcule un score de précision global.

Certains cas (colonne "expected" = None) sont volontairement laissés
sans attente stricte — la bonne réponse dépend du jugement du LLM sur
une formulation ambiguë, à toi de lire le "reasoning" et juger à l'oeil.
"""

import sys
from dataclasses import dataclass

sys.path.insert(0, ".")

from app.core.models import PreprocessedQuery
from app.rag.routing.rule_router import RuleRouter
from app.rag.routing.llm_router import LLMRouter


@dataclass
class TestCase:
    category: str
    question: str
    expected_in_scope: bool | None = None   # None = pas d'attente stricte
    expected_sources: list[str] | None = None  # None = pas d'attente stricte


TEST_CASES: list[TestCase] = [

    # --- 1. Identifiant explicite (doit être tranché par le Rule Router) ---
    TestCase("ID Jira", "IH-2", True, ["jira"]),
    TestCase("ID Jira", "peux-tu me montrer INFRA-45 ?", True, ["jira"]),
    TestCase("ID Jira", "le ticket SUPPORT-102 est bloqué depuis 3 jours", True, ["jira"]),

    # --- 2. Salutations / politesse pure (hors scope, sans appel LLM idéalement) ---
    TestCase("Salutation", "bonjour", False, []),
    TestCase("Salutation", "merci beaucoup !", False, []),
    TestCase("Salutation", "au revoir", False, []),

    # --- 3. Nom de source cité explicitement ---
    TestCase("Source explicite", "montre-moi les tickets urgents dans Jira", True, ["jira"]),
    TestCase("Source explicite", "quoi de neuf sur Confluence ?", True, ["confluence"]),
    TestCase("Source explicite", "cherche ce document sur SharePoint", True, ["sharepoint"]),

    # --- 4. Domaine métier fort (RH / business) ---
    TestCase("Domaine métier", "quel est le salaire de Karim ?", True, ["sql"]),
    TestCase("Domaine métier", "combien d'employés dans l'équipe DEV ?", True, ["sql"]),
    TestCase("Domaine métier", "combien y a-t-il de congés en attente ?", True, ["sql"]),

    # --- 5. Ambiguïté ticket/jira/sql — LE cas central de ce projet ---
    TestCase("Ambiguïté ticket", "combien de tickets non résolus a le projet InsightHub ?", True, ["sql"]),
    TestCase("Ambiguïté ticket", "montre-moi les tickets urgents et leur description", True, ["jira"]),
    TestCase("Ambiguïté ticket", "répartition des tickets par priorité", True, ["sql"]),
    TestCase("Ambiguïté ticket", "quel est le contenu du ticket IH-9 ?", True, ["jira"]),

    # --- 6. Opérateur générique isolé, hors scope malgré le mot-clé ---
    TestCase("Piège opérateur générique", "combien pèse une baleine bleue ?", False, []),
    TestCase("Piège opérateur générique", "quel est le total de la population mondiale ?", False, []),
    TestCase("Piège opérateur générique", "quelle est la moyenne d'âge des joueurs de la NBA ?", False, []),

    # --- 7. Hors scope, culture générale, sans aucun mot-clé piège ---
    TestCase("Hors scope pur", "explique-moi la théorie de la relativité", False, []),
    TestCase("Hors scope pur", "donne-moi une recette de tajine", False, []),
    TestCase("Hors scope pur", "qui a gagné la coupe du monde 2022 ?", False, []),
    TestCase("Hors scope pur", "raconte-moi une blague", False, []),

    # --- 8. Multi-source légitime (pas une collision, un vrai besoin double) ---
    TestCase("Multi-source légitime", "compare le nombre de tickets ouverts avec la documentation sur notre process de sprint", True, None),
    TestCase("Multi-source légitime", "les congés RH sont-ils bien documentés sur Confluence ?", True, None),

    # --- 9. Cas limites / robustesse ---
    TestCase("Edge case", "", None, None),
    TestCase("Edge case", "?", None, None),
    TestCase("Edge case", "azkjdhqsdjkh qsdkjh", None, None),
    TestCase("Edge case (anglais)", "how many open tickets does the DEV project have?", True, ["sql"]),

    # --- 10. Questions métier reformulées naturellement, sans mot-clé net ---
    TestCase("Reformulation naturelle", "est-ce que Karim a encore des jours de congé cette année ?", True, ["sql"]),
    TestCase("Reformulation naturelle", "j'aimerais comprendre pourquoi le ticket IH-9 traîne autant", True, ["jira"]),
    TestCase("Reformulation naturelle", "on a combien de monde dans l'équipe support ?", True, ["sql"]),
]


def evaluate() -> None:
    rule_router = RuleRouter()
    llm_router = LLMRouter()

    total_with_expectation = 0
    correct = 0

    print(f"{'Catégorie':<28} {'Question':<65} {'Router':<6} {'in_scope':<9} {'Sources':<20} {'OK?':<5}")
    print("-" * 145)

    for case in TEST_CASES:
        query = PreprocessedQuery(original_text=case.question, cleaned_text=case.question)

        decision = rule_router.route(query)
        if decision is None:
            decision = llm_router.route(query)

        ok_marker = "-"
        if case.expected_in_scope is not None:
            total_with_expectation += 1
            in_scope_ok = decision.in_scope == case.expected_in_scope
            sources_ok = (
                case.expected_sources is None
                or set(decision.sources) == set(case.expected_sources)
            )
            is_correct = in_scope_ok and sources_ok
            correct += int(is_correct)
            ok_marker = "✅" if is_correct else "❌"

        print(
            f"{case.category:<28} {case.question[:63]:<65} "
            f"{decision.router_used:<6} {str(decision.in_scope):<9} "
            f"{str(decision.sources):<20} {ok_marker:<5}"
        )
        if decision.router_used == "llm":
            print(f"{'':<28} └─ raisonnement LLM : {decision.reasoning}")

    print("-" * 145)
    if total_with_expectation:
        pct = 100 * correct / total_with_expectation
        print(f"\nScore : {correct}/{total_with_expectation} ({pct:.0f}%) sur les cas avec attente définie.")
    print(
        f"{len(TEST_CASES) - total_with_expectation} cas sans attente stricte "
        "(edge cases / multi-source légitime) — à relire manuellement dans le 'reasoning' ci-dessus."
    )


if __name__ == "__main__":
    evaluate()