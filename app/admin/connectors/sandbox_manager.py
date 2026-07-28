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
        if dialect == "postgresql":
            # Fix SERIAL PRIMARY KEY -> INTEGER PRIMARY KEY AUTOINCREMENT
            s = re.sub(r"\bSERIAL\s+PRIMARY\s+KEY\b", "INTEGER PRIMARY KEY AUTOINCREMENT", s, flags=re.IGNORECASE)
            s = re.sub(r"\bBIGSERIAL\s+PRIMARY\s+KEY\b", "INTEGER PRIMARY KEY AUTOINCREMENT", s, flags=re.IGNORECASE)
            s = re.sub(r"\bSERIAL\b", "INTEGER", s, flags=re.IGNORECASE)
            s = re.sub(r"\bBIGSERIAL\b", "INTEGER", s, flags=re.IGNORECASE)
            s = re.sub(r"\bTIMESTAMP WITH TIME ZONE\b", "TIMESTAMP", s, flags=re.IGNORECASE)
        elif dialect == "mysql":
            s = re.sub(r"\bINT\s+AUTO_INCREMENT\s+PRIMARY\s+KEY\b", "INTEGER PRIMARY KEY AUTOINCREMENT", s, flags=re.IGNORECASE)
            s = re.sub(r"\bAUTO_INCREMENT\b", "AUTOINCREMENT", s, flags=re.IGNORECASE)
            s = re.sub(r"\bENGINE\s*=\s*\w+", "", s, flags=re.IGNORECASE)
            s = re.sub(r"\bDEFAULT\s+CHARSET\s*=\s*\w+", "", s, flags=re.IGNORECASE)
        elif dialect == "oracle":
            s = re.sub(r"\bVARCHAR2\((\d+)\)", r"VARCHAR(\1)", s, flags=re.IGNORECASE)
            s = re.sub(r"\bNUMBER\((\d+),?\s*(\d+)?\)", "NUMERIC", s, flags=re.IGNORECASE)
        return s
