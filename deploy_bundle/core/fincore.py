"""Reviewed banking relation/column policy and versioned metric grounding."""
from decimal import Decimal
from datetime import date
import json
from pathlib import Path

ROLE_COLUMNS = {
    "compliance_officer": {
        "compliance.kyc_reviews": "customer_id jurisdiction kyc_status verified_at risk_tier",
        "compliance.aml_transactions": "transaction_id customer_id branch_id business_date currency amount direction channel reversal_of flagged",
        "compliance.risk_assessments": "customer_id risk_tier risk_score assessed_at",
        "compliance.compliance_cases": "case_id customer_id case_type status opened_at risk_score",
        "compliance.screening_hits": "hit_id customer_id case_id list_source match_score disposition screened_at",
        "compliance.cash_daily_monitoring": "customer_id business_date cash_in_usd cash_out_usd threshold_usd requires_review metric_version",
    },
    "branch_analyst": {
        "branch.account_summaries": "account_id branch_id account_type currency business_date posted_balance active_holds available_balance metric_version",
        "branch.daily_flows": "branch_id business_date currency direction transaction_count total_amount",
        "branch.loan_performance": "loan_id account_id branch_id currency principal_outstanding annual_rate day_count days_past_due daily_interest metric_version",
    },
    "fraud_investigator": {
        "fraud.flagged_transactions": "transaction_id case_id branch_id business_date currency amount direction channel flagged",
        "fraud.card_events": "event_id case_id transaction_id card_token event_type event_time outcome",
        "fraud.investigation_cases": "case_id status opened_at reason_code",
    },
}
ROLE_COLUMNS = {role: {table: names.split() for table, names in tables.items()} for role, tables in ROLE_COLUMNS.items()}
PG_GROUPS = {"compliance_officer": "fincore_compliance", "branch_analyst": "fincore_branch", "fraud_investigator": "fincore_fraud"}


class FinancialMetricRegistry:
    """Only approved versions/relations can establish a financial definition."""
    def __init__(self, path=None):
        path = path or Path(__file__).resolve().parents[1] / "data/financial_metrics.v1.json"
        self.document = json.loads(Path(path).read_text(encoding="utf-8"))
        if self.document["version"] != "1.0.0":
            raise ValueError("Unsupported financial metric version.")

    def query(self, metric, role):
        definition = self.document["metrics"].get(metric)
        if not definition or role not in definition["roles"]:
            raise PermissionError("Metric is outside the authorized closed world.")
        relation = definition["relation"]
        if relation not in ROLE_COLUMNS[role]:
            raise PermissionError("Metric relation is not authorized.")
        from sqlglot import exp
        columns = [exp.column(name) for name in ROLE_COLUMNS[role][relation]]
        return exp.select(*columns).from_(relation).sql(dialect="postgres")


def day_count_fraction(start: date, end: date, convention: str) -> Decimal:
    if end < start:
        raise ValueError("Accrual end precedes start.")
    if convention in {"ACT/360", "ACT/365F"}:
        return Decimal((end - start).days) / Decimal(360 if convention == "ACT/360" else 365)
    if convention == "30E/360":
        days = 360 * (end.year - start.year) + 30 * (end.month - start.month) + min(end.day, 30) - min(start.day, 30)
        return Decimal(days) / Decimal(360)
    raise ValueError("Unregistered contractual day-count convention.")


def interest_accrual(principal, rate, start, end, convention):
    principal, rate = Decimal(principal), Decimal(rate)
    if not principal.is_finite() or not rate.is_finite() or principal < 0 or not 0 <= rate <= 1:
        raise ValueError("Invalid contractual principal/rate.")
    return principal * rate * day_count_fraction(start, end, convention)
