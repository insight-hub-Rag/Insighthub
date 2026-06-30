from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Configuration centralisée de l'application.
    Toutes les valeurs viennent de l'environnement (.env en local, vraies
    variables d'env en prod/Docker). Rien ne doit être codé en dur ailleurs
    dans le projet.
    """

    # ── Base de données ────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://insighthub:changeme@localhost:5432/insighthub"

    # ── Jira ────────────────────────────────────────────────────────────
    jira_url: str = ""
    jira_user: str = ""
    jira_api_token: str = ""
    jira_project_keys: str = ""
    jira_max_results: int = 50

    # ── Embedding : stratégie active ────────────────────────────────────
    # "local"   → sentence-transformers, modèle téléchargé et exécuté en local
    # "bedrock" → AWS Bedrock (Titan Embed), nécessite des credentials AWS
    embedding_provider: str = "local"
    embedding_model: str = "all-MiniLM-L6-v2"   # utilisé si embedding_provider == "local"
    embedding_dimension: int = 384               # doit correspondre au modèle choisi

    # ── AWS Bedrock (optionnel, utilisé seulement si embedding_provider == "bedrock") ──
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"
    bedrock_embedding_model: str = "amazon.titan-embed-text-v2:0"

    @property
    def jira_projects(self) -> list[str]:
        """Liste des clés de projets Jira à synchroniser, parsée depuis le CSV."""
        return [p.strip() for p in self.jira_project_keys.split(",") if p.strip()]

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()