from dataclasses import dataclass, field
from typing import Any, Optional


# ==================================================================
# Schéma de la base cible — produit par schema_scanner.py
# ==================================================================

@dataclass
class ColumnInfo:
    name: str
    data_type: str
    nullable: bool = True
    is_primary_key: bool = False
    default: Optional[str] = None


@dataclass
class ForeignKeyInfo:
    column: str
    references_table: str
    references_column: str


@dataclass
class TableInfo:
    name: str
    schema: str = "public"
    columns: list[ColumnInfo] = field(default_factory=list)
    foreign_keys: list[ForeignKeyInfo] = field(default_factory=list)


@dataclass
class SchemaScanResult:
    """
    Résultat complet d'un scan de schéma pour UNE connexion cible.
    C'est ce que schema_scanner.py produit, que schema_store.py persiste,
    et que schema_cache.py sert en lecture rapide.
    """
    connection_id: str
    engine_dialect: str          # "postgresql" | "mysql" | "oracle"...
    tables: list[TableInfo] = field(default_factory=list)
    scanned_at: Optional[str] = None   # ISO format, rempli à la persistance


# ==================================================================
# Configuration d'une connexion cible — anticipe le multi-connexion
# ==================================================================

@dataclass
class NL2SQLConfig:
    """
    Configuration d'une connexion à une base cible à scanner.
    Aujourd'hui : une seule instance construite depuis settings (.env).
    Demain : plusieurs instances, une par client, chargées depuis une
    table de config plutôt que l'environnement — cette dataclass ne
    change pas, seule sa source de construction change.
    """
    connection_id: str            # identifiant stable, ex: "default" ou "client_x"
    database_url: str
    latency_threshold_ms: float = 2000.0   # au-delà : déclenche query_optimizer
    schema_cache_ttl_seconds: int = 86400  # 24h — re-scan automatique périodique


# ==================================================================
# Résultat d'exécution d'une requête — alimente le dashboard monitoring
# ==================================================================

@dataclass
class QueryExecutionLog:
    """
    Une ligne du tableau "Recent generated queries" du dashboard.
    Persistée par query_logger.py après chaque question traitée.
    """
    connection_id: str
    natural_language_question: str
    generated_sql: str
    engine_dialect: str
    source_label: str = "SQL Database"   # affiché tel quel côté front
    status: str = "accepted"             # "accepted" | "optimized" | "rejected"
    exec_time_ms: Optional[float] = None
    suggested_improvement: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None     # ISO format, rempli à la persistance


# ==================================================================
# Résultat de validation — produit par query_validator.py
# ==================================================================

@dataclass
class ValidationResult:
    """
    Résultat de la validation READ-ONLY d'une requête SQL générée.
    Séparé en dataclass plutôt qu'un simple bool pour tracer la raison
    exacte du rejet (utile pour le log + la suggestion d'amélioration).
    """
    is_valid: bool
    reason: Optional[str] = None   # ex: "Instruction DELETE interdite"