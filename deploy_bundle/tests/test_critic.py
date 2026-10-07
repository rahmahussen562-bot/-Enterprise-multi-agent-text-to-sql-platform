"""
Unit tests for agents.critic RuntimeCriticAgent hallucination detection and schema grounding.
"""

from tests._credentials import LEGACY_PASSWORDS
import unittest

from agents.critic import EvaluationResult, RuntimeCriticAgent
from core.auth import authenticate
from core.config import DatabaseConfig
from core.database import DatabaseEngine
from utils.db_seeder import seed_database


class TestCriticSchemaGrounding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_db_path = "data/test_critic_tsql.sqlite"
        seed_database(cls.test_db_path, seed_vanna=False)
        cls.config = DatabaseConfig(dialect="tsql", sqlite_path=cls.test_db_path)
        cls.db = DatabaseEngine(cls.config)
        cls.critic = RuntimeCriticAgent(cls.db, timeout_sec=10)
        cls.sales_user = authenticate("sales_analyst", LEGACY_PASSWORDS["sales_analyst"])

    def test_detects_unauthorized_table_hallucination(self):
        # sales_analyst cannot query Track table
        hallucinated_sql = "SELECT TOP 10 [TrackId], [Name] FROM [Track];"
        critique = self.critic.validate_schema_grounding(
            hallucinated_sql,
            user_session=self.sales_user
        )
        self.assertIsNotNone(critique)
        self.assertEqual(critique["type"], "HALLUCINATION_UNAUTHORIZED_TABLE")
        self.assertIn("Track", critique["message"])

    def test_detects_fabricated_column_hallucination(self):
        # Customer table does not have [SecretDiscountCode] or [NonExistentColumn]
        hallucinated_sql = "SELECT TOP 5 [CustomerId], [SecretDiscountCode] FROM [Customer];"
        critique = self.critic.validate_schema_grounding(
            hallucinated_sql,
            user_session=self.sales_user
        )
        self.assertIsNotNone(critique)
        self.assertEqual(critique["type"], "HALLUCINATION_INVALID_COLUMN")
        self.assertIn("SecretDiscountCode", critique["message"])

    def test_allows_valid_grounded_query(self):
        valid_sql = "SELECT TOP 5 [CustomerId], [FirstName], [Country] FROM [Customer] WHERE [Country] = 'Brazil';"
        critique = self.critic.validate_schema_grounding(
            valid_sql,
            user_session=self.sales_user
        )
        self.assertIsNone(critique)

        # Full evaluation should succeed
        res: EvaluationResult = self.critic.evaluate(
            question="Top 5 Brazilian customers",
            sql=valid_sql,
            user_session=self.sales_user
        )
        self.assertTrue(res.success)
        self.assertFalse(res.df.empty)
        self.assertEqual(len(res.df), 5)


if __name__ == "__main__":
    unittest.main()
