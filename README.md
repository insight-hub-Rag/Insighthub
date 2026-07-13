# InsightHub

Assistant IA d'entreprise capable de répondre en langage naturel à des questions portant sur plusieurs sources internes hétérogènes : outils de gestion de projet et de documentation (Jira, Confluence, SharePoint) et données métier structurées (bases SQL).

## Sommaire

- [Vue d'ensemble](#vue-densemble)
- [Architecture du pipeline RAG](#architecture-du-pipeline-rag)
- [Ingestion des données](#ingestion-des-données)
- [Recherche et fusion](#recherche-et-fusion)
- [Génération de la réponse](#génération-de-la-réponse)
- [Extension aux données structurées (NL2SQL)](#extension-aux-données-structurées-nl2sql)
- [Stack technique](#stack-technique)
- [Structure du projet](#structure-du-projet)
- [Installation](#installation)
- [Configuration](#configuration)
- [Lancement](#lancement)
- [Principes de conception](#principes-de-conception)
- [Limitations connues](#limitations-connues)

## Vue d'ensemble

InsightHub ingère en continu le contenu de plusieurs sources d'entreprise, le rend interrogeable via une combinaison de recherche vectorielle et textuelle, puis répond aux questions des utilisateurs en s'appuyant uniquement sur ce contenu — jamais sur les connaissances générales du modèle de langage.

Le projet repose sur une architecture volontairement modulaire : chaque source (documentaire ou structurée) est intégrée derrière un contrat commun, ce qui permet d'ajouter une nouvelle source sans modifier le cœur du pipeline.

## Architecture du pipeline RAG

```
Utilisateur / Client
        │
        ▼
    API /search
        │
        ▼
 Orchestrator (Pipeline Master)
        │
        ▼
 Query Preprocessor
 (nettoyage & reformulation)
        │
        ▼
    Rule Router
  (décision rapide)
      /        \
Décision simple   LLM Router
(règle explicite) (classification sémantique
      \             si nécessaire)
        \         /
         ▼       ▼
     Agent Manager
   (dispatch vers les agents)
    /       |       |       \
 Jira   ServiceNow  Confluence  SharePoint
  │         │           │           │
Metadata  Vector      BM25       Recherche
filtres   Search      recherche  propriétaire
          embeddings  textuelle
    \       |           |          /
     \      |           |         /
        RRF Interne (Top K par source)
                │
                ▼
        Global Fusion (RRF global consolidé)
                │
                ▼
        Cross-Encoder (re-ranking fin)
                │
                ▼
        Context Builder (contexte final)
                │
                ▼
        Prompt Builder (template + documents)
                │
                ▼
        Generator (LLM)
                │
                ▼
        Réponse + Sources
```

Chaque étape est isolée et remplaçable indépendamment des autres (principe Open/Closed) : le routage, la recherche par agent, la fusion et la génération ne dépendent que de contrats abstraits (`app/rag/interfaces.py`), jamais des implémentations concrètes.

## Ingestion des données

Avant d'être interrogeable, chaque source suit un pipeline d'ingestion en amont (`app/ingestion/`, `app/connectors/`) :

1. **Connecteurs** (`app/connectors/jira`, `confluence`, `sharepoint`) — récupèrent le contenu brut depuis l'API de chaque source (`client.py`), le transforment en un format commun (`transformer.py`), et orchestrent la synchronisation (`pipeline.py`).
2. **Chunking** — chaque document est découpé en fragments de taille adaptée avant vectorisation. Ce découpage évite de dépasser la limite d'entrée du modèle d'embedding et produit des vecteurs plus précis qu'un document entier traité comme un seul bloc.
3. **Embeddings** (`app/ingestion/embeddings/embedder.py`) — chaque fragment est transformé en vecteur numérique, stocké aux côtés du texte source dans PostgreSQL via l'extension `pgvector`.
4. **Stockage** — les fragments et leurs vecteurs sont persistés par schéma dédié (un schéma par source), avec les métadonnées nécessaires au filtrage (statut, priorité, date, identifiant externe...).

Ce pipeline d'ingestion est indépendant du pipeline de requête (query time) : il tourne en tâche de fond / batch, alimente la base, et n'est jamais appelé directement lors d'une question utilisateur.

## Recherche et fusion

Pour chaque source interrogée, un agent dédié combine plusieurs méthodes de recherche complémentaires, exécutées en parallèle :

- **Recherche vectorielle** (pgvector, similarité cosinus) — capte le sens et la proximité sémantique, même sans correspondance exacte de mots.
- **Recherche full-text** (PostgreSQL `tsvector` / `ts_rank`) — capte les correspondances exactes de mots-clés et de termes techniques.
- **Recherche par métadonnées** — capte les filtres structurés explicites (statut, priorité, identifiant).

Les résultats de ces méthodes sont combinés via **Reciprocal Rank Fusion (RRF)**, une technique de fusion de classements sans entraînement, robuste face à des scores non comparables entre méthodes. Cette fusion s'opère à deux niveaux :

1. **En interne à chaque agent** — fusionne les résultats des différentes méthodes de recherche pour une même source.
2. **Globalement** — fusionne les résultats déjà agrégés de toutes les sources interrogées.

Un modèle de **reranking cross-encoder** réévalue ensuite finement les meilleurs candidats issus de la fusion globale, en lisant la question et chaque extrait ensemble — plus précis qu'une simple comparaison vectorielle, appliqué uniquement sur un nombre restreint de candidats pour rester performant.

## Génération de la réponse

Les extraits retenus après reranking sont assemblés dans un budget de tokens contrôlé (`Context Builder`), puis insérés dans un prompt structuré (`Prompt Builder`) avec des consignes strictes :

- Répondre uniquement à partir du contexte fourni, sans compléter avec des connaissances générales.
- Citer systématiquement la source de chaque information.
- Indiquer explicitement l'absence de réponse si l'information n'est pas dans le contexte.

La génération finale est assurée par un LLM (Groq en développement, AWS Bedrock en production, avec repli automatique entre les deux).

## Extension aux données structurées (NL2SQL)

En complément des sources documentaires, un module dédié (`app/nl2sql/`) permet d'interroger en langage naturel des bases de données structurées (RH, projets, tickets...). Il génère une requête SQL à partir de la question, l'exécute en lecture seule, et reformule le résultat en langage naturel.

Ce module est isolé du reste du pipeline et s'y intègre comme une source parmi les autres, via le même contrat que les agents documentaires — il n'introduit aucune dépendance ni modification structurelle du pipeline RAG. Voir `app/nl2sql/` pour le détail (sécurité READ-ONLY à deux couches, cache de schéma, génération et validation des requêtes).

## Stack technique

| Composant | Technologie |
|---|---|
| API | FastAPI |
| Base de données | PostgreSQL + extension `pgvector` |
| Recherche vectorielle | pgvector (similarité cosinus) |
| Recherche full-text | PostgreSQL natif (`tsvector`, `ts_rank`) |
| Reranking | `sentence-transformers` (cross-encoder multilingue) |
| Génération / routage LLM | Groq (dev) et AWS Bedrock (prod) |
| ORM / migrations | SQLAlchemy, Alembic |
| Conteneurisation | Docker, docker-compose |

## Structure du projet

```
app/
├── api/            # Endpoints FastAPI
├── connectors/     # Connecteurs source (client + pipeline + transformer par source)
│   ├── confluence/
│   ├── jira/
│   └── sharepoint/
├── core/           # Contrats et modèles partagés à l'ingestion
├── db/             # Accès base InsightHub, vector store
├── ingestion/       # Pipeline d'ingestion + embeddings
├── nl2sql/          # Module d'interrogation NL2SQL (isolé)
└── rag/            # Pipeline RAG documentaire
    ├── agents/       # Un agent par source (hérite de BaseAgent)
    ├── fusion/       # Reciprocal Rank Fusion (interne + globale)
    ├── generator/    # Construction du contexte, du prompt, appel LLM
    ├── preprocessing/# Nettoyage et détection de langue
    ├── reranker/     # Cross-encoder
    ├── retrievers/   # Vector / BM25 / SQL retrievers
    ├── routing/      # Rule Router + LLM Router
    ├── interfaces.py # Contrats Protocol du pipeline
    └── orchestrator.py
postgres/           # Scripts d'initialisation SQL
alembic/            # Migrations de schéma
tests/
```

## Installation

```bash
git clone <url-du-repo>
cd Insighthub
pip install -r requirements.txt
```

## Configuration

Créer un fichier `.env` à la racine (voir `config.py` pour la liste complète des variables) :

```
# Base InsightHub
DATABASE_URL=postgresql://...

# LLM
GROQ_API_KEY=...
GROQ_MODEL=...
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=...
USE_BEDROCK=false
```

## Lancement

```bash
docker-compose up --build
```

Ou en local :

```bash
alembic upgrade head
uvicorn main:app --reload
```

## Principes de conception

- **Open/Closed** — ajouter une nouvelle source (documentaire ou structurée) ne nécessite qu'une nouvelle implémentation des contrats définis dans `interfaces.py`, sans modifier l'orchestrateur ni les autres agents.
- **Résilience par isolation des pannes** — chaque niveau du pipeline (retriever, agent, source) est protégé par timeout et gestion d'erreurs indépendante : la panne d'un composant ne fait jamais échouer l'ensemble de la réponse.
- **Traçabilité** — chaque résultat conserve ses scores intermédiaires (par méthode de recherche, après fusion, après reranking), utile pour le debug et l'explication des décisions du système.
- **Grounding strict** — le LLM de génération est contraint à ne répondre qu'à partir du contexte récupéré, avec citation systématique des sources.

## Limitations connues

- Le routeur par règles (`Rule Router`) reste sensible aux variantes lexicales et à la langue de la question.
- Le reranking cross-encoder, bien que plus précis, ajoute une latence supplémentaire — appliqué uniquement sur un nombre restreint de candidats pour limiter son impact.
- Le module NL2SQL présente des limitations propres, documentées séparément dans `app/nl2sql/`.