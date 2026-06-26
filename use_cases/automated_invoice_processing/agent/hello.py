"""Minimal LangGraph + Bedrock hello world.

A single-node graph that calls Claude Haiku 4.5 via Bedrock and returns the
reply. Sanity check for the LLM plumbing before the extraction node lands.

    uv run python -m use_cases.automated_invoice_processing.agent.hello
    uv run python -m use_cases.automated_invoice_processing.agent.hello "Erkläre Wein in zwei Sätzen."
"""

from __future__ import annotations

import os
import sys
from typing import TypedDict

from dotenv import load_dotenv
from langchain_aws import ChatBedrockConverse
from langgraph.graph import END, StateGraph

load_dotenv()

_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID",
    "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
)
_REGION = os.environ.get("AWS_REGION", "eu-central-1")


class HelloState(TypedDict):
    prompt: str
    reply: str


def _llm() -> ChatBedrockConverse:
    return ChatBedrockConverse(model_id=_MODEL_ID, region_name=_REGION)


def greet(state: HelloState) -> dict:
    response = _llm().invoke(state["prompt"])
    return {"reply": response.content}


def build_graph():
    graph = StateGraph(HelloState)
    graph.add_node("greet", greet)
    graph.set_entry_point("greet")
    graph.add_edge("greet", END)
    return graph.compile()


def main(prompt: str) -> str:
    app = build_graph()
    result = app.invoke({"prompt": prompt, "reply": ""})
    return result["reply"]


if __name__ == "__main__":
    prompt = sys.argv[1] if len(sys.argv) > 1 else "Say hello in German, one short sentence."
    print(main(prompt))
