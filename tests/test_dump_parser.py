import unittest
from app.admin.connectors.dump_parser import DumpParser, DumpParseError

class TestDumpParser(unittest.TestCase):

    def setUp(self):
        self.parser = DumpParser()

    def test_normalize_engine(self):
        self.assertEqual(self.parser.normalize_engine("postgres"), "postgresql")
        self.assertEqual(self.parser.normalize_engine("PostgreSQL"), "postgresql")
        self.assertEqual(self.parser.normalize_engine("MySQL"), "mysql")
        self.assertEqual(self.parser.normalize_engine("sqlite3"), "sqlite")
        self.assertEqual(self.parser.normalize_engine("sql server"), "mssql")
        with self.assertRaises(DumpParseError):
            self.parser.normalize_engine("unknown_engine")

    def test_detect_engine(self):
        self.assertEqual(self.parser.detect_engine("CREATE TABLE users (id SERIAL PRIMARY KEY, name VARCHAR); -- pg_dump"), "postgresql")
        self.assertEqual(self.parser.detect_engine("CREATE TABLE items (id INT AUTO_INCREMENT PRIMARY KEY) ENGINE=InnoDB;"), "mysql")
        self.assertEqual(self.parser.detect_engine("CREATE TABLE t (id INT IDENTITY(1,1), name NVARCHAR(100));"), "mssql")

    def test_parse_statements_postgres(self):
        sql = """
        -- Comment line
        /* Multi line
           comment */
        CREATE TABLE users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) NOT NULL
        );
        
        INSERT INTO users (email) VALUES ('test@example.com');
        """
        stmts = self.parser.parse_statements(sql, "postgresql")
        self.assertEqual(len(stmts), 2)
        self.assertTrue(stmts[0].startswith("CREATE TABLE users"))
        self.assertTrue(stmts[1].startswith("INSERT INTO users"))

    def test_parse_statements_with_semicolons_in_quotes(self):
        sql = "INSERT INTO data (val) VALUES ('a;b;c'); SELECT * FROM data;"
        stmts = self.parser.parse_statements(sql, "sqlite")
        self.assertEqual(len(stmts), 2)
        self.assertEqual(stmts[0], "INSERT INTO data (val) VALUES ('a;b;c')")
        self.assertEqual(stmts[1], "SELECT * FROM data")

if __name__ == "__main__":
    unittest.main()
