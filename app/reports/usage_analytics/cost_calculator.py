"""
app/reports/usage_analytics/cost_calculator.py

Calcul pur du coût en $ d'un appel LLM à partir de son nombre de
tokens. Aucune dépendance DB/HTTP — uniquement une table de tarifs et
une fonction de conversion (SRP strict : ce fichier ne fait QUE ça).

Tarifs vérifiés le 08/09/2026 (pages de pricing officielles AWS
Bedrock et Groq) — à mettre à jour si les tarifs changent ou si un
nouveau modèle est introduit dans app/rag/generator/generator.py.

Modèles absents de la table (ex: "sql-passthrough", "none", "error",
retournés par Generator dans certains cas de bypass/échec) coûtent
0$ — cohérent, puisqu'aucun appel LLM n'a réellement eu lieu.
"""

# Prix en $ par MILLION de tokens : {model_id: (prix_input, prix_output)}
_PRICING_PER_MILLION_TOKENS: dict[str, tuple[float, float]] = {
    "bedrock-nova-micro":         (0.035, 0.14),
    "llama-3.3-70b-versatile":    (0.59, 0.79),
    "amazon.nova-pro-v1:0":       (0.80, 3.20),  # utilisé par NL2SQL (query_generator.py)
}


class CostCalculator:

    @staticmethod
    def compute_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
        pricing = _PRICING_PER_MILLION_TOKENS.get(model)
        if pricing is None:
            return 0.0

        input_price_per_million, output_price_per_million = pricing
        cost = (
            (input_tokens / 1_000_000) * input_price_per_million
            + (output_tokens / 1_000_000) * output_price_per_million
        )
        return round(cost, 8)