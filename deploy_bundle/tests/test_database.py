"""
Unit tests for core.database DatabaseEngine for Microsoft SQL Server (T-SQL).
Tests table enumeration filtered by RBAC, schema DDLs with bracket escaping,
T-SQL value probing, dynamic driver resolution, and connection string builders.
"""
import unittest

from core.config import DatabaseConfig, resolve_best_odbc_driver
from core.database import DatabaseEngine, MSSQLDatabaseEngine
from utils.db_seeder import seed_database


class TestDatabaseEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_db_path = "data/test_db_tsql.sqlite"
        seed_database(cls.test_db_path, seed_vanna=False)
        cls.config = DatabaseConfig(dialect="tsql", sqlite_path=cls.test_db_path)
        cls.db = DatabaseEngine(cls.config)

    def test_connection(self):
        ok, msg, latency, mode = self.db.test_connection()
        self.assertTrue(ok)
        self.assertIn("T-SQL", msg)
        self.assertIn(mode, ["MOCK_EMULATOR", "LIVE_MSSQL"])
        self.assertGreaterEqual(latency, 0.0)

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
        for fk in fks:
            self.assertIn(fk["from_table"], ["Customer", "Invoice"])
            self.assertIn(fk["to_table"], ["Customer", "Invoice"])

    def test_probe_distinct_values_tsql(self):
        vals = self.db.probe_distinct_values("Customer", "Country", limit=5)
        self.assertGreater(len(vals), 0)
        self.assertTrue(any("Brazil" in v or "USA" in v or "Germany" in v for v in vals))

    def test_execute_query_tsql(self):
        df = self.db.execute_query("SELECT TOP 5 [CustomerId], [FirstName], [Country] FROM [Customer];")
        self.assertEqual(len(df), 5)
        self.assertIn("CustomerId", df.columns)

    # -------------------------------------------------------------------------
    # Driver Resolution & Connection Builder Tests
    # -------------------------------------------------------------------------
    def test_driver_resolution_hierarchy(self):
        # Case 1: All drivers installed -> picks Driver 18
        all_drivers = [
            "SQL Server",
            "ODBC Driver 17 for SQL Server",
            "ODBC Driver 18 for SQL Server",
            "SQL Server Native Client 11.0"
        ]
        self.assertEqual(resolve_best_odbc_driver(all_drivers), "ODBC Driver 18 for SQL Server")

        # Case 2: Driver 18 missing -> picks Driver 17
        sub_drivers = ["SQL Server", "ODBC Driver 17 for SQL Server"]
        self.assertEqual(resolve_best_odbc_driver(sub_drivers), "ODBC Driver 17 for SQL Server")

        # Case 3: Only Native Client installed -> picks Native Client
        nc_drivers = ["SQL Server", "SQL Server Native Client 11.0"]
        self.assertEqual(resolve_best_odbc_driver(nc_drivers), "SQL Server Native Client 11.0")

        # Case 4: No modern drivers -> falls back to SQL Server
        self.assertEqual(resolve_best_odbc_driver(["SQL Server"]), "SQL Server")
        self.assertEqual(resolve_best_odbc_driver([]), "SQL Server")

    def test_connection_string_builder_windows_auth(self):
        cfg = DatabaseConfig(
            server=r"sql-server.corp.local\INST01",
            database="FinancialDB",
            trusted_connection=True,
            driver="ODBC Driver 17 for SQL Server"
        )
        conn_str = cfg.get_odbc_connection_string()
        self.assertIn("DRIVER={ODBC Driver 17 for SQL Server}", conn_str)
        self.assertIn(r"SERVER=sql-server.corp.local\INST01", conn_str)
        self.assertIn("DATABASE=FinancialDB", conn_str)
        self.assertIn("Trusted_Connection=yes", conn_str)
        self.assertNotIn("UID=", conn_str)

    def test_connection_string_builder_sql_auth(self):
        cfg = DatabaseConfig(
            server="10.0.1.50",
            database="CommerceDB",
            trusted_connection=False,
            username="app_user",
            password="SecurePassword2026!",
            driver="SQL Server"
        )
        conn_str = cfg.get_odbc_connection_string()
        self.assertIn("UID=app_user", conn_str)
        self.assertIn("PWD=SecurePassword2026!", conn_str)
        self.assertNotIn("Trusted_Connection=yes", conn_str)

    def test_connection_string_sanitization(self):
        cfg = DatabaseConfig(
            server="prod-db",
            database="Vault",
            trusted_connection=False,
            username="vault_admin",
            password="SuperSecretPassword!",
            driver="SQL Server"
        )
        sanitized = cfg.get_sanitized_connection_string()
        self.assertNotIn("SuperSecretPassword!", sanitized)
        self.assertIn("PWD=***", sanitized)
        self.assertIn("UID=vault_admin", sanitized)

    def test_odbc_18_encryption_flags(self):
        cfg = DatabaseConfig(
            server="modern-sql.internal",
            database="Inventory",
            driver="ODBC Driver 18 for SQL Server",
            trust_server_certificate=True,
            encrypt="optional"
        )
        conn_str = cfg.get_odbc_connection_string()
        self.assertIn("DRIVER={ODBC Driver 18 for SQL Server}", conn_str)
        self.assertIn("TrustServerCertificate=yes", conn_str)
        self.assertIn("Encrypt=optional", conn_str)


if __name__ == "__main__":
    unittest.main()
