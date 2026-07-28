"""
app/admin/connectors/dump_parser.py

Parsing et nettoyage des fichiers de dump SQL pour PostgreSQL, MySQL, Oracle, SQL Server et SQLite.
- Détection automatique ou validation du dialecte moteur
- Découpage robuste en instructions SQL exploitables
- Suppression des commentaires et instructions non supportées
"""

import re
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

SUPPORTED_ENGINES = {"postgresql", "mysql", "oracle", "mssql", "sqlite"}


class DumpParseError(Exception):
    pass


class DumpParser:

    @staticmethod
    def normalize_engine(engine: str) -> str:
        engine_clean = engine.strip().lower()
        mapping = {
            "postgres": "postgresql",
            "postgresql": "postgresql",
            "mysql": "mysql",
            "oracle": "oracle",
            "sqlite": "sqlite",
            "sqlite3": "sqlite",
            "sqlserver": "mssql",
            "mssql": "mssql",
            "sql_server": "mssql",
            "sql server": "mssql",
        }
        if engine_clean not in mapping:
            raise DumpParseError(
                f"Moteur non supporté : '{engine}'. Moteurs autorisés : {', '.join(sorted(SUPPORTED_ENGINES))}"
            )
        return mapping[engine_clean]

    def detect_engine(self, sql_content: str) -> Optional[str]:
        content_lower = sql_content.lower()
        if "postgresql" in content_lower or "pg_dump" in content_lower or "create table public." in content_lower:
            return "postgresql"
        if "mysqldump" in content_lower or "engine=innodb" in content_lower or "auto_increment" in content_lower:
            return "mysql"
        if "sqlite_master" in content_lower or "autoincrement" in content_lower:
            return "sqlite"
        if "identity(1,1)" in content_lower or "nvarchar(" in content_lower or "dbo." in content_lower:
            return "mssql"
        if "varchar2(" in content_lower or "number(" in content_lower or "sysdate" in content_lower:
            return "oracle"
        return None

    def parse_statements(self, sql_content: str, engine: str) -> List[str]:
        engine_normalized = self.normalize_engine(engine)
        
        # 1. Clean multi-line and single-line comments
        cleaned_sql = self._strip_comments(sql_content, engine_normalized)
        
        # 2. Split statements cleanly
        raw_statements = self._split_sql_statements(cleaned_sql)

        # 3. Filter out empty statements or unsupported directives (e.g. SET client_encoding, etc.)
        valid_statements: List[str] = []
        for stmt in raw_statements:
            stmt_trimmed = stmt.strip()
            if not stmt_trimmed:
                continue
            if self._is_ignorable_directive(stmt_trimmed, engine_normalized):
                continue
            valid_statements.append(stmt_trimmed)

        logger.info(
            f"[DumpParser] Dialecte='{engine_normalized}' — {len(valid_statements)} instruction(s) extraite(s)"
        )
        return valid_statements

    def _strip_comments(self, sql: str, engine: str) -> str:
        # Strip C-style /* ... */ comments
        sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
        
        # Strip single-line comments (-- ...)
        lines = []
        for line in sql.splitlines():
            # Keep line content before single-line comment marker --
            stripped_line = re.sub(r"--.*$", "", line)
            if engine == "mysql":
                # MySQL inline comment `#`
                stripped_line = re.sub(r"#.*$", "", stripped_line)
            lines.append(stripped_line)
            
        return "\n".join(lines)

    def _split_sql_statements(self, sql: str) -> List[str]:
        statements = []
        current_stmt: List[str] = []
        in_single_quote = False
        in_double_quote = False
        in_dollar_quote = False
        dollar_tag = ""
        escape = False

        i = 0
        n = len(sql)

        while i < n:
            char = sql[i]

            # Handle dollar quoting (PostgreSQL $$ or $tag$)
            if not in_single_quote and not in_double_quote:
                if char == "$" and not in_dollar_quote:
                    match = re.match(r"^\$[A-Za-z0-9_]*\$", sql[i:])
                    if match:
                        dollar_tag = match.group(0)
                        in_dollar_quote = True
                        current_stmt.append(dollar_tag)
                        i += len(dollar_tag)
                        continue
                elif in_dollar_quote and sql[i:].startswith(dollar_tag):
                    in_dollar_quote = False
                    current_stmt.append(dollar_tag)
                    i += len(dollar_tag)
                    dollar_tag = ""
                    continue

            if in_dollar_quote:
                current_stmt.append(char)
                i += 1
                continue

            # Handle escapes
            if escape:
                current_stmt.append(char)
                escape = False
                i += 1
                continue

            if char == "\\":
                current_stmt.append(char)
                escape = True
                i += 1
                continue

            # Handle single quotes
            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
                current_stmt.append(char)
                i += 1
                continue

            # Handle double quotes
            if char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
                current_stmt.append(char)
                i += 1
                continue

            # Statement boundary: semicolon outside string literal
            if char == ";" and not in_single_quote and not in_double_quote:
                stmt_str = "".join(current_stmt).strip()
                if stmt_str:
                    statements.append(stmt_str)
                current_stmt = []
                i += 1
                continue

            current_stmt.append(char)
            i += 1

        remainder = "".join(current_stmt).strip()
        if remainder:
            statements.append(remainder)

        return statements

    def _is_ignorable_directive(self, stmt: str, engine: str) -> bool:
        stmt_upper = stmt.upper()

        # Transaction management directives that are handled at session level
        if stmt_upper in {"BEGIN TRANSACTION", "COMMIT", "ROLLBACK", "START TRANSACTION"}:
            return False

        # Ignore dump header metadata like SET client_encoding, LOCK TABLES, UNLOCK TABLES, etc.
        ignored_prefixes = [
            "SET ",
            "LOCK TABLES",
            "UNLOCK TABLES",
            "/*!40101",
            "USE ",
            "SELECT PG_CATALOG.",
            "SELECT SETVAL",
        ]
        for prefix in ignored_prefixes:
            if stmt_upper.startswith(prefix):
                return True

        return False
