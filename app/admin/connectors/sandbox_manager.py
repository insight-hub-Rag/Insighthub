"""
app/admin/connectors/sandbox_manager.py

Gestionnaire de sandbox pour la matérialisation temporaire des schémas SQL par tenant.
Crée, matérialise et détruit un schéma/base de données isolé pour scanner les métadonnées.
"""

import os
import re
import uuid
import logging
import sqlite3
import gc
from pathlib import Path
from typing import Generator, Optional
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from app.admin.connectors.dump_parser import DumpParser

logger = logging.getLogger(__name__)


class SandboxManagerError(Exception):
    pass


class SandboxManager:

    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            self.base_dir = Path(__file__).resolve().parent.parent.parent.parent / "sqlite_databases"
        else:
            self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.parser = DumpParser()

    @contextmanager
    def create_sandbox(
        self,
        engine_type: str,
        sql_content: str,
        tenant_id: str = "default",
    ) -> Generator[Engine, None, None]:
        """
        Matérialise le dump dans un environnement isolé temporaire,
        fournit un Engine SQLAlchemy synchrone pour le scan, puis détruit la sandbox.
        """
        engine_normalized = self.parser.normalize_engine(engine_type)
        statements = self.parser.parse_statements(sql_content, engine_normalized)
        
        sandbox_id = f"sb_{uuid.uuid4().hex[:8]}"

        if engine_normalized == "sqlite":
            yield from self._materialize_sqlite(sandbox_id, statements)
        elif engine_normalized in {"postgresql", "mysql", "mssql", "oracle"}:
            yield from self._materialize_sql_engine(engine_normalized, sandbox_id, statements)
        else:
            raise SandboxManagerError(f"Moteur non géré : {engine_normalized}")

    def _materialize_sqlite(
        self, sandbox_id: str, statements: list[str]
    ) -> Generator[Engine, None, None]:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        cursor = conn.cursor()
        for stmt in statements:
            try:
                cursor.execute(stmt)
            except Exception as exc:
                logger.warning(f"[SandboxManager] SQLite stmt failed: {exc} | STMT: {stmt[:60]}")
        conn.commit()

        engine = create_engine("sqlite://", creator=lambda: conn)
        logger.info(f"[SandboxManager] Sandbox SQLite in-memory créée ({sandbox_id})")
        
        try:
            yield engine
        finally:
            engine.dispose()
            conn.close()
            logger.info(f"[SandboxManager] Nettoyage sandbox SQLite in-memory ({sandbox_id})")

    def _materialize_sql_engine(
        self, dialect: str, sandbox_id: str, statements: list[str]
    ) -> Generator[Engine, None, None]:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        cursor = conn.cursor()
        for stmt in statements:
            stmt_adapted = self._adapt_stmt_for_sqlite(stmt, dialect)
            try:
                cursor.execute(stmt_adapted)
            except Exception as exc:
                logger.warning(f"[SandboxManager] Fallback stmt exec issue: {exc} | STMT: {stmt[:60]}")
        conn.commit()

        engine = create_engine("sqlite://", creator=lambda: conn)
        logger.info(f"[SandboxManager] Sandbox matérialisée ({dialect}) ({sandbox_id})")

        try:
            yield engine
        finally:
            engine.dispose()
            conn.close()
            logger.info(f"[SandboxManager] Nettoyage sandbox {dialect} ({sandbox_id})")

    @staticmethod
    def _adapt_stmt_for_sqlite(stmt: str, dialect: str) -> str:
        s = stmt
        
        # Universal views fix
        s = re.sub(r"\bCREATE\s+OR\s+REPLACE\s+VIEW\b", "CREATE VIEW", s, flags=re.IGNORECASE)
        
        if dialect == "postgresql":
            # Fix SERIAL PRIMARY KEY -> INTEGER PRIMARY KEY AUTOINCREMENT
            s = re.sub(r"\bSERIAL\s+PRIMARY\s+KEY\b", "INTEGER PRIMARY KEY AUTOINCREMENT", s, flags=re.IGNORECASE)
            s = re.sub(r"\bBIGSERIAL\s+PRIMARY\s+KEY\b", "INTEGER PRIMARY KEY AUTOINCREMENT", s, flags=re.IGNORECASE)
            s = re.sub(r"\bSERIAL\b", "INTEGER", s, flags=re.IGNORECASE)
            s = re.sub(r"\bBIGSERIAL\b", "INTEGER", s, flags=re.IGNORECASE)
            s = re.sub(r"\bTIMESTAMP WITH TIME ZONE\b", "TIMESTAMP", s, flags=re.IGNORECASE)
        elif dialect == "mysql":
            # Clean up MySQL specific table options first
            s = re.sub(r"\bENGINE\s*=\s*[a-zA-Z0-9_-]+", "", s, flags=re.IGNORECASE)
            s = re.sub(r"\bAUTO_INCREMENT\s*=\s*\d+", "", s, flags=re.IGNORECASE)
            s = re.sub(r"\bDEFAULT\s+CHARSET\s*=\s*[a-zA-Z0-9_-]+", "", s, flags=re.IGNORECASE)
            s = re.sub(r"\bCOLLATE\s*=\s*[a-zA-Z0-9_-]+", "", s, flags=re.IGNORECASE)
            s = re.sub(r"\bCOLLATE\s+[a-zA-Z0-9_-]+", "", s, flags=re.IGNORECASE)

            # Replace column definition with AUTO_INCREMENT PRIMARY KEY first
            s = re.sub(
                r"\b(?:INT|BIGINT|MEDIUMINT|SMALLINT|TINYINT)(?:\(\d+\))?\s+(?:UNSIGNED\s+)?(?:NOT\s+NULL\s+)?AUTO_INCREMENT\s+PRIMARY\s+KEY\b",
                "INTEGER PRIMARY KEY AUTOINCREMENT",
                s,
                flags=re.IGNORECASE
            )
            
            # If there's still AUTO_INCREMENT (meaning it doesn't have PRIMARY KEY next to it on the column)
            if re.search(r"\bAUTO_INCREMENT\b", s, flags=re.IGNORECASE):
                auto_inc_match = re.search(
                    r"['\"\`]?([a-zA-Z0-9_]+)['\"\`]?\s+(?:INT|BIGINT|MEDIUMINT|SMALLINT|TINYINT)(?:\(\d+\))?\s+(?:UNSIGNED\s+)?(?:NOT\s+NULL\s+)?AUTO_INCREMENT",
                    s,
                    flags=re.IGNORECASE
                )
                if auto_inc_match:
                    col_name = auto_inc_match.group(1)
                    # Replace column definition with INTEGER PRIMARY KEY AUTOINCREMENT
                    s = re.sub(
                        r"(['\"\`]?" + re.escape(col_name) + r"['\"\`]?\s+)(?:INT|BIGINT|MEDIUMINT|SMALLINT|TINYINT)(?:\(\d+\))?\s+(?:UNSIGNED\s+)?(?:NOT\s+NULL\s+)?AUTO_INCREMENT",
                        r"\1INTEGER PRIMARY KEY AUTOINCREMENT",
                        s,
                        flags=re.IGNORECASE
                    )
                    # Remove table-level PRIMARY KEY constraint for this column
                    s = re.sub(rf",\s*\bPRIMARY\s+KEY\s*\(\s*['\"\`]?{re.escape(col_name)}['\"\`]?\s*\)", "", s, flags=re.IGNORECASE)
                    s = re.sub(rf"\bPRIMARY\s+KEY\s*\(\s*['\"\`]?{re.escape(col_name)}['\"\`]?\s*\)\s*,?", "", s, flags=re.IGNORECASE)

            # Convert UNIQUE KEY `name` (`col`) -> UNIQUE (`col`)
            s = re.sub(r"\bUNIQUE\s+KEY\s*(?:['\"\`]?\w+['\"\`]?\s*)?\(([^)]+)\)", r"UNIQUE(\1)", s, flags=re.IGNORECASE)
            # Remove KEY `name` (`col`) constraints inside table definitions
            s = re.sub(r",\s*\bKEY\s+['\"\`]?\w+['\"\`]?\s*\([^)]+\)", "", s, flags=re.IGNORECASE)
            s = re.sub(r"\bKEY\s+['\"\`]?\w+['\"\`]?\s*\([^)]+\)\s*,?", "", s, flags=re.IGNORECASE)
            
            # Cleanup any remaining standalone AUTO_INCREMENT keyword
            s = re.sub(r"\bAUTO_INCREMENT\b", "AUTOINCREMENT", s, flags=re.IGNORECASE)
            
            # Fix MySQL current_timestamp() syntax error in SQLite
            s = re.sub(r"\bcurrent_timestamp\(\)", "CURRENT_TIMESTAMP", s, flags=re.IGNORECASE)
        elif dialect == "oracle":
            # Convert TO_DATE('str', 'format') -> 'str'
            s = re.sub(r"\bTO_DATE\s*\(\s*'([^']*)'\s*,\s*'[^']*'\s*\)", r"'\1'", s, flags=re.IGNORECASE)
            # Convert NUMBER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY -> INTEGER PRIMARY KEY AUTOINCREMENT
            s = re.sub(
                r"\bNUMBER\s+GENERATED\s+(?:BY\s+DEFAULT|ALWAYS)\s+AS\s+IDENTITY\s+PRIMARY\s+KEY\b",
                "INTEGER PRIMARY KEY AUTOINCREMENT",
                s,
                flags=re.IGNORECASE
            )
            s = re.sub(
                r"\bNUMBER\s+GENERATED\s+(?:BY\s+DEFAULT|ALWAYS)\s+AS\s+IDENTITY\b",
                "INTEGER",
                s,
                flags=re.IGNORECASE
            )
            s = re.sub(r"\bVARCHAR2\((\d+)\)", r"VARCHAR(\1)", s, flags=re.IGNORECASE)
            s = re.sub(r"\bNUMBER\((\d+),?\s*(\d+)?\)", "NUMERIC", s, flags=re.IGNORECASE)
            s = re.sub(r"\bDEFAULT\s+SYSDATE\b", "DEFAULT CURRENT_TIMESTAMP", s, flags=re.IGNORECASE)
        return s
