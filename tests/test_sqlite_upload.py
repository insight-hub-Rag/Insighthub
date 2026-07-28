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

import os
import sqlite3
import unittest
import tempfile
import shutil
from pathlib import Path
from fastapi.testclient import TestClient

# Mock database dependency injection
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

class TestSqliteUpload(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Create a temporary sqlite file
        cls.temp_dir = tempfile.mkdtemp()
        cls.db_file = Path(cls.temp_dir) / "test_schema.sqlite"
        
        conn = sqlite3.connect(cls.db_file)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE test_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE test_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES test_users(id)
            )
        """)
        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_upload_sqlite_success(self):
        with TestClient(app) as client:
            with open(self.db_file, "rb") as f:
                response = client.post(
                    "/nl2sql/upload-sqlite",
                    files={"file": ("test_schema.sqlite", f, "application/octet-stream")}
                )
                
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["engine_dialect"], "sqlite")
            
            # Verify scanned tables exist in response
            tables = data["tables"]
            self.assertEqual(len(tables), 2)
            
            table_names = {t["name"] for t in tables}
            self.assertIn("test_users", table_names)
            self.assertIn("test_items", table_names)
            
            # Check columns
            users_table = next(t for t in tables if t["name"] == "test_users")
            self.assertIn("username", users_table["columns"])
            self.assertIn("id", users_table["columns"])

    def test_upload_sqlite_db_extension_success(self):
        with TestClient(app) as client:
            with open(self.db_file, "rb") as f:
                response = client.post(
                    "/nl2sql/upload-sqlite",
                    files={"file": ("my_database.db", f, "application/octet-stream")}
                )
                
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], "ok")
            self.assertEqual(data["database_name"], "my_database.db")

    def test_upload_sqlite_invalid_extension(self):
        with TestClient(app) as client:
            # Send a text file disguised as sqlite
            response = client.post(
                "/nl2sql/upload-sqlite",
                files={"file": ("test_schema.txt", b"some data", "text/plain")}
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("Extension de fichier non autorisée", response.json()["detail"])

    def test_upload_sqlite_invalid_signature(self):
        # Create file with correct extension but invalid sqlite header
        bad_file = Path(self.temp_dir) / "bad.db"
        bad_file.write_bytes(b"Not an sqlite database format!")
        
        with TestClient(app) as client:
            with open(bad_file, "rb") as f:
                response = client.post(
                    "/nl2sql/upload-sqlite",
                    files={"file": ("bad.db", f, "application/octet-stream")}
                )
            self.assertEqual(response.status_code, 400)
            self.assertIn("Fichier SQLite invalide", response.json()["detail"])

if __name__ == "__main__":
    unittest.main()
