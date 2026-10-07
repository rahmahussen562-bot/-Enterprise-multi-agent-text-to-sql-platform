"""Pipeline security decisions must stop before execution or regeneration."""
from unittest.mock import Mock, patch

import pandas as pd
import pytest
import sqlglot

from agents.critic import RuntimeCriticAgent
from agents.guardian import ASTGuardianAgent
from agents.intent_router import IntentResult, IntentRouter, IntentType
from agents.orchestrator import CentralController
from agents.reconnaissance import SchemaCard
from core.auth import UserSession
from core.config import AgentConfig, SystemConfig
from core.database import DatabaseEngine
from core.sql_validation import ValidationError


@pytest.fixture
def session():
    return UserSession("analyst", "Analyst", "Sales", ["Customer"], "Customer only")


@pytest.fixture
def controller():
    # Construct the controller with deterministic dependencies: no provider,
    # database connection, seed data, or persistent semantic-store writes.
    instance = CentralController.__new__(CentralController)
    instance.config = SystemConfig(agent=AgentConfig(max_retries=3, defensive_limit=100))
    instance.db = Mock(spec=DatabaseEngine)
    instance.db.get_table_names.return_value = ["Customer", "Track"]
    instance.db.get_table_columns_info.return_value = [
        {"name": "CustomerId", "type": "INTEGER"},
        {"name": "Country", "type": "TEXT"},
    ]
    instance.db.execute_query.return_value = pd.DataFrame({"CustomerId": [1]})
    instance.vanna = Mock()
    instance.vanna.retrieve_similar_examples.return_value = []
    instance.explorer = Mock()
    instance.explorer.run.return_value = SchemaCard(["Customer"], [], [], {})
    instance.coder = Mock()
    instance.coder.generate_sql.return_value = "SELECT TOP 25 CustomerId FROM Customer"
    instance.guardian = ASTGuardianAgent()
    instance.critic = RuntimeCriticAgent(instance.db)
    instance.intent_router = Mock(spec=IntentRouter)
    instance.intent_router.classify.return_value = IntentResult(IntentType.DATA_QUERY)
    return instance


def assert_terminal_without_execution(result, controller, code):
    assert not result.success
    assert code in result.error_message
    assert controller.coder.generate_sql.call_count == 1
    controller.db.execute_query.assert_not_called()
    assert result.retry_history == []
    assert not any(event.status == "retry" for event in result.events)
    assert result.events[-1].status == "failed"


def test_guardian_parser_failure_does_not_regenerate_or_execute(controller, session):
    controller.coder.generate_sql.side_effect = ["SELECT (", "SELECT CustomerId FROM Customer"]
    result = controller.execute_pipeline("Find customer records", user_session=session)
    assert_terminal_without_execution(result, controller, "AST_PARSER_FAILURE")
    assert result.events[-1].agent_name == "Guardian"


def test_parser_outage_is_terminal_after_guardian_denial(controller, session):
    with patch("sqlglot.parse", side_effect=RuntimeError("parser unavailable")):
        result = controller.execute_pipeline("Find customer records", user_session=session)
    assert_terminal_without_execution(result, controller, "AST_PARSER_FAILURE")


def test_critic_parser_failure_does_not_regenerate_or_execute(controller, session):
    with patch(
        "agents.critic.parse_single_query",
        side_effect=ValidationError("AST_PARSER_FAILURE", "parser unavailable at evaluator boundary"),
    ):
        result = controller.execute_pipeline("Find customer records", user_session=session)
    assert_terminal_without_execution(result, controller, "AST_PARSER_FAILURE")
    assert result.events[-1].agent_name == "Evaluator"


def test_permission_violation_cannot_self_heal_into_execution(controller, session):
    controller.coder.generate_sql.side_effect = ["SELECT * FROM Track", "SELECT * FROM Customer"]
    result = controller.execute_pipeline("Find customer records", user_session=session)
    assert_terminal_without_execution(result, controller, "RBAC_AUTHORIZATION_VIOLATION")


def test_unapproved_function_policy_is_terminal(controller, session):
    controller.coder.generate_sql.side_effect = [
        "SELECT dbo.unapproved_function() FROM Customer", "SELECT CustomerId FROM Customer",
    ]
    result = controller.execute_pipeline("Find customer records", user_session=session)
    assert_terminal_without_execution(result, controller, "AST_UNSUPPORTED_FUNCTION")


def test_unavailable_column_metadata_is_terminal(controller, session):
    controller.db.get_table_columns_info.return_value = []
    result = controller.execute_pipeline("Find customer records", user_session=session)
    assert_terminal_without_execution(result, controller, "HALLUCINATION_SCHEMA_UNAVAILABLE")


def test_legitimate_empty_result_completes_first_attempt_without_filter_mutation(controller, session):
    sql = "SELECT TOP 25 CustomerId FROM Customer WHERE Country = 'Unmatched'"
    controller.coder.generate_sql.return_value = sql
    controller.db.execute_query.return_value = pd.DataFrame(columns=["CustomerId"])
    result = controller.execute_pipeline("Find customers in Unmatched", user_session=session)
    assert result.success, result.error_message
    assert result.df.empty
    original = sqlglot.parse_one(sql, read="tsql")
    sanitized = sqlglot.parse_one(result.final_sql, read="tsql")
    assert sanitized.args["where"] == original.args["where"]
    assert sanitized.args["limit"] == original.args["limit"]
    controller.coder.generate_sql.assert_called_once()
    assert controller.coder.generate_sql.call_args.kwargs["critique"] is None
    controller.db.execute_query.assert_called_once_with(result.final_sql, timeout_sec=controller.critic.timeout_sec)
    assert result.retry_history == []
    assert not any(event.status == "retry" for event in result.events)


def test_missing_identity_denies_data_before_schema_or_generation(controller):
    result = controller.execute_pipeline("Find customer records")
    assert not result.success
    assert "AUTHENTICATION_REQUIRED" in result.error_message
    controller.explorer.run.assert_not_called()
    controller.coder.generate_sql.assert_not_called()
    controller.db.get_table_names.assert_not_called()
    controller.db.execute_query.assert_not_called()


def test_help_remains_available_without_identity(controller):
    controller.intent_router.classify.return_value = IntentResult(IntentType.HELP, response_message="Help text")
    result = controller.execute_pipeline("How can I use this platform?")
    assert result.success
    assert result.intent == "HELP"
    assert result.executive_narrative == "Help text"
    controller.explorer.run.assert_not_called()
    controller.coder.generate_sql.assert_not_called()
    controller.db.execute_query.assert_not_called()


def test_known_catalog_column_typo_retains_bounded_repair(controller, session):
    controller.coder.generate_sql.side_effect = [
        "SELECT TOP 25 CustomerTypo FROM Customer",
        "SELECT TOP 25 CustomerId FROM Customer",
    ]
    result = controller.execute_pipeline("Find customer records", user_session=session)
    assert result.success, result.error_message
    assert controller.coder.generate_sql.call_count == 2
    controller.db.execute_query.assert_called_once()
    assert len(result.retry_history) == 1
    assert result.retry_history[0].critique_type == "HALLUCINATION_INVALID_COLUMN"


def test_database_timeout_is_terminal_instead_of_repeating_work(controller, session):
    controller.db.execute_query.side_effect = TimeoutError("database operation cancelled")
    result = controller.execute_pipeline("Find customer records", user_session=session)
    assert not result.success
    assert "EXECUTION_TIMEOUT" in result.error_message
    controller.coder.generate_sql.assert_called_once()
    controller.db.execute_query.assert_called_once()
    assert not any(event.status == "retry" for event in result.events)
