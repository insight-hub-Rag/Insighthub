from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Configuration centralisée de l'application.
    Toutes les valeurs viennent de l'environnement (.env en local, vraies
    variables d'env en prod/Docker). Rien ne doit être codé en dur ailleurs
    dans le projet.
    """

    # ── Base de données ────────────────────────────────────────────────
    database_url: str      = "postgresql+asyncpg://insighthub:changeme@localhost:5432/insighthub"
    database_url_sync: str = "postgresql://insighthub:changeme@localhost:5432/insighthub"

    # ── Jira ────────────────────────────────────────────────────────────
    jira_url: str          = ""
    jira_user: str         = ""
    jira_api_token: str    = ""
    jira_project_keys: str = ""
    jira_max_results: int  = 50

    # ── Admin des connecteurs (écran Connecteurs) ───────────────────────
    # Clé Fernet pour chiffrer les credentials stockés en base
    # (connector_configs.auth_encrypted) — jamais en clair. Générer une
    # vraie clé en prod avec : python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    connector_encryption_key: str = ""
    # Secret partagé optionnel entre la Lambda de sync planifiée et cet
    # endpoint (header X-Sync-Secret). Vide = pas de contrôle (dev) —
    # à définir en prod pour empêcher un déclenchement de sync non
    # autorisé par n'importe qui connaissant l'URL.
    lambda_sync_secret: str = ""
    # ARN de la Lambda sync_trigger déployée (infrastructure/lambda/).
    # Vide = EventBridge désactivé silencieusement (dev sans AWS réel) —
    # le CRUD des connecteurs continue de fonctionner normalement, juste
    # sans planification automatique.
    sync_lambda_arn: str = ""

    # ── Confluence ──────────────────────────────────────────────────────
    confluence_url: str          = ""
    confluence_user: str         = ""
    confluence_api_token: str    = ""
    confluence_space_keys: str   = ""
    confluence_max_results: int  = 50

    # ── SharePoint ──────────────────────────────────────────────────────
    sharepoint_tenant_id:     str = ""
    sharepoint_client_id:     str = ""
    sharepoint_client_secret: str = ""
    sharepoint_site_url:      str = ""
    sharepoint_list_title:    str = ""
    sharepoint_username:      str = ""
    sharepoint_password:      str = ""

    # ── ServiceNow ──────────────────────────────────────────────────────
    servicenow_instance_url: str = ""
    servicenow_username:     str = ""
    servicenow_password:     str = ""
    servicenow_table:        str = "incident"
    servicenow_page_size:    int = 100

    # ── Embedding ───────────────────────────────────────────────────────
    embedding_provider:  str = "local"
    embedding_model:     str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 1024

    # ── AWS Bedrock ─────────────────────────────────────────────────────
    aws_access_key_id:     str  = ""
    aws_secret_access_key: str  = ""
    aws_region:            str  = "us-east-1"
    bedrock_embedding_model: str = "amazon.titan-embed-text-v2:0"
    use_bedrock:           bool = False

    # ── RAG / LLM ───────────────────────────────────────────────────────
    groq_api_key:       str   = ""
    groq_model:         str   = "llama-3.3-70b-versatile"
    rag_top_k:          int   = 5
    rag_min_similarity: float = 0.3

    # ── NL2SQL ──────────────────────────────────────────────────────────
    nl2sql_target_db_url: str          = ""
    nl2sql_latency_threshold_ms: float = 2000.0
    nl2sql_schema_ttl_seconds: int     = 86400
    bedrock_text_model: str            = "amazon.nova-pro-v1:0"

    # ── Properties ──────────────────────────────────────────────────────
    @property
    def jira_projects(self) -> list[str]:
        return [p.strip() for p in self.jira_project_keys.split(",") if p.strip()]

    @property
    def confluence_spaces(self) -> list[str]:
        return [s.strip() for s in self.confluence_space_keys.split(",") if s.strip()]

    @property
    def servicenow_configured(self) -> bool:
        return bool(
            self.servicenow_instance_url
            and self.servicenow_username
            and self.servicenow_password
        )

    class Config:
        env_file = str(Path(__file__).resolve().parent / ".env")
        extra    = "ignore"


settings = Settings()