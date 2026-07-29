from app.rag.conversation.question_condenser import (
    MAX_HISTORY_CHARS,
    MAX_HISTORY_MESSAGES,
    QuestionCondenser,
)
from config import settings


def test_sans_historique_ne_declenche_pas_le_llm(monkeypatch):
    condenser = QuestionCondenser()
    monkeypatch.setattr(
        condenser,
        "_condense_groq",
        lambda prompt: (_ for _ in ()).throw(AssertionError("appel inattendu")),
    )

    assert condenser.condense("Quelle est la priorité de IH-1 ?", []) == (
        "Quelle est la priorité de IH-1 ?"
    )


def test_question_de_suivi_est_reformulee(monkeypatch):
    condenser = QuestionCondenser()
    monkeypatch.setattr(settings, "use_bedrock", False)
    monkeypatch.setattr(
        condenser,
        "_condense_groq",
        lambda prompt: "Quelle est la priorité du ticket IH-1 ?",
    )

    result = condenser.condense(
        "et sa priorité ?",
        [
            {"role": "user", "content": "IH-1"},
            {"role": "assistant", "content": "Le ticket IH-1 concerne un timeout."},
        ],
    )

    assert result == "Quelle est la priorité du ticket IH-1 ?"


def test_echec_du_llm_conserve_la_question_originale(monkeypatch):
    condenser = QuestionCondenser()
    monkeypatch.setattr(settings, "use_bedrock", False)
    monkeypatch.setattr(
        condenser,
        "_condense_groq",
        lambda prompt: (_ for _ in ()).throw(RuntimeError("indisponible")),
    )

    assert condenser.condense(
        "et sa priorité ?",
        [{"role": "user", "content": "IH-1"}],
    ) == "et sa priorité ?"


def test_historique_est_limite_en_messages_et_caracteres():
    history = [
        {"role": "user", "content": str(index) * 1000}
        for index in range(10)
    ]

    prepared = QuestionCondenser._prepare_history(history)

    assert len(prepared) <= MAX_HISTORY_MESSAGES
    assert sum(len(item["content"]) for item in prepared) <= MAX_HISTORY_CHARS
    assert prepared[-1]["content"].startswith("9")
