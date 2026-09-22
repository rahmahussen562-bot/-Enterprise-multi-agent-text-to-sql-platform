"""
Unit tests for core.database DatabaseEngine for Microsoft SQL Server (T-SQL).
Tests table enumeration filtered by RBAC, schema DDLs with bracket escaping,
and T-SQL value probing.
"""
import unittest

from core.config import DatabaseConfig
from core.database import DatabaseEngine
from utils.db_seeder import seed_database


class TestDatabaseEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_db_path = "data/test_db_tsql.sqlite"
        seed_database(cls.test_db_path, seed_vanna=False)
        cls.db = DatabaseEngine(DatabaseConfig(dialect="tsql", sqlite_path=cls.test_db_path))

    def test_connection(self):
        ok, msg = self.db.test_connection()
        self.assertTrue(ok)
        self.assertIn("T-SQL", msg)

    def test_table_names_unfiltered(self):
        tables = self.db.get_table_names()
        self.assertIn("Customer", tables)
        self.assertIn("Invoice", tables)
        self.assertIn("Track", tables)

    def test_table_names_filtered_by_rbac(self):
        sales_tables = self.db.get_table_names(authorized_tables=["Customer", "Invoice"])
        self.assertIn("Customer", sales_tables)
        self.assertIn("Invoice", sales_tables)
        self.assertNotIn("Track", sales_tables)
        self.assertNotIn("Album", sales_tables)

    def test_get_table_schema_ddl(self):
        ddl = self.db.get_table_schema_ddl("Customer")
        self.assertIn("CREATE TABLE [Customer]", ddl)
        self.assertIn("[CustomerId]", ddl)

    def test_get_foreign_keys_filtered(self):
        fks = self.db.get_foreign_keys(authorized_tables=["Customer", "Invoice"])
        self.assertGreater(len(fks), 0)
        # All returned FKs must connect only authorized tables
        for fk in fks:
            self.assertIn(fk["from_table"], ["Customer", "Invoice"])
            self.assertIn(fk["to_table"], ["Customer", "Invoice"])

    def test_probe_distinct_values_tsql(self):
        vals = self.db.probe_distinct_values("Customer", "Country", limit=5)
        self.assertGreater(len(vals), 0)
        self.assertTrue(any("Brazil" in v or "USA" in v or "Germany" in v for v in vals))

    def test_execute_query_tsql(self):
        # T-SQL query with TOP and brackets
        df = self.db.execute_query("SELECT TOP 5 [CustomerId], [FirstName], [Country] FROM [Customer];")
        self.assertEqual(len(df), 5)
        self.assertIn("CustomerId", df.columns)


if __name__ == "__main__":
    unittest.main()
