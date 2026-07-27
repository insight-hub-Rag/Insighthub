

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.models import RoutingDecision, RAGResponse, RetrievedChunk, AgentResult
from app.rag.orchestrator import Orchestrator


@pytest.fixture
def orchestrator():
    return Orchestrator()


@pytest.mark.asyncio
async def test_question_hors_scope_court_circuite_le_pipeline(orchestrator, monkeypatch):
    """Le point central du fix : si le routage dit in_scope=False,
    AUCUN agent ne doit être lancé — juste generate_out_of_scope()."""

    fake_out_of_scope_response = RAGResponse(
        question="combien pèse une baleine bleue ?",
        answer="Je suis un assistant dédié aux données d'entreprise.",
        sources=[],
        model="llama-3-8b",
        total_chunks_searched=0,
    )

    monkeypatch.setattr(
        orchestrator.rule_router, "route",
        lambda q: None,
    )
    monkeypatch.setattr(
        orchestrator.llm_router, "route",
        lambda q: RoutingDecision(
            sources=[], search_type="hybrid", filters={}, confidence=0.95,
            router_used="llm", reasoning="hors scope", in_scope=False,
        ),
    )
    monkeypatch.setattr(
        orchestrator.generator, "generate_out_of_scope",
        lambda question: fake_out_of_scope_response,
    )

    # Garde-fou : si l'orchestrateur appelle quand même les agents malgré
    # in_scope=False, ce mock lèvera une AssertionError explicite plutôt
    # que de silencieusement continuer.
    agent_manager_mock = AsyncMock(
        side_effect=AssertionError(
            "AgentManager.run() ne doit JAMAIS être appelé pour une "
            "question hors scope !"
        )
    )
    monkeypatch.setattr(orchestrator.agent_manager, "run", agent_manager_mock)

    response = await orchestrator.ask("combien pèse une baleine bleue ?")

    assert response.answer == fake_out_of_scope_response.answer
    assert response.sources == []
    agent_manager_mock.assert_not_called()


@pytest.mark.asyncio
async def test_question_in_scope_lance_bien_les_agents(orchestrator, monkeypatch):
    """Contre-test : vérifie qu'on n'a pas cassé le chemin normal en
    ajoutant le court-circuit — une question in_scope doit toujours
    déclencher AgentManager."""

    monkeypatch.setattr(
        orchestrator.rule_router, "route",
        lambda q: RoutingDecision(
            sources=["sql"], search_type="hybrid", filters={}, confidence=0.85,
            router_used="rule", reasoning="domaine métier", in_scope=True,
        ),
    )

    agent_manager_mock = AsyncMock(return_value=[])  # pas de résultats, on teste juste l'appel
    monkeypatch.setattr(orchestrator.agent_manager, "run", agent_manager_mock)

    response = await orchestrator.ask("quel est le salaire de Karim ?")

    agent_manager_mock.assert_awaited_once()
    # Pas de résultats -> réponse "je n'ai pas trouvé", comportement existant
    assert response.sources == []


@pytest.mark.asyncio
async def test_forced_sources_ecrase_le_choix_du_routeur(orchestrator, monkeypatch):
    """Chat scopé à une instance (écran Connecteurs) : forced_sources
    doit imposer la source, même si le routeur en a choisi une autre."""

    monkeypatch.setattr(
        orchestrator.rule_router, "route",
        lambda q: None,
    )
    monkeypatch.setattr(
        orchestrator.llm_router, "route",
        lambda q: RoutingDecision(
            sources=["confluence"], search_type="hybrid", filters={"priority": "High"},
            confidence=0.8, router_used="llm", reasoning="test", in_scope=True,
        ),
    )

    captured_routing = {}

    async def fake_agent_manager_run(query, routing):
        captured_routing["routing"] = routing
        return []

    monkeypatch.setattr(orchestrator.agent_manager, "run", fake_agent_manager_run)

    await orchestrator.ask("des tickets urgents ?", forced_sources=["jira"])

    assert captured_routing["routing"].sources == ["jira"]
    # Les filtres extraits par le LLM Router doivent être conservés
    assert captured_routing["routing"].filters == {"priority": "High"}


@pytest.mark.asyncio
async def test_sans_forced_sources_comportement_inchange(orchestrator, monkeypatch):
    """Non-régression : sans forced_sources (chat normal), le routeur
    garde la main sur le choix de la source, comme avant ce changement."""

    monkeypatch.setattr(
        orchestrator.rule_router, "route",
        lambda q: RoutingDecision(
            sources=["confluence"], search_type="hybrid", filters={},
            confidence=0.9, router_used="rule", reasoning="test", in_scope=True,
        ),
    )

    captured_routing = {}

    async def fake_agent_manager_run(query, routing):
        captured_routing["routing"] = routing
        return []

    monkeypatch.setattr(orchestrator.agent_manager, "run", fake_agent_manager_run)

    await orchestrator.ask("quoi de neuf sur Confluence ?")

    assert captured_routing["routing"].sources == ["confluence"]


@pytest.mark.asyncio
async def test_forced_instance_id_ajoute_le_filtre_connector_instance_id(orchestrator, monkeypatch):
    """Le chat scopé à une instance précise (pas juste un type de
    source) doit ajouter connector_instance_id aux filtres, sans écraser
    les autres filtres déjà extraits par le routeur (ex: priority)."""

    monkeypatch.setattr(
        orchestrator.rule_router, "route",
        lambda q: None,
    )
    monkeypatch.setattr(
        orchestrator.llm_router, "route",
        lambda q: RoutingDecision(
            sources=["jira"], search_type="hybrid", filters={"priority": ["Highest", "High"]},
            confidence=0.85, router_used="llm", reasoning="test", in_scope=True,
        ),
    )

    captured_routing = {}

    async def fake_agent_manager_run(query, routing):
        captured_routing["routing"] = routing
        return []

    monkeypatch.setattr(orchestrator.agent_manager, "run", fake_agent_manager_run)

    await orchestrator.ask(
        "tickets urgents ?",
        forced_sources=["jira"],
        forced_instance_id="abc-123",
    )

    assert captured_routing["routing"].filters["connector_instance_id"] == "abc-123"
    # Le filtre priority extrait par le LLM Router doit être conservé
    assert captured_routing["routing"].filters["priority"] == ["Highest", "High"]


@pytest.mark.asyncio
async def test_sans_forced_instance_id_comportement_inchange(orchestrator, monkeypatch):
    """Non-régression : sans forced_instance_id, aucun filtre
    connector_instance_id n'est ajouté."""

    monkeypatch.setattr(
        orchestrator.rule_router, "route",
        lambda q: RoutingDecision(
            sources=["jira"], search_type="hybrid", filters={},
            confidence=0.9, router_used="rule", reasoning="test", in_scope=True,
        ),
    )

    captured_routing = {}

    async def fake_agent_manager_run(query, routing):
        captured_routing["routing"] = routing
        return []

    monkeypatch.setattr(orchestrator.agent_manager, "run", fake_agent_manager_run)

    await orchestrator.ask("IH-2", forced_sources=["jira"])

    assert "connector_instance_id" not in captured_routing["routing"].filters


@pytest.mark.asyncio
async def test_forced_instance_id_seul_ne_declenche_pas_filters_were_requested(
    orchestrator, monkeypatch
):
    """Régression : connector_instance_id (scope technique, toujours
    présent en chat scopé) ne doit JAMAIS, à lui seul, déclencher
    filters_were_requested=True — sinon le Generator republie tous les
    chunks non cités explicitement, même sur une simple recherche
    sémantique ouverte sans vrai critère métier demandé."""

    monkeypatch.setattr(
        orchestrator.rule_router, "route",
        lambda q: None,
    )
    monkeypatch.setattr(
        orchestrator.llm_router, "route",
        lambda q: RoutingDecision(
            sources=["jira"], search_type="hybrid", filters={},
            confidence=0.85, router_used="llm", reasoning="test", in_scope=True,
        ),
    )

    chunk = RetrievedChunk(
        source_type="jira", document_id="IH-2", chunk_id="jira-IH-2-0",
        content="...", title="[IH-2] Test", vector_score=0.9,
    )

    async def fake_agent_manager_run(query, routing):
        return [AgentResult(source_type="jira", chunks=[chunk])]

    monkeypatch.setattr(orchestrator.agent_manager, "run", fake_agent_manager_run)
    monkeypatch.setattr(orchestrator.reranker, "rerank", lambda **kwargs: [chunk])

    captured_kwargs = {}

    def fake_generate(question, chunks, **kwargs):
        captured_kwargs.update(kwargs)
        return RAGResponse(
            question=question, answer="ok", sources=[], model="test",
            total_chunks_searched=len(chunks),
        )

    monkeypatch.setattr(orchestrator.generator, "generate", fake_generate)

    await orchestrator.ask(
        "des tickets ?",
        forced_sources=["jira"],
        forced_instance_id="abc-123",
    )

    assert captured_kwargs["filters_were_requested"] is False


@pytest.mark.asyncio
async def test_forced_instance_id_avec_vrai_filtre_declenche_filters_were_requested(
    orchestrator, monkeypatch
):
    """Contre-test : si un VRAI filtre métier (priority) est extrait EN
    PLUS de connector_instance_id, filters_were_requested doit rester
    True — on ne casse pas le cas qu'on avait corrigé à l'origine."""

    monkeypatch.setattr(
        orchestrator.rule_router, "route",
        lambda q: None,
    )
    monkeypatch.setattr(
        orchestrator.llm_router, "route",
        lambda q: RoutingDecision(
            sources=["jira"], search_type="hybrid", filters={"priority": ["Highest", "High"]},
            confidence=0.85, router_used="llm", reasoning="test", in_scope=True,
        ),
    )

    chunk = RetrievedChunk(
        source_type="jira", document_id="IH-2", chunk_id="jira-IH-2-0",
        content="...", title="[IH-2] Test", sql_score=1.0,
    )

    async def fake_agent_manager_run(query, routing):
        return [AgentResult(source_type="jira", chunks=[chunk])]

    monkeypatch.setattr(orchestrator.agent_manager, "run", fake_agent_manager_run)

    captured_kwargs = {}

    def fake_generate(question, chunks, **kwargs):
        captured_kwargs.update(kwargs)
        return RAGResponse(
            question=question, answer="ok", sources=[], model="test",
            total_chunks_searched=len(chunks),
        )

    monkeypatch.setattr(orchestrator.generator, "generate", fake_generate)

    await orchestrator.ask(
        "tickets urgents ?",
        forced_sources=["jira"],
        forced_instance_id="abc-123",
    )

    assert captured_kwargs["filters_were_requested"] is True