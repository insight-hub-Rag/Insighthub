"""
Script de diagnostic — appelle directement RuleRouter puis LLMRouter
pour UNE question, sans passer par l'API ni l'orchestrateur, afin de
voir exactement ce que chaque routeur décide isolément.

Usage : docker compose exec backend python scripts/debug_routing.py
"""

import sys
sys.path.insert(0, ".")

from app.rag.routing.rule_router import RuleRouter
from app.rag.routing.llm_router import LLMRouter
from app.core.models import PreprocessedQuery

question = "tickets non résolus dans jira ?"
query = PreprocessedQuery(original_text=question, cleaned_text=question)

print("=" * 80)
print(f"Question : {question!r}")
print("=" * 80)

rule_router = RuleRouter()
rule_decision = rule_router.route(query)
print(f"\n--- RuleRouter ---")
print(f"Résultat : {rule_decision}")

print(f"\n--- LLMRouter (vrai appel Bedrock) ---")
llm_router = LLMRouter()
llm_decision = llm_router.route(query)
print(f"sources    : {llm_decision.sources}")
print(f"filters    : {llm_decision.filters}")
print(f"confidence : {llm_decision.confidence}")
print(f"router_used: {llm_decision.router_used}")
print(f"reasoning  : {llm_decision.reasoning}")
print(f"in_scope   : {llm_decision.in_scope}")