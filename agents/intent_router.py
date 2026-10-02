"""
Intent Classification & Conversational Grounding Router.
Distinguishes between operational data queries, platform onboarding/capability inquiries,
out-of-scope conversational deviations, and security prompt injection attempts.
"""
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional

from core.auth import UserSession


class IntentType(str, Enum):
    DATA_QUERY = "DATA_QUERY"
    CAPABILITY_HELP = "CAPABILITY_HELP"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    SECURITY_REJECTION = "SECURITY_REJECTION"


@dataclass
class IntentResult:
    intent: IntentType
    confidence: float = 1.0
    response_message: Optional[str] = None
    sample_queries: List[str] = field(default_factory=list)


# -----------------------------------------------------------------------------
# Role-Specific High-Impact Business Inquiries
# -----------------------------------------------------------------------------
ROLE_SAMPLE_QUERIES = {
    "sales_analyst": [
        "What are the total sales and invoice count for customers in Brazil?",
        "Find the top 10 invoices ranked by total billing amount.",
        "Calculate Gross Revenue, Bank Fees (2.5%), Partner Share (70%), and Company Net Profit (30%) across InvoiceLine."
    ],
    "inventory_lead": [
        "List tracks in the Rock genre with their album and artist details.",
        "Find the top 10 artists with the highest number of albums in the catalog.",
        "Show the total track count across each media type in the catalog."
    ]
}

ROLE_SAMPLE_QUERIES_AR = {
    "sales_analyst": [
        "ما هو إجمالي المبيعات وعدد الفواتير للعملاء في البرازيل؟",
        "ما هي أعلى 10 فواتير من حيث إجمالي قيمة الفاتورة؟",
        "احسب إجمالي الإيرادات ورسوم البنك (2.5%) وحصة الشركاء (70%) وصافي ربح الشركة (30%)."
    ],
    "inventory_lead": [
        "عرض المقاطع الموسيقية في تصنيف Rock مع اسم الألبوم والفنان.",
        "أفضل 10 فنانين حسب عدد الألبومات في الكتالوج.",
        "توزيع إجمالي عدد المقاطع الموسيقية حسب نوع الوسائط (Media Type)."
    ]
}


class IntentRouter:
    """Classifies user queries to enforce strict operational boundaries and capability guidance."""

    # Security Violation / Injection Patterns
    INJECTION_PATTERNS = [
        r"ignore\s+(previous|all)\s+instructions",
        r"bypass\s+(rules|guardrails|security)",
        r"system\s+override",
        r"disregard\s+(guardrails|rules)",
        r"\b(dan|jailbreak|developer\s+mode)\b",
        r"\b(drop|truncate|alter)\s+table\b",
        r"\b(xp_cmdshell|sp_executesql)\b",
        r"\bdelete\s+from\b",
        r"\binsert\s+into\b",
        r"\bupdate\s+\w+\s+set\b",
        r"expose\s+(system\s+prompt|metadata|schema\s+keys)",
        r"show\s+(hidden\s+prompt|internal\s+instructions)"
    ]

    # Capability / Help / Onboarding Patterns
    HELP_PATTERNS = [
        r"\b(help|assist|guidance|guide|onboarding|manual)\b",
        r"\bwhat\s+can\s+you\s+do\b",
        r"\bhow\s+can\s+you\s+help\b",
        r"\bwho\s+are\s+you\b",
        r"\bwhat\s+are\s+your\s+capabilities\b",
        r"\b(capabilities|features|instructions|start)\b",
        r"^(hi|hello|hey|greetings|welcome)\b",
        r"ازاي\s+تساعدني",
        r"كيف\s+تساعدني",
        r"ماذا\s+يمكنك\s+ان\s+تفعل",
        r"ما\s+هي\s+قدراتك",
        r"تقدر\s+تعمل\s+ايه",
        r"عرفني\s+بالنظام",
        r"من\s+أنت",
        r"مين\s+انت",
        r"^(مساعدة|شرح|تعليمات|البداية|دليل)$",
        r"^(أهلاً|مرحبا|اهلا|سلام|مساء الخير|صباح الخير)$"
    ]

    # Out-of-Scope Patterns (unrelated to SQL, business data, or database queries)
    OUT_OF_SCOPE_PATTERNS = [
        r"\b(weather|temperature|forecast)\b",
        r"\b(who\s+won\s+the\s+world\s+cup|football|soccer|champions\s+league)\b",
        r"\b(recipe|cook|baking|cake|ingredients)\b",
        r"\b(joke|funny|poem|story|creative\s+writing)\b",
        r"\bwrite\s+(a\s+python|a\s+javascript|a\s+java|a\s+c\+\+|html|css)\s+(game|app|script|code)\b",
        r"\b(translate\s+to\s+french|translate\s+to\s+spanish)\b",
        r"\b(capital\s+of\s+\w+|president\s+of\s+\w+)\b",
        r"الطقس|درجة\s+الحرارة|كأس\s+العالم|وصفة|طبخ|نكتة|قصة"
    ]

    # Business Entity / Database Indicators that qualify as DATA_QUERY
    DATA_ENTITY_INDICATORS = [
        r"\b(select|from|where|group\s+by|order\s+by|join|count|sum|avg|max|min)\b",
        r"\b(customer|customers|invoice|invoices|invoiceline|billing|sales|revenue|profit)\b",
        r"\b(track|tracks|album|albums|artist|artists|genre|genres|mediatype|media\s+type)\b",
        r"\b(brazil|usa|germany|canada|rock|jazz|metal|latin)\b",
        r"\b(unitprice|quantity|total|fee|bank|share|royalty)\b",
        r"مبيعات|فواتير|فواتيرنا|عملاء|عميل|إيراد|أرباح|أرباح|مقاطع|ألبومات|فنان|موسيقى|أنواع"
    ]

    def classify(self, query: str, user_session: Optional[UserSession] = None) -> IntentResult:
        """Classify user query into operational intent category with structured response."""
        clean_query = query.strip()
        lower_query = clean_query.lower()

        # Step 1: Security Quarantine & Prompt Injection Defense
        for pat in self.INJECTION_PATTERNS:
            if re.search(pat, lower_query, re.IGNORECASE):
                return IntentResult(
                    intent=IntentType.SECURITY_REJECTION,
                    confidence=1.0,
                    response_message="[SECURITY_QUARANTINE_REJECTION]: The prompt attempted an unauthorized system override or security boundary violation."
                )

        # Step 2: Capability / Help / Onboarding Intent
        # If the query contains explicit data entities and is a question asking for data, prefer DATA_QUERY
        has_data_indicator = any(re.search(pat, lower_query, re.IGNORECASE) for pat in self.DATA_ENTITY_INDICATORS)
        is_help_pattern = any(re.search(pat, lower_query, re.IGNORECASE) for pat in self.HELP_PATTERNS)

        if is_help_pattern and not (has_data_indicator and len(clean_query.split()) > 4):
            onboarding_msg, samples = self.generate_onboarding_response(user_session)
            return IntentResult(
                intent=IntentType.CAPABILITY_HELP,
                confidence=0.98,
                response_message=onboarding_msg,
                sample_queries=samples
            )

        # Step 3: Out-of-Scope Non-Database Questions
        for pat in self.OUT_OF_SCOPE_PATTERNS:
            if re.search(pat, lower_query, re.IGNORECASE) and not has_data_indicator:
                return IntentResult(
                    intent=IntentType.OUT_OF_SCOPE,
                    confidence=0.95,
                    response_message="[OUT_OF_SCOPE_REFUSAL]: This inquiry is strictly outside the database operational boundaries."
                )

        # Step 4: Default to Operational Data Query
        return IntentResult(
            intent=IntentType.DATA_QUERY,
            confidence=0.90,
            response_message=None
        )

    def generate_onboarding_response(self, user_session: Optional[UserSession] = None) -> tuple[str, List[str]]:
        """Generate a bilingual (Arabic & English) onboarding response tailored to the active user's role."""
        username = user_session.username if user_session else "sales_analyst"
        role_title = user_session.role_title if user_session else "Commercial Intelligence Lead"
        scope = user_session.scope if user_session else "Commercial & Transactional Intelligence"
        allowed_tables = getattr(user_session, "allowed_tables", getattr(user_session, "authorized_tables", ["Customer", "Invoice", "InvoiceLine"]))

        role_key = "inventory_lead" if "inventory" in username.lower() or "catalog" in username.lower() else "sales_analyst"
        samples_en = ROLE_SAMPLE_QUERIES.get(role_key, ROLE_SAMPLE_QUERIES["sales_analyst"])
        samples_ar = ROLE_SAMPLE_QUERIES_AR.get(role_key, ROLE_SAMPLE_QUERIES_AR["sales_analyst"])

        tables_badge = ", ".join([f"`[{t}]`" for t in allowed_tables])

        msg = f"""### 🏢 دليل المنصة والقدرات التشغيلية | Enterprise Platform Capabilities

أهلاً بك في **منصة الاستعلام الذكي للمؤسسات (Enterprise Multi-Agent Text-to-SQL Platform)**.
تم تصميم النظام لترجمة الاستفسارات التحليلية إلى استعلامات Microsoft SQL Server (T-SQL) معتمدة، مشفرة، وآمنة وفق حوكمة البيانات المعتمدة.

Welcome to the **Enterprise Multi-Agent Text-to-SQL Platform**. This platform transforms your business inquiries into verified, secure Microsoft SQL Server (T-SQL) queries under strict deterministic data governance.

---
#### 👤 ملف المشغل وحوكمة الصلاحيات | Active Session Governance
- **الدور الوظيفي / Active Role:** `{role_title}` (`{username}`)
- **نطاق العمل / Scope:** {scope}
- **الجداول المصرح بها / Authorized Whitelist:** {tables_badge}
- **قواعد البيانات / Database Dialect:** `Microsoft SQL Server (T-SQL)`
- **محرك الأمان / Security Firewall:** `AST Injection Quarantine + Schema Grounding Active`

---
#### 💡 استفسارات مقترحة عالية التأثير | High-Impact Business Inquiries
يمكنك الضغط على الأزرار السريعة أو نسخ أحد الاستفسارات المصرح بها أدناه مباشرة:

1. **{samples_en[0]}**
   *(بالعربية: {samples_ar[0]})*

2. **{samples_en[1]}**
   *(بالعربية: {samples_ar[1]})*

3. **{samples_en[2]}**
   *(بالعربية: {samples_ar[2]})*

---
*ملاحظة: يمكنك إدخال استفساراتك باللغة العربية أو الإنجليزية، وسيتولى الوكلاء الأربعة فحص المخطط، توليد الكود، والتحقق الرياضي والأمني قبل التنفيذ.*
"""
        return msg, samples_en


IntentClassifier = IntentRouter
