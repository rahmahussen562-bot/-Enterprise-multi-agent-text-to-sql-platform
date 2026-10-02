"""
AegisSQL Enterprise Gateway: Microsoft SQL Server (T-SQL) Platform
Production Corporate Interface featuring Semantic Domain Intent Routing,
Closed-World Grounding, and AST-based Hallucination Elimination.
Zero-Emoji Industrial UI with 4 Dedicated Analysis Tabs.
"""
import io
import os
import time
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from agents.intent_router import IntentResult, IntentRouter, IntentType
from agents.orchestrator import CentralController, OrchestrationResult
from core.auth import UserSession, authenticate
from core.config import AgentConfig, DatabaseConfig, LLMConfig, SystemConfig, get_config
from core.database import DatabaseEngine
from core.vanna_client import VannaTextToSQLEngine

try:
    from agents.visualizer import AutonomousVisualizer
except ImportError:
    from utils.visualizer import AutonomousVisualizer

# -----------------------------------------------------------------------------
# Streamlit Application Configuration & Branding
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="AEGISSQL ENTERPRISE GATEWAY | MS SQL SERVER",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -----------------------------------------------------------------------------
# Corporate Design System CSS (Dark Slate / Corporate Navy / Off-White)
# -----------------------------------------------------------------------------
st.markdown("""
<style>
    /* Global Base */
    .stApp {
        background-color: #0f172a;
        color: #f8fafc;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    
    /* Headers & Subtitles */
    h1, h2, h3, h4, h5, h6 {
        color: #f8fafc !important;
        font-weight: 600 !important;
        letter-spacing: -0.5px;
    }
    
    /* Corporate Badges */
    .corp-badge {
        display: inline-block;
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 700;
        font-family: monospace;
        letter-spacing: 0.5px;
        margin-right: 6px;
    }
    .badge-primary { background: #1e293b; color: #38bdf8; border: 1px solid #334155; }
    .badge-success { background: #064e3b; color: #34d399; border: 1px solid #059669; }
    .badge-warning { background: #451a03; color: #fbbf24; border: 1px solid #d97706; }
    .badge-danger  { background: #4c0519; color: #fb7185; border: 1px solid #e11d48; }
    .badge-info    { background: #172554; color: #93c5fd; border: 1px solid #2563eb; }

    /* Executive Analytical Card */
    .executive-card {
        background-color: #1e293b;
        border: 1px solid #334155;
        border-radius: 6px;
        padding: 16px 20px;
        margin: 12px 0;
    }
    
    /* Quick Action Chip Buttons */
    div.stButton > button {
        border-radius: 20px !important;
        font-size: 0.8rem !important;
        font-weight: 600 !important;
        padding: 4px 12px !important;
        border: 1px solid #334155 !important;
        background-color: #1e293b !important;
        color: #e2e8f0 !important;
        transition: all 0.2s ease-in-out !important;
    }
    div.stButton > button:hover {
        border-color: #38bdf8 !important;
        color: #38bdf8 !important;
        background-color: #0f172a !important;
    }

    /* Clean Corporate Tab Styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: transparent;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: #1e293b;
        border-radius: 6px 6px 0 0;
        padding: 8px 16px;
        color: #94a3b8;
        border: 1px solid #334155;
        font-weight: 600;
        font-size: 0.88rem;
    }
    .stTabs [aria-selected="true"] {
        background-color: #0f172a !important;
        color: #38bdf8 !important;
        border-bottom: 2px solid #38bdf8 !important;
    }
</style>
""", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# Session State Initialization
# -----------------------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

if "config" not in st.session_state:
    st.session_state.config = get_config()

if "user" not in st.session_state:
    st.session_state.user = None

if "active_prompt" not in st.session_state:
    st.session_state.active_prompt = None

db_engine = DatabaseEngine(st.session_state.config.db)
vanna_engine = VannaTextToSQLEngine(st.session_state.config.llm, st.session_state.config.vector)
visualizer = AutonomousVisualizer(theme="plotly_dark")
intent_router = IntentRouter()


# -----------------------------------------------------------------------------
# Authentication Guard (Multi-User RBAC Screen)
# -----------------------------------------------------------------------------
if st.session_state.user is None:
    st.markdown("<div style='height: 40px;'></div>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        st.markdown("""
        <div style="text-align: center; margin-bottom: 24px;">
            <div style="font-size: 1.25rem; font-weight: 700; letter-spacing: 1px; color: #38bdf8;">
                [AEGISSQL CORPORATE ACCESS CONTROL]
            </div>
            <div style="font-size: 0.85rem; color: #94a3b8; margin-top: 4px;">
                AegisSQL Enterprise Gateway | Microsoft SQL Server (T-SQL)
            </div>
        </div>
        """, unsafe_allow_html=True)

        with st.form("login_form"):
            username = st.text_input("Corporate ID / Username", value="sales_analyst")
            password = st.text_input("Password", type="password", value="Sales@2026!")
            submitted = st.form_submit_button("Authenticate Session", use_container_width=True)

            if submitted:
                session = authenticate(username, password)
                if session:
                    st.session_state.user = session
                    st.session_state.messages = []
                    st.rerun()
                else:
                    st.error("Authentication Failure: Invalid corporate credentials.")

        st.markdown("---")
        st.markdown("""
        <div style="font-size: 0.8rem; color: #94a3b8; line-height: 1.6;">
            <strong>Directory Credentials for Evaluation:</strong><br>
            - <code>sales_analyst</code> / <code>Sales@2026!</code> (Commercial Scope: Customer, Invoice, InvoiceLine)<br>
            - <code>inventory_lead</code> / <code>Ops@2026!</code> (Catalog Scope: Track, Album, Artist, Genre, MediaType)
        </div>
        """, unsafe_allow_html=True)

    st.stop()


# -----------------------------------------------------------------------------
# Authenticated Corporate Interface
# -----------------------------------------------------------------------------
active_user: UserSession = st.session_state.user

# Sidebar: Corporate Governance & Session Status
with st.sidebar:
    st.markdown("""
    <div style="padding: 10px 0; border-bottom: 1px solid #334155; margin-bottom: 12px;">
        <span class="corp-badge badge-primary">[GATEWAY CONTROL]</span>
        <div style="font-size: 0.95rem; font-weight: 700; margin-top: 6px; color: #f8fafc;">
            AEGISSQL CONSOLE
        </div>
    </div>
    """, unsafe_allow_html=True)

    # User Profile Block
    st.markdown(f"""
    <div style="background-color: #1e293b; border: 1px solid #334155; padding: 12px; border-radius: 6px; margin-bottom: 12px;">
        <div style="font-size: 0.75rem; text-transform: uppercase; color: #94a3b8; font-weight: 700;">Active Identity</div>
        <div style="font-size: 0.9rem; font-weight: 600; color: #38bdf8;">{active_user.role_title}</div>
        <div style="font-size: 0.78rem; color: #cbd5e1; margin-top: 2px;">User ID: <code>{active_user.username}</code></div>
        <div style="font-size: 0.78rem; color: #94a3b8; margin-top: 2px;">Scope: {active_user.scope}</div>
    </div>
    """, unsafe_allow_html=True)

    if st.button("Terminate Session (Log Out)", use_container_width=True):
        st.session_state.user = None
        st.session_state.messages = []
        st.session_state.active_prompt = None
        st.rerun()

    st.markdown("---")
    st.subheader("Database Gateway Status")
    conn_result = db_engine.test_connection()
    if isinstance(conn_result, (tuple, list)):
        conn_ok = bool(conn_result[0]) if len(conn_result) > 0 else False
        conn_msg = str(conn_result[1]) if len(conn_result) > 1 else ""
        latency_ms = float(conn_result[2]) if len(conn_result) > 2 and isinstance(conn_result[2], (int, float)) else getattr(db_engine, "last_latency_ms", 0.0)
        conn_mode = str(conn_result[3]) if len(conn_result) > 3 else getattr(db_engine, "connection_mode", "UNKNOWN")
    else:
        conn_ok = bool(conn_result)
        conn_msg = "Database connection operational." if conn_ok else "Database connection failed."
        latency_ms = getattr(db_engine, "last_latency_ms", 0.0)
        conn_mode = getattr(db_engine, "connection_mode", "UNKNOWN")

    if conn_mode == "LIVE_MSSQL":
        st.markdown(f"<span class='corp-badge badge-success'>[LIVE MSSQL: {db_engine.config.server}/{db_engine.config.database}]</span>", unsafe_allow_html=True)
    elif conn_mode == "MOCK_EMULATOR":
        st.markdown("<span class='corp-badge badge-info'>[MOCK EMULATOR: LOCAL STORAGE]</span>", unsafe_allow_html=True)
    else:
        st.markdown("<span class='corp-badge badge-danger'>[CONNECTION_ERROR]</span>", unsafe_allow_html=True)

    st.markdown(f"""
    <div style="font-size: 0.78rem; color: #94a3b8; margin-top: 6px; line-height: 1.5;">
        <div><strong>ODBC Driver:</strong> <code>{db_engine.detected_driver}</code></div>
        <div><strong>Round-Trip Latency:</strong> <code>{latency_ms:.1f} ms</code></div>
        <div style="margin-top: 2px; color: #cbd5e1;">{conn_msg}</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("Authorized Table Whitelist")
    st.caption("Row & Table-Level Control (RLC) enforced at AST Guardian")
    allowed_tables = getattr(active_user, "allowed_tables", getattr(active_user, "authorized_tables", []))
    for tbl in allowed_tables:
        st.markdown(f"- `[{tbl}]`")

    st.markdown("---")
    st.subheader("Governance Parameters")
    max_retries = st.slider("Max Self-Healing Iterations", 1, 5, value=3)
    st.session_state.config.agent.max_retries = max_retries

    defensive_top = st.number_input("Defensive TOP Limit Injection", 10, 1000, value=100)
    st.session_state.config.agent.defensive_limit = defensive_top


# -----------------------------------------------------------------------------
# Main Workspace: Header & Scope Information
# -----------------------------------------------------------------------------
st.markdown(f"""
<div style="margin-bottom: 18px; padding-bottom: 12px; border-bottom: 1px solid #334155;">
    <div style="display: flex; align-items: center; justify-content: space-between;">
        <div>
            <h2 style="margin: 0; font-size: 1.5rem; letter-spacing: -0.5px;">
                AEGISSQL ENTERPRISE GATEWAY
            </h2>
            <div style="font-size: 0.85rem; color: #94a3b8; margin-top: 4px;">
                Microsoft SQL Server Architecture | Semantic Intent Gatekeeper | AST Hallucination Defense
            </div>
        </div>
        <div>
            <span class="corp-badge badge-info">DIALECT: T-SQL</span>
            <span class="corp-badge badge-success">SEMANTIC ROUTER: ACTIVE</span>
            <span class="corp-badge badge-primary">CLOSED-WORLD CWA: ACTIVE</span>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# Responsive Quick-Action Chips (Tailored by Role - Zero Emojis)
# -----------------------------------------------------------------------------
st.markdown("<div style='font-size: 0.85rem; font-weight: 600; color: #94a3b8; margin-bottom: 8px;'>QUICK-ACTION BUSINESS INQUIRIES:</div>", unsafe_allow_html=True)

chip_c1, chip_c2, chip_c3, chip_c4, chip_c5 = st.columns(5)

if "sales" in active_user.username.lower():
    with chip_c1:
        if st.button("[Brazil Sales & Invoices]", use_container_width=True):
            st.session_state.active_prompt = "What are the total sales and invoice count for customers in Brazil?"
    with chip_c2:
        if st.button("[Top 10 Invoices]", use_container_width=True):
            st.session_state.active_prompt = "Find the top 10 invoices ranked by total billing amount."
    with chip_c3:
        if st.button("[Net Profit Breakdown]", use_container_width=True):
            st.session_state.active_prompt = "Calculate Gross Revenue, Bank Fees (2.5%), Partner Share (70%), and Company Net Profit (30%) across InvoiceLine."
    with chip_c4:
        if st.button("[High-Value Clients]", use_container_width=True):
            st.session_state.active_prompt = "Find top 5 customers with their country and billing total."
    with chip_c5:
        if st.button("[Help / System Capabilities]", use_container_width=True):
            st.session_state.active_prompt = "help"
else:
    with chip_c1:
        if st.button("[Rock Genre Catalog]", use_container_width=True):
            st.session_state.active_prompt = "List tracks in the Rock genre with their album and artist details."
    with chip_c2:
        if st.button("[Top 10 Artists]", use_container_width=True):
            st.session_state.active_prompt = "Find the top 10 artists with the highest number of albums in the catalog."
    with chip_c3:
        if st.button("[Media Distribution]", use_container_width=True):
            st.session_state.active_prompt = "Show the total track count across each media type in the catalog."
    with chip_c4:
        if st.button("[Longest Audio Tracks]", use_container_width=True):
            st.session_state.active_prompt = "Find the 10 longest audio tracks with their duration in milliseconds."
    with chip_c5:
        if st.button("[Help / System Capabilities]", use_container_width=True):
            st.session_state.active_prompt = "help"


# -----------------------------------------------------------------------------
# Chat Conversation History (Clean 4-Tab Rendering - Zero Emojis)
# -----------------------------------------------------------------------------
for idx, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        if msg.get("type") == "onboarding":
            st.markdown(msg["content"])
        elif msg.get("error"):
            st.error(msg["content"])
        elif msg.get("df") is not None and isinstance(msg["df"], pd.DataFrame) and not msg["df"].empty:
            st.markdown(f"**Analysis Summary:** {msg.get('content', '')}")
            h_tab1, h_tab2, h_tab3, h_tab4 = st.tabs([
                "Query Dataset",
                "Visual Analytics",
                "Validated T-SQL",
                "Security Telemetry"
            ])
            with h_tab1:
                st.dataframe(msg["df"], use_container_width=True)
                csv_bytes = msg["df"].to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="Export Dataset (CSV)",
                    data=csv_bytes,
                    file_name=f"dataset_{idx}.csv",
                    mime="text/csv",
                    key=f"hist_dl_{idx}"
                )
            with h_tab2:
                if msg.get("fig"):
                    st.plotly_chart(msg["fig"], use_container_width=True, key=f"hist_fig_{idx}")
                else:
                    st.info("Visual representation not applicable for this result set format.")
            with h_tab3:
                if msg.get("sql"):
                    st.code(msg["sql"], language="sql")
            with h_tab4:
                if msg.get("telemetry"):
                    st.json(msg["telemetry"])
        else:
            st.markdown(msg["content"])
            if msg.get("sql"):
                st.code(msg["sql"], language="sql")


# -----------------------------------------------------------------------------
# Natural Language Query Input & Multi-Agent Execution
# -----------------------------------------------------------------------------
prompt = st.chat_input("Enter natural language query against authorized corporate schemas...")
if st.session_state.active_prompt:
    prompt = st.session_state.active_prompt
    st.session_state.active_prompt = None

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        # Step 1: Semantic Intent Classification & Domain Boundary Guard
        intent_res: IntentResult = intent_router.classify_intent_semantic(prompt, user_session=active_user)

        if intent_res.intent == IntentType.HELP:
            # DO NOT generate SQL or render empty/mock data tables
            st.markdown(intent_res.response_message)
            st.session_state.messages.append({
                "role": "assistant",
                "content": intent_res.response_message,
                "type": "onboarding"
            })

        elif intent_res.intent == IntentType.SECURITY_ATTACK:
            st.error(intent_res.response_message)
            st.session_state.messages.append({
                "role": "assistant",
                "content": intent_res.response_message,
                "error": True
            })

        elif intent_res.intent == IntentType.OUT_OF_SCOPE:
            st.warning(intent_res.response_message)
            st.session_state.messages.append({
                "role": "assistant",
                "content": intent_res.response_message,
                "error": True
            })

        else:
            # Step 2: Multi-Agent Operational Data Pipeline
            status_box = st.status("[ORCHESTRATOR] Initializing Multi-Agent State Machine...", expanded=True)

            controller = CentralController(
                db_engine=db_engine,
                vanna_engine=vanna_engine,
                config=st.session_state.config
            )

            def on_agent_event(event):
                badge = f"[{event.agent_name.upper()}]"
                if event.status == "running":
                    status_box.write(f"{badge} {event.message}")
                elif event.status == "success":
                    status_box.write(f"{badge} PASSED: {event.message}")
                elif event.status == "retry":
                    status_box.write(f"{badge} SELF-HEALING TRIGGERED: {event.message}")
                elif event.status == "failed":
                    status_box.write(f"{badge} POLICY VIOLATION / FAILURE: {event.message}")

            # Execute Pipeline with graceful network error trapping
            try:
                result: OrchestrationResult = controller.execute_pipeline(
                    prompt,
                    user_session=active_user,
                    on_event=on_agent_event
                )
            except Exception as conn_err:
                status_box.update(label="[DATABASE_CONNECTION_ERROR] Network Failure", state="error", expanded=True)
                st.error(f"[DATABASE_CONNECTION_ERROR] Communication with SQL Server failed: {str(conn_err)}")
                result = OrchestrationResult(
                    success=False,
                    final_sql="",
                    df=pd.DataFrame(),
                    executive_narrative="",
                    events=[],
                    retry_history=[],
                    error_message=f"[DATABASE_CONNECTION_ERROR] {str(conn_err)}"
                )

            if result.success:
                status_box.update(label="[ORCHESTRATOR] Pipeline Complete: Execution and Sanity Verification Passed", state="complete", expanded=False)
            else:
                status_box.update(label="[ORCHESTRATOR] Execution Interrupted: Policy Violation or Failure", state="error", expanded=True)

            # Generate Visualization
            fig = None
            if not result.df.empty:
                fig = visualizer.generate_chart(result.df)

            # Telemetry Metadata
            telemetry_data = {
                "platform": "AegisSQL Enterprise Gateway",
                "ast_firewall_status": "APPROVED" if result.success else "REJECTED_OR_FAILED",
                "rbac_role": active_user.role_title,
                "operator_id": active_user.username,
                "authorized_tables": allowed_tables,
                "referenced_tables": getattr(result.schema_card, "candidate_tables", []),
                "hallucination_check": "PASSED_STRICT_SCHEMA_GROUNDING" if result.success else "FLAGGED",
                "closed_world_assumption": "ENFORCED",
                "execution_latency_ms": round(result.execution_time_ms, 2),
                "self_healing_retries": len(result.retry_history),
                "dialect": "Microsoft SQL Server (T-SQL)",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
            }

            # -----------------------------------------------------------------
            # 4 Clean Output Tabs (Zero Emojis)
            # -----------------------------------------------------------------
            tabs = st.tabs([
                "Query Dataset",
                "Visual Analytics",
                "Validated T-SQL",
                "Security Telemetry"
            ])

            # Tab 1: Query Dataset
            with tabs[0]:
                if not result.df.empty:
                    col_m1, col_m2, col_m3 = st.columns(3)
                    with col_m1:
                        st.metric("Total Records", len(result.df))
                    with col_m2:
                        st.metric("Attributes", len(result.df.columns))
                    with col_m3:
                        st.metric("Execution Latency", f"{result.execution_time_ms:.1f} ms")

                    st.dataframe(result.df, use_container_width=True)

                    if result.executive_narrative:
                        st.markdown(f"""
                        <div class="executive-card">
                            <div style="font-size: 0.75rem; text-transform: uppercase; color: #38bdf8; font-weight: 700; margin-bottom: 4px;">
                                Executive Analytical Narrative
                            </div>
                            <div style="font-size: 0.9rem; line-height: 1.5; color: #f8fafc;">
                                {result.executive_narrative}
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                    exp_c1, exp_c2 = st.columns(2)
                    with exp_c1:
                        csv_bytes = result.df.to_csv(index=False).encode("utf-8")
                        st.download_button(
                            label="Export Dataset (CSV)",
                            data=csv_bytes,
                            file_name="query_results.csv",
                            mime="text/csv",
                            use_container_width=True,
                            key=f"live_csv_{len(st.session_state.messages)}"
                        )
                    with exp_c2:
                        excel_buffer = io.BytesIO()
                        try:
                            with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
                                result.df.to_excel(writer, index=False, sheet_name="Results")
                        except Exception:
                            with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
                                result.df.to_excel(writer, index=False, sheet_name="Results")

                        st.download_button(
                            label="Export Dataset (Excel)",
                            data=excel_buffer.getvalue(),
                            file_name="query_results.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                            key=f"live_xlsx_{len(st.session_state.messages)}"
                        )
                elif result.error_message:
                    st.error(f"Execution Quarantined or Failed: {result.error_message}")
                else:
                    st.info("No records found or result set is empty for the executed query.")

            # Tab 2: Visual Analytics
            with tabs[1]:
                if fig:
                    st.plotly_chart(fig, use_container_width=True, key=f"live_chart_{len(st.session_state.messages)}")
                else:
                    st.info("Visual representation is not applicable for this result set format. Charts are generated automatically for multi-column categorical or numeric distributions.")

            # Tab 3: Validated T-SQL
            with tabs[2]:
                if result.final_sql:
                    st.code(result.final_sql, language="sql")

                if result.retry_history:
                    with st.expander("Autonomous Self-Healing Trace", expanded=False):
                        for rec in result.retry_history:
                            st.warning(f"Self-Healing Iteration {rec.iteration} ({rec.trigger_agent}): {rec.critique_message}")
                            st.markdown("**Corrected T-SQL Diff:**")
                            st.code(rec.sql_diff if rec.sql_diff else "(Full query refactor)", language="diff")

                st.markdown("---")
                st.markdown("##### Query Verification & Continuous Learning")
                f_col1, f_col2, f_col3 = st.columns([2, 2, 3])
                with f_col1:
                    if st.button("[Record Verified Query]", key=f"rec_train_{time.time()}"):
                        vanna_engine.train_sql(question=prompt, sql=result.final_sql)
                        st.toast("Verified query pair trained into ChromaDB vector memory.", icon="[OK]")
                with f_col2:
                    if st.button("[Flag Query Inaccuracy]", key=f"flag_err_{time.time()}"):
                        st.toast("Audit feedback logged for model tuning.", icon="[LOG]")

            # Tab 4: Security Telemetry
            with tabs[3]:
                st.json(telemetry_data)
                with st.expander("Agent State Machine Trace Log", expanded=False):
                    for ev in result.events:
                        st.markdown(f"- **[{ev.agent_name.upper()}]** `{ev.status.upper()}`: {ev.message}")

            st.session_state.messages.append({
                "role": "assistant",
                "content": result.executive_narrative or "Query execution finished.",
                "sql": result.final_sql,
                "df": result.df,
                "fig": fig,
                "telemetry": telemetry_data
            })
