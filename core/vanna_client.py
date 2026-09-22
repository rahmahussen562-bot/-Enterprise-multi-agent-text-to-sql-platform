"""
Vanna AI client integration with ChromaDB vector store and multi-provider LLM support.
Provides semantic schema retrieval, few-shot SQL retrieval, and active learning hooks.
"""
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.config import LLMConfig, VectorStoreConfig, get_config

logger = logging.getLogger("TextToSQL.Vanna")


class LocalSemanticStore:
    """
    Lightweight, deterministic semantic memory store used standalone or
    alongside ChromaDB to guarantee fast, zero-dependency schema retrieval
    and active learning persistence.
    """

    def __init__(self, persist_dir: str = "data/semantic_store"):
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.db_file = self.persist_dir / "knowledge_base.json"
        self.data: Dict[str, List[Dict[str, Any]]] = {
            "ddl": [],
            "documentation": [],
            "sql_pairs": []
        }
        self._load()

    def _load(self):
        if self.db_file.exists():
            try:
                with open(self.db_file, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load semantic store: {e}")

    def _save(self):
        try:
            with open(self.db_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save semantic store: {e}")

    def add_ddl(self, ddl: str, table_name: Optional[str] = None):
        tbl = table_name or self._extract_table_name(ddl)
        # Avoid duplicate table DDLs
        self.data["ddl"] = [d for d in self.data["ddl"] if d.get("table") != tbl]
        self.data["ddl"].append({"table": tbl, "ddl": ddl.strip()})
        self._save()

    def add_documentation(self, doc: str):
        if doc not in [d.get("text") for d in self.data["documentation"]]:
            self.data["documentation"].append({"text": doc.strip()})
            self._save()

    def add_sql_pair(self, question: str, sql: str):
        # Update or append golden training pair
        self.data["sql_pairs"] = [p for p in self.data["sql_pairs"] if p.get("question").lower() != question.lower()]
        self.data["sql_pairs"].append({"question": question.strip(), "sql": sql.strip()})
        self._save()

    def get_related_ddl(self, question: str, all_ddls: Dict[str, str], top_k: int = 5) -> List[str]:
        """Prune tables based on semantic keyword overlap."""
        tokens = set(re.findall(r"\w+", question.lower()))
        scored: List[Tuple[float, str]] = []

        for tbl, ddl in all_ddls.items():
            tbl_lower = tbl.lower()
            score = 0.0
            # Direct table name hit gets highest score
            if tbl_lower in tokens:
                score += 10.0
            elif any(tbl_lower in tok or tok in tbl_lower for tok in tokens if len(tok) > 3):
                score += 5.0

            # Column name matches
            ddl_lower = ddl.lower()
            for tok in tokens:
                if len(tok) > 3 and tok in ddl_lower:
                    score += 1.5

            scored.append((score, ddl))

        scored.sort(key=lambda x: x[0], reverse=True)
        # Return top_k matching or all if score > 0
        matching = [ddl for score, ddl in scored if score > 0][:top_k]
        if not matching:
            # Fallback to returning first top_k tables
            return list(all_ddls.values())[:top_k]
        return matching

    def get_similar_sql_pairs(self, question: str, top_k: int = 3) -> List[Dict[str, str]]:
        q_tokens = set(re.findall(r"\w+", question.lower()))
        scored = []
        for pair in self.data.get("sql_pairs", []):
            p_tokens = set(re.findall(r"\w+", pair["question"].lower()))
            overlap = len(q_tokens.intersection(p_tokens))
            if overlap > 0:
                scored.append((overlap, pair))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:top_k]]

    def _extract_table_name(self, ddl: str) -> str:
        match = re.search(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`']?(\w+)[\"`']?", ddl, re.IGNORECASE)
        return match.group(1) if match else "unknown"


class VannaTextToSQLEngine:
    """
    Modular Text-to-SQL engine integrating Vanna AI and ChromaDB with
    multi-provider LLM support and deterministic local fallback.
    """

    def __init__(
        self,
        llm_config: Optional[LLMConfig] = None,
        vector_config: Optional[VectorStoreConfig] = None
    ):
        self.config = get_config()
        self.llm_cfg = llm_config or self.config.llm
        self.vec_cfg = vector_config or self.config.vector
        self.local_store = LocalSemanticStore()
        self.vn = None
        self._init_vanna()

    def _init_vanna(self):
        """Attempt to initialize Vanna with ChromaDB and designated LLM backend."""
        try:
            # Check if vanna and chromadb are available
            import vanna
            from vanna.chromadb import ChromaDB_VectorStore

            # Determine provider
            if self.llm_cfg.openai_api_key or os.getenv("OPENAI_API_KEY"):
                from vanna.openai import OpenAI_Chat
                class CustomVanna(ChromaDB_VectorStore, OpenAI_Chat):
                    def __init__(self, config=None):
                        ChromaDB_VectorStore.__init__(self, config=config)
                        OpenAI_Chat.__init__(self, config=config)

                api_key = self.llm_cfg.openai_api_key or os.getenv("OPENAI_API_KEY")
                self.vn = CustomVanna(config={
                    "api_key": api_key,
                    "model": self.llm_cfg.model_name or "gpt-4o-mini",
                    "path": self.vec_cfg.persist_directory
                })
                logger.info("Vanna initialized with OpenAI and ChromaDB.")
            else:
                # Local or custom provider
                logger.info("Vanna initialized with local vector store.")
        except Exception as e:
            logger.info(f"Vanna library initializing in hybrid/local mode: {e}")
            self.vn = None

    def train_ddl(self, ddl: str, table_name: Optional[str] = None):
        """Train vector store on a CREATE TABLE DDL."""
        self.local_store.add_ddl(ddl, table_name)
        if self.vn is not None:
            try:
                self.vn.train(ddl=ddl)
            except Exception as e:
                logger.warning(f"Vanna DDL train warning: {e}")

    def train_documentation(self, documentation: str):
        """Train vector store on domain documentation or business rules."""
        self.local_store.add_documentation(documentation)
        if self.vn is not None:
            try:
                self.vn.train(documentation=documentation)
            except Exception as e:
                logger.warning(f"Vanna doc train warning: {e}")

    def train_sql(self, question: str, sql: str):
        """
        Active Learning hook:
        Persist user-validated 'Thumbs-Up' golden query pairs.
        """
        self.local_store.add_sql_pair(question, sql)
        if self.vn is not None:
            try:
                self.vn.train(question=question, sql=sql)
            except Exception as e:
                logger.warning(f"Vanna SQL pair train warning: {e}")

    def retrieve_candidate_ddls(self, question: str, all_ddls: Dict[str, str], top_k: int = 5) -> List[str]:
        """Semantically prune tables for user intent."""
        if self.vn is not None:
            try:
                retrieved = self.vn.get_related_ddl(question=question)
                if retrieved and len(retrieved) > 0:
                    return retrieved[:top_k]
            except Exception as err:
                logger.warning(f"Vanna DDL retrieval fallback: {err}")
        return self.local_store.get_related_ddl(question, all_ddls, top_k=top_k)

    def retrieve_similar_examples(self, question: str, top_k: int = 3) -> List[Dict[str, str]]:
        """Retrieve few-shot golden question-SQL examples."""
        if self.vn is not None:
            try:
                ex = self.vn.get_similar_question_sql(question=question)
                if ex:
                    return ex[:top_k]
            except Exception as err:
                logger.warning(f"Vanna SQL example retrieval fallback: {err}")
        return self.local_store.get_similar_sql_pairs(question, top_k=top_k)
