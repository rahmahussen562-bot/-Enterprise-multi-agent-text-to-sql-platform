"""
Unit tests for agents.guardian ASTGuardianAgent for Microsoft SQL Server (T-SQL).
Tests injection firewall, multi-statement quarantine, RBAC table whitelists,
TOP 100 injection, and Cartesian join defense.
"""
import unittest
from agents.guardian import ASTGuardianAgent


class TestASTGuardianAgent(unittest.TestCase):
    def setUp(self):
        self.guardian = ASTGuardianAgent(default_limit=100, dialect="tsql")

    def test_valid_select_with_top_injection(self):
        raw_sql = "SELECT [CustomerId], [FirstName] FROM [Customer]"
        res = self.guardian.audit(
            raw_sql,
            valid_tables=["Customer", "Invoice"],
            authorized_tables=["Customer", "Invoice"],
            username="sales_analyst"
        )
        self.assertTrue(res.is_valid)
        self.assertTrue(res.limit_injected)
        self.assertIn("TOP 100", res.sanitized_sql.upper())

    def test_preserves_existing_top_clause(self):
        raw_sql = "SELECT TOP 25 [CustomerId], [FirstName] FROM [Customer]"
        res = self.guardian.audit(
            raw_sql,
            valid_tables=["Customer"],
            authorized_tables=["Customer"],
            username="sales_analyst"
        )
        self.assertTrue(res.is_valid)
        self.assertFalse(res.limit_injected)
        self.assertIn("TOP 25", res.sanitized_sql.upper())

    def test_blocks_destructive_drop(self):
        destructive_sql = "DROP TABLE [Customer];"
        res = self.guardian.audit(
            destructive_sql,
            valid_tables=["Customer"],
            authorized_tables=["Customer"],
            username="sales_analyst"
        )
        self.assertFalse(res.is_valid)
        self.assertEqual(res.critique["type"], "AST_SECURITY_VIOLATION")

    def test_blocks_destructive_delete(self):
        destructive_sql = "DELETE FROM [Invoice] WHERE [Total] > 10;"
        res = self.guardian.audit(
            destructive_sql,
            valid_tables=["Invoice"],
            authorized_tables=["Invoice"],
            username="sales_analyst"
        )
        self.assertFalse(res.is_valid)
        self.assertEqual(res.critique["type"], "AST_SECURITY_VIOLATION")

    def test_quarantines_multi_statement_injection(self):
        # Stacked query SQL injection attempt
        injection_sql = "SELECT * FROM [Customer]; DROP TABLE [Customer];"
        res = self.guardian.audit(
            injection_sql,
            valid_tables=["Customer"],
            authorized_tables=["Customer"],
            username="sales_analyst"
        )
        self.assertFalse(res.is_valid)
        self.assertIn(res.critique["type"], ["SQL_INJECTION_QUARANTINE", "AST_SECURITY_VIOLATION"])

    def test_blocks_exec_stored_procedure(self):
        exec_sql = "EXEC xp_cmdshell 'dir';"
        res = self.guardian.audit(
            exec_sql,
            valid_tables=["Customer"],
            authorized_tables=["Customer"],
            username="sales_analyst"
        )
        self.assertFalse(res.is_valid)
        self.assertIn(res.critique["type"], ["AST_SECURITY_VIOLATION", "INVALID_QUERY_ROOT"])

    def test_enforces_rbac_table_authorization(self):
        # sales_analyst attempting to query Track (restricted to inventory_lead)
        unauthorized_sql = "SELECT TOP 10 * FROM [Track];"
        res = self.guardian.audit(
            unauthorized_sql,
            valid_tables=["Customer", "Invoice", "Track"],
            authorized_tables=["Customer", "Invoice"],  # sales_analyst whitelist
            username="sales_analyst"
        )
        self.assertFalse(res.is_valid)
        self.assertEqual(res.critique["type"], "RBAC_AUTHORIZATION_VIOLATION")
        self.assertIn("track", res.critique["message"].lower())

    def test_detects_cartesian_product(self):
        cartesian_sql = "SELECT * FROM [Customer] JOIN [Invoice];"
        res = self.guardian.audit(
            cartesian_sql,
            valid_tables=["Customer", "Invoice"],
            authorized_tables=["Customer", "Invoice"],
            username="sales_analyst"
        )
        self.assertFalse(res.is_valid)
        self.assertEqual(res.critique["type"], "AST_CARTESIAN_PRODUCT")

    def test_preserves_valid_cte_with_top(self):
        valid_cte = """
        WITH [TopCustomers] AS (
            SELECT c.[CustomerId], c.[FirstName], c.[LastName]
            FROM [Customer] c
            INNER JOIN [Invoice] i ON c.[CustomerId] = i.[CustomerId]
            WHERE c.[Country] = 'Brazil'
        )
        SELECT TOP 10 * FROM [TopCustomers];
        """
        res = self.guardian.audit(
            valid_cte,
            valid_tables=["Customer", "Invoice"],
            authorized_tables=["Customer", "Invoice"],
            username="sales_analyst"
        )
        self.assertTrue(res.is_valid)


if __name__ == "__main__":
    unittest.main()
