"""
Autonomous 4-Agent Topology for Text-to-SQL.
"""
from agents.coder import SQLCoderAgent
from agents.critic import EvaluationResult, RuntimeCriticAgent
from agents.guardian import ASTGuardianAgent, GuardianResult
from agents.orchestrator import (
    AgentEvent,
    CentralController,
    OrchestrationResult,
    RetryRecord,
)
from agents.reconnaissance import ReconnaissanceAgent, SchemaCard
try:
    from agents.visualizer import AutonomousVisualizer
except ImportError:
    AutonomousVisualizer = None

__all__ = [
    "ReconnaissanceAgent",
    "SchemaCard",
    "SQLCoderAgent",
    "ASTGuardianAgent",
    "GuardianResult",
    "RuntimeCriticAgent",
    "EvaluationResult",
    "CentralController",
    "OrchestrationResult",
    "AgentEvent",
    "RetryRecord",
]
if AutonomousVisualizer is not None:
    __all__.append("AutonomousVisualizer")
