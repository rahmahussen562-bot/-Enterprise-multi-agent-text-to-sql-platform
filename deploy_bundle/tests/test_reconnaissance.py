"""
Unit tests for agents.reconnaissance ReconnaissanceAgent under RBAC constraints.
"""

from tests._credentials import LEGACY_PASSWORDS
import unittest

from agents.reconnaissance import ReconnaissanceAgent, SchemaCard
from core.auth import authenticate
from core.config import DatabaseConfig
from core.database import DatabaseEngine
from core.vanna_client import VannaTextToSQLEngine
from utils.db_seeder import seed_database


class TestReconnaissanceAgent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_path = "data/test_recon_tsql.sqlite"
        seed_database(cls.db_path, seed_vanna=False)
        cls.db = DatabaseEngine(DatabaseConfig(dialect="tsql", sqlite_path=cls.db_path))
        cls.vanna = VannaTextToSQLEngine()
        cls.explorer = ReconnaissanceAgent(cls.db, cls.vanna)
        cls.sales_user = authenticate("sales_analyst", LEGACY_PASSWORDS["sales_analyst"])
        cls.inv_user = authenticate("inventory_lead", LEGACY_PASSWORDS["inventory_lead"])

    def test_reconnaissance_under_sales_analyst_rbac(self):
        question = "Find total revenue for customers in Brazil"
        schema_card: SchemaCard = self.explorer.run(
            question,
            max_tables=5,
            authorized_tables=self.sales_user.authorized_tables
        )

        # Candidate tables must only be from sales_user whitelist
        for t in schema_card.candidate_tables:
            self.assertIn(t, self.sales_user.authorized_tables)
            self.assertNotIn(t, ["Track", "Album", "Artist"])

        # Value Grounding check for Brazil
        has_brazil_grounded = False
        for col_ref, vals in schema_card.grounded_values.items():
            if "country" in col_ref.lower() and any("brazil" in v.lower() for v in vals):
                has_brazil_grounded = True
                break
        self.assertTrue(has_brazil_grounded)

        # Context rendering includes T-SQL guidelines
        context_str = schema_card.to_prompt_context()
        self.assertIn("T-SQL", context_str)
        self.assertIn("[Customer]", context_str)

    def test_reconnaissance_under_inventory_lead_rbac(self):
        question = "List all albums by artist Queen"
        schema_card: SchemaCard = self.explorer.run(
            question,
            max_tables=5,
            authorized_tables=self.inv_user.authorized_tables
        )

        for t in schema_card.candidate_tables:
            self.assertIn(t, self.inv_user.authorized_tables)
            self.assertNotIn(t, ["Customer", "Invoice"])


if __name__ == "__main__":
    unittest.main()
