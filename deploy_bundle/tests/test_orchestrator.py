"""
Unit tests for agents.orchestrator CentralController with RBAC personas and T-SQL.
"""

from tests._credentials import LEGACY_PASSWORDS
import unittest

from agents.orchestrator import CentralController, OrchestrationResult
from core.auth import authenticate
from core.config import AgentConfig, DatabaseConfig, SystemConfig
from core.database import DatabaseEngine
from utils.db_seeder import seed_database


class TestCentralController(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "data/test_orch_tsql.sqlite"
        seed_database(cls.db_path, seed_vanna=True)
        cls.config = SystemConfig(
            db=DatabaseConfig(dialect="tsql", sqlite_path=cls.db_path),
            agent=AgentConfig(max_retries=3, defensive_limit=50)
        )
        cls.controller = CentralController(config=cls.config)
        cls.sales_user = authenticate("sales_analyst", LEGACY_PASSWORDS["sales_analyst"])
        cls.inv_user = authenticate("inventory_lead", LEGACY_PASSWORDS["inventory_lead"])

    def test_pipeline_execution_sales_analyst(self):
        question = "What are the total sales and invoice count for customers in Brazil?"
        result: OrchestrationResult = self.controller.execute_pipeline(
            question,
            user_session=self.sales_user
        )

        self.assertTrue(result.success, f"Pipeline failed: {result.error_message}")
        self.assertFalse(result.df.empty)
        self.assertIn("SELECT", result.final_sql.upper())
        self.assertIn("TOP", result.final_sql.upper())

        # Check that no unauthorized tables were queried
        for t in ["Track", "Album", "Artist"]:
            self.assertNotIn(f"[{t}]", result.final_sql)

        # Verify telemetry
        agent_names = {ev.agent_name for ev in result.events}
        self.assertIn("Explorer", agent_names)
        self.assertIn("Coder", agent_names)
        self.assertIn("Guardian", agent_names)
        self.assertIn("Evaluator", agent_names)

    def test_pipeline_execution_inventory_lead(self):
        question = "List Rock genre tracks with album and artist details"
        result: OrchestrationResult = self.controller.execute_pipeline(
            question,
            user_session=self.inv_user
        )

        self.assertTrue(result.success, f"Pipeline failed: {result.error_message}")
        self.assertFalse(result.df.empty)
        self.assertIn("TOP", result.final_sql.upper())

        # Check that no commercial tables were queried
        for t in ["Customer", "Invoice", "InvoiceLine"]:
            self.assertNotIn(f"[{t}]", result.final_sql)


if __name__ == "__main__":
    unittest.main()
