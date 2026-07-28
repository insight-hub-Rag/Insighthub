import sys
from unittest.mock import MagicMock

# Mock third-party dependencies that are missing or compile-heavy
sys.modules["psycopg2"] = MagicMock()
sys.modules["jira"] = MagicMock()
sys.modules["office365"] = MagicMock()
sys.modules["office365.runtime"] = MagicMock()
sys.modules["office365.runtime.auth"] = MagicMock()
sys.modules["office365.runtime.auth.client_credential"] = MagicMock()
sys.modules["office365.sharepoint"] = MagicMock()
sys.modules["office365.sharepoint.client_context"] = MagicMock()
sys.modules["sentence_transformers"] = MagicMock()
sys.modules["pgvector"] = MagicMock()
sys.modules["pgvector.psycopg2"] = MagicMock()
sys.modules["cryptography"] = MagicMock()
sys.modules["cryptography.fernet"] = MagicMock()

import unittest
from fastapi.testclient import TestClient

from app.db.database import get_db

class MockAsyncSession:
    async def execute(self, *args, **kwargs):
        mock_result = MagicMock()
        mock_result.mappings.return_value.first.return_value = None
        return mock_result

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

from main import app
app.dependency_overrides[get_db] = lambda: MockAsyncSession()


class TestDumpUploadPipeline(unittest.TestCase):

    def test_upload_postgres_dump_success(self):
        dump_content = b"""
        -- Dump PostgreSQL
        CREATE TABLE company_departments (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL
        );

        CREATE TABLE company_employees (
            id SERIAL PRIMARY KEY,
            department_id INT,
            full_name VARCHAR(150) NOT NULL,
            FOREIGN KEY (department_id) REFERENCES company_departments(id)
        );
        """

        with TestClient(app) as client:
            response = client.post(
                "/nl2sql/upload-dump",
                data={"engine_type": "postgresql", "tenant_id": "tenant_acme"},
                files={"file": ("pg_dump.sql", dump_content, "text/plain")}
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["engine_dialect"], "postgresql")
        self.assertEqual(data["connection_id"], "tenant_acme")

        tables = data["tables"]
        self.assertEqual(len(tables), 2)
        table_names = {t["name"] for t in tables}
        self.assertIn("company_departments", table_names)
        self.assertIn("company_employees", table_names)

    def test_upload_mysql_dump_success(self):
        dump_content = b"""
        # Dump MySQL
        CREATE TABLE inventory_categories (
            id INT AUTO_INCREMENT PRIMARY KEY,
            title VARCHAR(100) NOT NULL
        ) ENGINE=InnoDB;
        """

        with TestClient(app) as client:
            response = client.post(
                "/nl2sql/upload-dump",
                data={"engine_type": "mysql", "tenant_id": "tenant_globex"},
                files={"file": ("mysql_dump.sql", dump_content, "text/plain")}
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["engine_dialect"], "mysql")
        self.assertEqual(data["connection_id"], "tenant_globex")

    def test_upload_invalid_extension(self):
        with TestClient(app) as client:
            response = client.post(
                "/nl2sql/upload-dump",
                data={"engine_type": "postgresql"},
                files={"file": ("malicious.exe", b"binary", "application/octet-stream")}
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Extension de fichier non autorisée", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
