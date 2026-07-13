"""
app/nl2sql/query_generator.py

Génère une requête SQL à partir d'une question en langage naturel et
du schéma scanné (via schema_cache.py).
Utilise AWS Bedrock,ici pour la génération de texte.

Le prompt système est volontairement agnostique du moteur SQL : le
dialecte (postgresql/mysql/oracle...) est injecté dynamiquement depuis
SchemaScanResult.engine_dialect, jamais codé en dur.

Ce module ne valide PAS la requête générée (responsabilité de
query_validator.py) et ne l'exécute pas (query_executor.py) — SRP
strict : uniquement la génération.
"""

import logging
import re

import boto3

from app.nl2sql.models import SchemaScanResult, TableInfo

logger = logging.getLogger(__name__)

_SQL_BLOCK_PATTERN = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


class QueryGenerator:

    def __init__(self, bedrock_model_id: str, aws_region: str):
        self._model_id = bedrock_model_id
        self._client = boto3.client("bedrock-runtime", region_name=aws_region)

    async def generate_sql(self, question: str, schema: SchemaScanResult) -> str:
        prompt = self._build_prompt(question, schema)

        response = self._client.converse(
            modelId=self._model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 500, "temperature": 0.0},
        )

        raw_output = response["output"]["message"]["content"][0]["text"]
        sql = self._extract_sql(raw_output)

        logger.info(f"[QueryGenerator] SQL généré pour question='{question[:80]}...' → {sql}")
        return sql

    def _build_prompt(self, question: str, schema: SchemaScanResult) -> str:
        schema_description = self._describe_schema(schema)

        return f"""Tu es un expert SQL. Génère UNE SEULE requête SQL en dialecte
{schema.engine_dialect} pour répondre à la question suivante, en te basant
UNIQUEMENT sur le schéma ci-dessous.

RÈGLES STRICTES :
- Uniquement une requête SELECT (ou WITH ... SELECT), jamais d'écriture.
- Une seule instruction, pas de point-virgule multiple.
- Utilise uniquement les tables et colonnes listées ci-dessous.
- Si la question ne peut pas être répondue avec ce schéma, retourne
  exactement : SELECT NULL WHERE FALSE
- Réponds UNIQUEMENT avec la requête SQL, sans explication, sans markdown.

SCHÉMA DISPONIBLE :
{schema_description}

QUESTION : {question}

REQUÊTE SQL :"""

    def _describe_schema(self, schema: SchemaScanResult) -> str:
        lines = []
        for table in schema.tables:
            lines.append(self._describe_table(table))
        return "\n".join(lines)

    @staticmethod
    def _describe_table(table: TableInfo) -> str:
        columns_desc = ", ".join(
            f"{col.name} ({col.data_type}"
            + (", PK" if col.is_primary_key else "")
            + ")"
            for col in table.columns
        )
        fk_desc = ""
        if table.foreign_keys:
            fk_lines = ", ".join(
                f"{fk.column} → {fk.references_table}.{fk.references_column}"
                for fk in table.foreign_keys
            )
            fk_desc = f" | Clés étrangères : {fk_lines}"

        return f"- Table {table.schema}.{table.name} : {columns_desc}{fk_desc}"

    @staticmethod
    def _extract_sql(raw_output: str) -> str:
        """Le LLM peut parfois entourer sa réponse de ```sql ... ```
        malgré la consigne — on extrait proprement dans ce cas, sinon
        on retourne le texte brut nettoyé."""
        match = _SQL_BLOCK_PATTERN.search(raw_output)
        sql = match.group(1) if match else raw_output
        return sql.strip()