"""Human-in-the-loop review surface for invoices the agent flagged.

    uv run streamlit run use_cases/automated_invoice_processing/ui.py

Pick a scenario from the sidebar (or upload your own PDF), run the agent,
inspect the live log + extracted fields, decide whether to approve.
"""

from __future__ import annotations

import base64
import json
import logging
import tempfile
from pathlib import Path

import streamlit as st
from sqlalchemy.orm import Session

from data.erp.load_to_dsql import get_engine
from use_cases.automated_invoice_processing.agent.graph import run_on_pdf
from use_cases.automated_invoice_processing.agent.persist import persist_approved_invoice
from use_cases.automated_invoice_processing.agent.schema import AgentVerdict
from use_cases.automated_invoice_processing.agent.signals import (
    FRAUD_SIGNALS,
    WARNING_SIGNALS,
)

_TEST_DIR = Path("use_cases/automated_invoice_processing/test_invoices")


class _ListHandler(logging.Handler):
    def __init__(self, sink: list[str]) -> None:
        super().__init__()
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        self.sink.append(self.format(record))


def _run_with_log_capture(
    pdf_path: str,
) -> tuple[AgentVerdict | None, list[str], str | None]:
    """Run the agent, capturing logs and surfacing exceptions cleanly.

    Returns (verdict, logs, error). On success error is None. On failure
    verdict is None and error holds a one-line human-readable summary;
    the full traceback is in the captured logs.
    """
    logs: list[str] = []
    handler = _ListHandler(logs)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    root = logging.getLogger()
    prior_level = root.level
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    try:
        verdict = run_on_pdf(pdf_path)
        return verdict, logs, None
    except Exception as exc:
        root.exception("agent run failed")
        return None, logs, _summarize_error(exc)
    finally:
        root.removeHandler(handler)
        root.setLevel(prior_level)


def _summarize_error(exc: Exception) -> str:
    """One-line, demo-safe summary of an agent failure."""
    name = type(exc).__name__
    if "Throttl" in name or "TooManyRequests" in name:
        return "Bedrock throttled the request. Wait a few seconds and retry."
    if "AccessDenied" in name or "Unauthorized" in name:
        return "AWS credentials missing or lack permission for Bedrock / DSQL."
    if "Endpoint" in name or "Connection" in name:
        return "Could not reach AWS. Check the VPN / network and retry."
    if name == "ValidationError":
        return "The model returned data that didn't match the expected schema."
    return f"{name}: {exc}"


def _signal_badge(signal: str) -> str:
    if signal in FRAUD_SIGNALS:
        return f":red[**{signal}**]"
    if signal in WARNING_SIGNALS:
        return f":orange[{signal}]"
    return f":blue[{signal}]"


def _render_pdf(pdf_path: Path) -> None:
    b64 = base64.b64encode(pdf_path.read_bytes()).decode("utf-8")
    st.markdown(
        f'<iframe src="data:application/pdf;base64,{b64}" '
        f'width="100%" height="650"></iframe>',
        unsafe_allow_html=True,
    )


def _resolve_input() -> tuple[Path, dict | None]:
    """Sidebar widgets returning (pdf_path, scenario_meta_or_none)."""
    st.sidebar.subheader("Pick a scenario")
    scenarios = sorted(d for d in _TEST_DIR.iterdir() if d.is_dir())
    chosen = st.sidebar.selectbox(
        "Scenario", [d.name for d in scenarios],
        index=None, placeholder="select...",
    )

    st.sidebar.divider()
    st.sidebar.subheader("Or upload your own PDF")
    uploaded = st.sidebar.file_uploader("Invoice PDF", type=["pdf"], label_visibility="collapsed")

    if uploaded is not None:
        # Persist to a temp file so the agent can read by path.
        tmp = Path(tempfile.gettempdir()) / f"uploaded_{uploaded.name}"
        tmp.write_bytes(uploaded.getvalue())
        return tmp, None

    if chosen is None:
        st.info("Pick a test scenario in the sidebar or upload your own PDF to begin.")
        st.stop()

    scenario_dir = _TEST_DIR / chosen
    pdf_path = next(scenario_dir.glob("*.pdf"))
    meta = json.loads(next(scenario_dir.glob("*.json")).read_text())
    return pdf_path, meta


def main() -> None:
    st.set_page_config(page_title="Invoice review", layout="wide")
    st.title("Invoice intake review")
    st.caption(
        "Agent extracts fields from the PDF, validates against the ERP, and "
        "flags discrepancies. You approve, reject, or override."
    )

    pdf_path, meta = _resolve_input()

    if meta is not None:
        st.sidebar.divider()
        st.sidebar.markdown("**Expected outcome**")
        st.sidebar.write(meta["expected_outcome"])
        st.sidebar.markdown("**Expected signals**")
        st.sidebar.write(meta["expected_signals"] or "_none_")

    pdf_col, panel_col = st.columns([1, 1])
    with pdf_col:
        st.subheader("Source PDF")
        _render_pdf(pdf_path)

    state_key = f"verdict::{pdf_path}"
    logs_key = f"logs::{pdf_path}"

    error_key = f"error::{pdf_path}"

    with panel_col:
        if state_key not in st.session_state:
            if st.button("Run agent", type="primary", use_container_width=True):
                with st.spinner("Calling extraction + validation..."):
                    verdict, logs, error = _run_with_log_capture(str(pdf_path))
                st.session_state[state_key] = verdict
                st.session_state[logs_key] = logs
                st.session_state[error_key] = error
                st.rerun()
            return

        if st.session_state.get(error_key) is not None:
            st.error(f"Agent run failed: {st.session_state[error_key]}")
            with st.expander("Agent log", expanded=True):
                st.code("\n".join(st.session_state[logs_key]) or "(no log lines)", language="log")
            if st.button("Retry"):
                for key in (state_key, logs_key, error_key):
                    st.session_state.pop(key, None)
                st.rerun()
            return

        verdict: AgentVerdict = st.session_state[state_key]
        logs: list[str] = st.session_state[logs_key]

        st.subheader("Agent verdict")
        cols = st.columns(2)
        cols[0].metric("Decision", verdict.decision)
        cols[1].metric("Signals", len(verdict.signals))

        if verdict.signals:
            st.markdown("**Signals:**")
            for sig in verdict.signals:
                st.markdown(f"- {_signal_badge(sig)}")
        if verdict.notes:
            with st.expander("Validation notes", expanded=False):
                for note in verdict.notes:
                    st.write(f"- {note}")

        if verdict.extracted is not None:
            with st.expander("Extracted fields", expanded=False):
                st.json(verdict.extracted.model_dump(mode="json"))

        with st.expander("Agent log", expanded=True):
            st.code("\n".join(logs) or "(no log lines)", language="log")

        st.divider()
        st.subheader("Human decision")
        action = st.radio(
            "Override",
            ["accept agent verdict", "approve and persist", "reject"],
            horizontal=True,
        )
        if st.button("Confirm", type="primary"):
            if action == "approve and persist" and verdict.extracted is not None:
                engine = get_engine()
                with Session(engine) as session:
                    inv = persist_approved_invoice(session, verdict.extracted, str(pdf_path))
                st.success(f"Persisted as supplier_invoice id={inv.id}.")
            elif action == "reject":
                st.warning("Rejected (no DB change in this PoC).")
            else:
                st.info(f"Agent verdict kept: {verdict.decision}.")


if __name__ == "__main__":
    main()
