import unittest
import tempfile
import shutil
from pathlib import Path

from app.admin.connectors.sandbox_manager import SandboxManager
from app.nl2sql.schema_scanner import SchemaScanner

class TestSandboxManager(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.sandbox_manager = SandboxManager(base_dir=self.temp_dir)
        self.scanner = SchemaScanner()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_sandbox_sqlite(self):
        sql = """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            quantity INTEGER,
            FOREIGN KEY(product_id) REFERENCES products(id)
        );
        """
        with self.sandbox_manager.create_sandbox("sqlite", sql, tenant_id="tenant_1") as engine:
            result = self.scanner.scan(engine, connection_id="test_conn")
            self.assertEqual(len(result.tables), 2)
            table_names = {t.name for t in result.tables}
            self.assertIn("products", table_names)
            self.assertIn("orders", table_names)

        # Verify sandbox DB file was cleaned up
        remaining_files = list(self.temp_dir.glob("*.sqlite"))
        self.assertEqual(len(remaining_files), 0)

    def test_create_sandbox_postgres_materialization(self):
        sql = """
        CREATE TABLE employees (
            id SERIAL PRIMARY KEY,
            full_name VARCHAR(100) NOT NULL,
            department VARCHAR(50)
        );
        """
        with self.sandbox_manager.create_sandbox("postgresql", sql, tenant_id="tenant_2") as engine:
            result = self.scanner.scan(engine, connection_id="test_conn_pg")
            self.assertEqual(len(result.tables), 1)
            self.assertEqual(result.tables[0].name, "employees")

        # Verify cleanup
        remaining_files = list(self.temp_dir.glob("*.sqlite"))
        self.assertEqual(len(remaining_files), 0)

if __name__ == "__main__":
    unittest.main()
