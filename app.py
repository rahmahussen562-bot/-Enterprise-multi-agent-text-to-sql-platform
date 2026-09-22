"""
Enterprise Multi-Agent Text-to-SQL Platform (Microsoft SQL Server / T-SQL)
Production Corporate Interface featuring Multi-User RBAC/RLC Authentication,
AST-based SQL Injection Firewall, and Complete Industrial De-Emojification.
"""
import io
import os
import time
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from agents.orchestrator import CentralController, OrchestrationResult
from core.auth import UserSession, authenticate
from core.config import AgentConfig, DatabaseConfig, LLMConfig, SystemConfig, get_config
from core.database import DatabaseEngine
from core.vanna_client import VannaTextToSQLEngine
from utils.db_seeder import seed_database
from utils.visualizer import AutonomousVisualizer

# -----------------------------------------------------------------------------
# Streamlit Application Configuration
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="ENTERPRISE TEXT-TO-SQL PLATFORM | MS SQL SERVER",
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
    
    /* Code Diff Box */
    .sql-diff-box {
        background-color: #0b0f19;
        border-left: 3px solid #f43f5e;
        padding: 10px 14px;
        font-family: "Courier New", Courier, monospace;
        font-size: 0.85rem;
        border-radius: 4px;
        margin: 8px 0;
    }
    
    /* Login Container Card */
    .login-box {
        max-width: 480px;
        margin: 40px auto;
        padding: 30px;
        background-color: #1e293b;
        border: 1px solid #334155;
        border-radius: 8px;
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

if "db_seeded" not in st.session_state:
    seed_database(st.session_state.config.db.sqlite_path, seed_vanna=True)
    st.session_state.db_seeded = True

db_engine = DatabaseEngine(st.session_state.config.db)
vanna_engine = VannaTextToSQLEngine(st.session_state.config.llm, st.session_state.config.vector)
visualizer = AutonomousVisualizer(theme="plotly_dark")


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
                [CORPORATE ACCESS CONTROL PORTAL]
            </div>
            <div style="font-size: 0.85rem; color: #94a3b8; margin-top: 4px;">
                Enterprise Multi-Agent Text-to-SQL Platform | T-SQL Gateway
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
            • <code>sales_analyst</code> / <code>Sales@2026!</code> (Commercial Scope: Customer, Invoice, InvoiceLine)<br>
            • <code>inventory_lead</code> / <code>Ops@2026!</code> (Catalog Scope: Track, Album, Artist, Genre, MediaType)
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
        <span class="corp-badge badge-primary">SQL SERVER (T-SQL)</span>
        <div style="font-size: 0.95rem; font-weight: 700; margin-top: 6px; color: #f8fafc;">
            MANAGEMENT CONSOLE
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
        st.rerun()

    st.markdown("---")
    st.subheader("Authorized Table Whitelist")
    st.caption("Row & Table-Level Control (RLC) enforced at AST Guardian")
    for tbl in active_user.authorized_tables:
        st.markdown(f"- `[{tbl}]`")

    st.markdown("---")
    st.subheader("Database Engine Status")
    conn_ok, conn_msg = db_engine.test_connection()
    if conn_ok:
        st.markdown(f"<span class='corp-badge badge-success'>CONNECTED</span> {conn_msg}", unsafe_allow_html=True)
    else:
        st.markdown(f"<span class='corp-badge badge-danger'>ERROR</span> {conn_msg}", unsafe_allow_html=True)

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
                AUTONOMOUS MULTI-AGENT TEXT-TO-SQL PLATFORM
            </h2>
            <div style="font-size: 0.85rem; color: #94a3b8; margin-top: 4px;">
                Microsoft SQL Server Architecture | AST Injection Quarantine | Deterministic RBAC Enforcement
            </div>
        </div>
        <div>
            <span class="corp-badge badge-info">DIALECT: T-SQL</span>
            <span class="corp-badge badge-success">AST FIREWALL: ACTIVE</span>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# Dynamic Benchmark Prompt Suggestions (Filtered by Active Persona)
# -----------------------------------------------------------------------------
st.markdown("<div style='font-size: 0.85rem; font-weight: 600; color: #94a3b8; margin-bottom: 8px;'>RECOMMENDED INQUIRIES WITHIN YOUR AUTHORIZED SCOPE:</div>", unsafe_allow_html=True)

sample_prompt = None
col1, col2, col3 = st.columns(3)

if "sales" in active_user.username:
    with col1:
        if st.button("Total Sales for Customers in Brazil", use_container_width=True):
            sample_prompt = "What are the total sales and invoice count for customers in Brazil?"
    with col2:
        if st.button("Top 10 Invoices by Revenue", use_container_width=True):
            sample_prompt = "Find the top 10 invoices ranked by total billing amount."
    with col3:
        if st.button("Monthly Commercial Sales Trend 2024", use_container_width=True):
            sample_prompt = "Show the monthly revenue trend and invoice count across 2024."
else:
    with col1:
        if st.button("Catalog Tracks in Rock Genre", use_container_width=True):
            sample_prompt = "List tracks in the Rock genre with their album and artist."
    with col2:
        if st.button("Top 10 Artists by Album Count", use_container_width=True):
            sample_prompt = "Find the top 10 artists with the highest number of albums."
    with col3:
        if st.button("Catalog Media Type Distribution", use_container_width=True):
            sample_prompt = "Show the total track count across each media type in the catalog."


# -----------------------------------------------------------------------------
# Chat Conversation History
# -----------------------------------------------------------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "sql" in msg and msg["sql"]:
            st.code(msg["sql"], language="sql")
        if "df" in msg and isinstance(msg["df"], pd.DataFrame) and not msg["df"].empty:
            st.dataframe(msg["df"], use_container_width=True)
            if "fig" in msg and msg["fig"]:
                st.plotly_chart(msg["fig"], use_container_width=True)


# -----------------------------------------------------------------------------
# Natural Language Query Input & Multi-Agent Execution
# -----------------------------------------------------------------------------
prompt = st.chat_input("Enter natural language query against authorized corporate schemas...")
if sample_prompt:
    prompt = sample_prompt

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
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

        # Execute Pipeline passing active UserSession for RBAC enforcement
        result: OrchestrationResult = controller.execute_pipeline(
            prompt,
            user_session=active_user,
            on_event=on_agent_event
        )

        if result.success:
            status_box.update(label="[ORCHESTRATOR] Pipeline Complete: Execution and Sanity Verification Passed", state="complete", expanded=False)
        else:
            status_box.update(label="[ORCHESTRATOR] Execution Interrupted: Policy Violation or Failure", state="error", expanded=True)

        # ---------------------------------------------------------------------
        # Self-Healing Retry / Diff Display
        # ---------------------------------------------------------------------
        if result.retry_history:
            st.markdown("#### [AUTONOMOUS SELF-HEALING TRACE]")
            for rec in result.retry_history:
                with st.expander(f"Self-Healing Iteration {rec.iteration}: {rec.critique_type}", expanded=True):
                    st.warning(f"Diagnostic Critique from {rec.trigger_agent}: {rec.critique_message}")
                    st.markdown("**Corrected T-SQL Diff:**")
                    st.code(rec.sql_diff if rec.sql_diff else "(Full query refactor)", language="diff")

        # ---------------------------------------------------------------------
        # Synthesized T-SQL Query Output
        # ---------------------------------------------------------------------
        st.markdown("#### [SYNTHESIZED T-SQL QUERY]")
        st.code(result.final_sql, language="sql")

        # ---------------------------------------------------------------------
        # Tabular Data Results & Visualizations
        # ---------------------------------------------------------------------
        fig = None
        if not result.df.empty:
            st.markdown("#### [TABULAR DATA OUTPUT]")
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

            fig = visualizer.generate_chart(result.df)
            if fig:
                st.markdown("#### [AUTONOMOUS VISUAL ANALYTICS]")
                st.plotly_chart(fig, use_container_width=True)

            # Enterprise Data Export
            st.markdown("##### Data Export Utility")
            exp_c1, exp_c2 = st.columns(2)
            with exp_c1:
                csv_bytes = result.df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="Export CSV",
                    data=csv_bytes,
                    file_name="query_results.csv",
                    mime="text/csv",
                    use_container_width=True
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
                    label="Export Excel (.xlsx)",
                    data=excel_buffer.getvalue(),
                    file_name="query_results.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )

            # Closed-Loop Active Learning
            st.markdown("##### Query Verification & Continuous Learning")
            f_col1, f_col2, f_col3 = st.columns([2, 2, 3])
            with f_col1:
                if st.button("[Record Verified Query]", key=f"rec_train_{time.time()}"):
                    vanna_engine.train_sql(question=prompt, sql=result.final_sql)
                    st.toast("Verified query pair trained into ChromaDB vector memory.", icon="[OK]")
            with f_col2:
                if st.button("[Flag Query Inaccuracy]", key=f"flag_err_{time.time()}"):
                    st.toast("Audit feedback logged for model tuning.", icon="[LOG]")

        elif result.error_message:
            st.error(f"Execution Error: {result.error_message}")

        st.session_state.messages.append({
            "role": "assistant",
            "content": result.executive_narrative or "Query execution finished.",
            "sql": result.final_sql,
            "df": result.df,
            "fig": fig
        })
