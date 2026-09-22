"""
Agent 1: Schema & Data Reconnaissance Agent (The Explorer)
Implements semantic schema pruning, entity extraction, and active value grounding
(SELECT DISTINCT TOP probes) for Microsoft SQL Server (T-SQL).
Strictly adheres to authorized table boundaries (RBAC/RLC).
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from core.database import DatabaseEngine
from core.vanna_client import VannaTextToSQLEngine

logger = logging.getLogger("TextToSQL.Explorer")


@dataclass
class SchemaCard:
    """Hyper-condensed schema card enriched with real sample values and foreign keys."""
    candidate_tables: List[str]
    pruned_ddls: List[str]
    foreign_keys: List[Dict[str, str]]
    grounded_values: Dict[str, List[str]]
    business_context: List[str] = field(default_factory=list)

    def to_prompt_context(self) -> str:
        """Render an optimized schema context for the T-SQL Coder."""
        sections = []

        # 1. Candidate Table DDLs
        sections.append("### DATABASE SCHEMAS (Authorized Candidate Tables Only):")
        for ddl in self.pruned_ddls:
            sections.append(ddl.strip())

        # 2. Foreign Key Relationships
        if self.foreign_keys:
            sections.append("\n### FOREIGN KEY RELATIONSHIPS:")
            for fk in self.foreign_keys:
                sections.append(
                    f"- [{fk['from_table']}].[{fk['from_column']}] -> [{fk['to_table']}].[{fk['to_column']}]"
                )

        # 3. Grounded Categorical & Entity Values
        if self.grounded_values:
            sections.append("\n### GROUNDED ENTITY & CATEGORICAL VALUES (Exact DB Casing & Format):")
            for col_ref, vals in self.grounded_values.items():
                val_str = ", ".join(f"'{v}'" for v in vals)
                sections.append(f"- {col_ref}: [{val_str}]")

        # 4. Domain & Business Metrics
        if self.business_context:
            sections.append("\n### DOMAIN BUSINESS RULES & T-SQL CONVENTIONS:")
            for rule in self.business_context:
                sections.append(f"- {rule}")

        return "\n".join(sections)


class ReconnaissanceAgent:
    """Agent 1: Schema & Data Reconnaissance Agent (The Explorer) for T-SQL."""

    def __init__(self, db_engine: DatabaseEngine, vanna_engine: VannaTextToSQLEngine):
        self.db = db_engine
        self.vanna = vanna_engine

    def run(
        self,
        question: str,
        max_tables: int = 5,
        authorized_tables: Optional[List[str]] = None
    ) -> SchemaCard:
        """
        Execute active reconnaissance:
        1. Retrieve candidate DDLs filtered strictly by authorized tables (RBAC).
        2. Extract proper nouns, entities, filters from question.
        3. Probe database using T-SQL TOP queries for exact matching stored categorical values.
        4. Assemble condensed SchemaCard.
        """
        # Step 1: Semantic Schema Pruning within Authorized Scope
        all_ddls = self.db.get_all_ddls(authorized_tables=authorized_tables)
        candidate_ddls = self.vanna.retrieve_candidate_ddls(question, all_ddls, top_k=max_tables)

        candidate_tables: List[str] = []
        for ddl in candidate_ddls:
            match = re.search(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`\[]?(\w+)[\"`\]]?", ddl, re.IGNORECASE)
            if match:
                candidate_tables.append(match.group(1))

        if not candidate_tables:
            candidate_tables = self.db.get_table_names(authorized_tables=authorized_tables)[:max_tables]
            candidate_ddls = [self.db.get_table_schema_ddl(t) for t in candidate_tables]

        # Ensure no unauthorized table entered candidate set
        if authorized_tables is not None:
            auth_set = {t.lower() for t in authorized_tables}
            candidate_tables = [t for t in candidate_tables if t.lower() in auth_set]
            candidate_ddls = [self.db.get_table_schema_ddl(t) for t in candidate_tables]

        # Step 2: Foreign Key extraction for candidate tables
        all_fks = self.db.get_foreign_keys(authorized_tables=authorized_tables)
        relevant_fks = [
            fk for fk in all_fks
            if fk["from_table"] in candidate_tables and fk["to_table"] in candidate_tables
        ]

        # Step 3: Entity Extraction and Active Value Grounding
        grounded_values = self._ground_entity_values(question, candidate_tables)

        # Step 4: Assemble SchemaCard
        business_rules = [
            "Target Dialect: Microsoft SQL Server (T-SQL).",
            "Use square brackets for identifiers: [Table].[Column].",
            "Use TOP N for row limiting (do NOT use LIMIT).",
            "Prefer Common Table Expressions (WITH [...] AS (...)) for maintainability.",
            "Explicitly join tables with proper ON conditions. Never omit join predicates."
        ]

        return SchemaCard(
            candidate_tables=candidate_tables,
            pruned_ddls=candidate_ddls,
            foreign_keys=relevant_fks,
            grounded_values=grounded_values,
            business_context=business_rules
        )

    def _ground_entity_values(self, question: str, candidate_tables: List[str]) -> Dict[str, List[str]]:
        """
        Parse keywords and proper nouns from query, then probe candidate tables
        using T-SQL SELECT DISTINCT TOP probes.
        """
        grounded: Dict[str, List[str]] = {}

        quoted = re.findall(r"['\"]([^'\"]+)['\"]", question)
        capitalized = [w.strip() for w in re.findall(r"\b[A-Z][a-zA-Z0-9_\-\./]+\b", question)]
        stopwords = {
            "what", "which", "where", "show", "find", "give", "list", "total", "count",
            "average", "from", "with", "have", "been", "that", "this", "many", "much",
            "table", "data", "database", "query", "select", "order", "group", "order",
            "each", "every", "highest", "lowest", "more", "less", "than", "between"
        }
        words = [
            w for w in re.findall(r"\b[a-zA-Z]{3,}\b", question)
            if w.lower() not in stopwords
        ]

        probe_tokens: Set[str] = set(quoted + capitalized + words)

        for table in candidate_tables:
            try:
                cols_info = self.db.get_table_columns_info(table)
            except Exception as e:
                logger.warning(f"Could not fetch columns for {table}: {e}")
                continue

            text_cols = [
                c["name"] for c in cols_info
                if any(t in c["type"] for t in ["CHAR", "TEXT", "CLOB", "VARCHAR", "NVARCHAR", "STRING"])
                or "NAME" in c["name"].upper()
                or "STATUS" in c["name"].upper()
                or "COUNTRY" in c["name"].upper()
                or "CITY" in c["name"].upper()
                or "STATE" in c["name"].upper()
                or "TITLE" in c["name"].upper()
                or "TYPE" in c["name"].upper()
                or "GENRE" in c["name"].upper()
                or "CATEGORY" in c["name"].upper()
            ]

            for col in text_cols:
                col_key = f"[{table}].[{col}]"
                matched_values = []

                for token in list(probe_tokens)[:6]:
                    try:
                        vals = self.db.probe_distinct_values(table, col, limit=3, pattern=token)
                        for v in vals:
                            if v not in matched_values:
                                matched_values.append(v)
                    except Exception:
                        pass

                if not matched_values and any(k in col.upper() for k in ["STATUS", "TYPE", "GENRE", "COUNTRY", "CATEGORY"]):
                    try:
                        sample_vals = self.db.probe_distinct_values(table, col, limit=3, pattern=None)
                        matched_values.extend(sample_vals)
                    except Exception:
                        pass

                if matched_values:
                    grounded[col_key] = matched_values[:5]

        return grounded
