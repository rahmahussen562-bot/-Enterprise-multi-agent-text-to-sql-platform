"""FinCore domain adapter retaining the hardened four-agent state machine."""
import re
from agents.intent_router import IntentResult, IntentRouter, IntentType
from agents.orchestrator import CentralController
from agents.reconnaissance import SchemaCard
from core.fincore import FinancialMetricRegistry, ROLE_COLUMNS

SAMPLES = {
    'branch_analyst': ['Show daily account balances', 'Show branch daily flows', 'Show loan delinquency and interest accrual'],
    'compliance_officer': ['Show high-risk cash monitoring', 'Show KYC reviews', 'Show AML compliance cases'],
    'fraud_investigator': ['Show flagged transactions', 'Show card events', 'Show active investigation cases'],
}


class FinCoreIntentRouter:
    def classify(self, question, user_session=None):
        q = question.strip().lower()
        role = getattr(user_session, 'role', '')
        # Preserve the deterministic injection boundary before domain routing.
        legacy = IntentRouter()._semantic_domain_fallback(question)
        if legacy[0] == IntentType.SECURITY_ATTACK:
            return IntentResult(IntentType.SECURITY_ATTACK, 1.0, response_message='Security boundary violation rejected.')
        if not q or legacy[0] == IntentType.HELP:
            return IntentResult(IntentType.HELP, 1.0, response_message='FinCore Enterprise: PostgreSQL, masked views and database-native row security.', sample_queries=SAMPLES.get(role, []))
        concepts = {'bank','balance','balances','account','accounts','cash','ctr','sar','kyc','aml','loan','loans','delinquency',
                    'interest','risk','transaction','transactions','fraud','card','cards','branch','ledger','screening','investigation',
                    'رصيد','أرصدة','حسابات','قروض','فوائد','مخاطر','احتيال'}
        intent = IntentType.DATA_QUERY if set(re.findall(r'\w+', q)) & concepts else IntentType.OUT_OF_SCOPE
        return IntentResult(intent, 1.0, response_message=None if intent==IntentType.DATA_QUERY else 'Outside the FinCore banking closed world.')


class NoRetrieval:
    def retrieve_similar_examples(self, question):
        return []


class FinCoreExplorer:
    def __init__(self, database):
        self.db = database
    def run(self, question, max_tables=5, authorized_tables=None):
        ddls = self.db.get_all_ddls(authorized_tables)
        return SchemaCard(list(ddls), list(ddls.values()), [], {},
            ['PostgreSQL; schema-qualified views; explicit masked columns.',
             'Financial metric registry 1.0.0; never invent definitions, FX values, thresholds or relax empty-result filters.'])


class FinCoreCoder:
    """Deterministic v1 metric catalog; unsupported filters refuse, never broaden.

    No banking request can fall through to the media revenue heuristic. Open-ended
    provider synthesis can later be added behind the same AST/metric contracts.
    """
    def __init__(self, role):
        self.role = role
        self.registry = FinancialMetricRegistry()
    def generate_sql(self, question, schema_card, critique=None, similar_examples=None):
        q = question.strip().lower()
        accepted = {
            'show daily account balances', 'show daily balances', 'show available balances',
            'show loan delinquency and interest accrual', 'show loan performance',
            'show high-risk cash monitoring', 'show cash monitoring', 'show kyc reviews',
            'show risk assessments', 'show aml compliance cases', 'show compliance cases',
            'show screening hits', 'show branch daily flows', 'show flagged transactions',
            'show card events', 'show active investigation cases',
        }
        if q not in accepted:
            return '[GROUNDING_ERROR]'
        # Explicit predicates, dates, amounts or extra entities require approved
        # parameter grounding, not a broad template that ignores the request.
        if re.search(r'\d|\b(where|except|exclude|between|before|after|only|greater|less|customer|customers)\b',q):
            return '[GROUNDING_ERROR]'
        metric = None
        if 'cash' in q or 'ctr' in q:
            metric = 'high_risk_cash'
        elif any(word in q for word in ('loan','delinquency','accrual','interest','قروض','فوائد')):
            metric = 'loan_performance'
        elif any(word in q for word in ('balance','balances','رصيد','أرصدة')):
            metric = 'daily_balance'
        if metric:
            try:
                query = self.registry.query(metric,self.role)
            except PermissionError:
                return '[GROUNDING_ERROR]'
        else:
            mapping = [('kyc','compliance.kyc_reviews'),('risk','compliance.risk_assessments'),
                ('screening','compliance.screening_hits'),('compliance case','compliance.compliance_cases'),
                ('daily flow','branch.daily_flows'),('flagged transaction','fraud.flagged_transactions'),
                ('card event','fraud.card_events'),('investigation case','fraud.investigation_cases')]
            relation = next((table for words,table in mapping if words in q),None)
            if relation not in ROLE_COLUMNS[self.role]:
                return '[GROUNDING_ERROR]'
            query = 'SELECT '+', '.join(ROLE_COLUMNS[self.role][relation])+' FROM '+relation
        from core.sql_validation import parse_single_query, physical_tables
        expression = parse_single_query(query,'postgres')
        if not all(table.sql(dialect='postgres') in schema_card.candidate_tables for table in physical_tables(expression)):
            return '[GROUNDING_ERROR]'
        return query


class FinCoreController(CentralController):
    def __init__(self, database, role):
        super().__init__(db_engine=database,vanna_engine=NoRetrieval())
        self.intent_router = FinCoreIntentRouter()
        self.explorer = FinCoreExplorer(database)
        self.coder = FinCoreCoder(role)
    def execute_pipeline(self,*args,**kwargs):
        with self.db.scope():
            return super().execute_pipeline(*args,**kwargs)
