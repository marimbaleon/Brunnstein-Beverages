"""LangGraph composition: extract -> validate -> decide -> (persist).

Each invocation runs inside an MLflow run for traceability. The DB session
is opened per node intentionally: the agent is stateless across invoices
and we don't want one slow validation to hold a connection open while the
LLM is in-flight on the next.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import TypedDict

import mlflow
from dotenv import load_dotenv
from langgraph.graph import END, StateGraph
from pydantic import ValidationError
from sqlalchemy.orm import Session

from data.erp.load_to_dsql import get_engine
from use_cases.automated_invoice_processing.agent.extraction import extract_invoice
from use_cases.automated_invoice_processing.agent.persist import persist_approved_invoice
from use_cases.automated_invoice_processing.agent.policy import decide_from_signals
from use_cases.automated_invoice_processing.agent.schema import (
    AgentVerdict,
    ExtractedInvoice,
)
from use_cases.automated_invoice_processing.agent.signals import Decision, Signal
from use_cases.automated_invoice_processing.agent.validation import validate_invoice

load_dotenv()
logger = logging.getLogger(__name__)

# Local SQLite-backed MLflow tracking. SQLite unlocks the full feature set
# (model registry, search) over the legacy file store, and stays local-only
# so you don't need a running tracking server for development.
mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "sqlite:///mlflow.db"))
mlflow.set_experiment("automated_invoice_processing")


class AgentState(TypedDict, total=False):
    pdf_path: str
    auto_persist: bool
    extracted: ExtractedInvoice | None
    signals: list[Signal]
    notes: list[str]
    decision: Decision
    persisted_id: str | None
    error: str | None


def _run_extraction(state: AgentState) -> dict:
    pdf_bytes = Path(state["pdf_path"]).read_bytes()
    try:
        extracted = extract_invoice(pdf_bytes)
    except (json.JSONDecodeError, ValueError, ValidationError) as exc:
        logger.exception("extraction failed")
        return {
            "error": f"extraction_failed: {exc}",
            "signals": [Signal.extraction_failed],
        }
    return {"extracted": extracted}


def _run_validation(state: AgentState) -> dict:
    if state.get("extracted") is None:
        return {"signals": state.get("signals", []), "notes": []}
    engine = get_engine()
    with Session(engine) as session:
        signals, notes = validate_invoice(session, state["extracted"])
    return {"signals": signals, "notes": notes}


def _run_decision(state: AgentState) -> dict:
    signals = frozenset(state.get("signals") or [])
    return {"decision": decide_from_signals(signals)}


def _run_persistence(state: AgentState) -> dict:
    engine = get_engine()
    with Session(engine) as session:
        invoice = persist_approved_invoice(
            session, state["extracted"], state["pdf_path"],
        )
        return {"persisted_id": str(invoice.id)}


def _route_after_decision(state: AgentState) -> str:
    if state.get("auto_persist") and state.get("decision") == Decision.approve:
        return "persist"
    return "end"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("extract", _run_extraction)
    graph.add_node("validate", _run_validation)
    graph.add_node("decide", _run_decision)
    graph.add_node("persist", _run_persistence)
    graph.set_entry_point("extract")
    graph.add_edge("extract", "validate")
    graph.add_edge("validate", "decide")
    graph.add_conditional_edges(
        "decide",
        _route_after_decision,
        {"persist": "persist", "end": END},
    )
    graph.add_edge("persist", END)
    return graph.compile()


def run_on_pdf(pdf_path: str, auto_persist: bool = False) -> AgentVerdict:
    app = build_graph()
    pdf_name = Path(pdf_path).stem

    with mlflow.start_run(run_name=pdf_name):
        mlflow.log_params({
            "pdf": pdf_name,
            "auto_persist": auto_persist,
            "model_id": os.environ.get(
                "BEDROCK_MODEL_ID",
                "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
            ),
        })

        start = time.perf_counter()
        result = app.invoke({"pdf_path": pdf_path, "auto_persist": auto_persist})
        elapsed = time.perf_counter() - start

        signals = result.get("signals") or []
        mlflow.log_metric("latency_seconds", elapsed)
        mlflow.log_metric("n_signals", len(signals))
        mlflow.log_params({
            "decision": result["decision"],
            "signals": ",".join(signals) if signals else "none",
            "persisted_id": result.get("persisted_id") or "none",
        })

    return AgentVerdict(
        decision=result["decision"],
        signals=signals,
        notes=result.get("notes", []),
        extracted=result.get("extracted"),
    )
