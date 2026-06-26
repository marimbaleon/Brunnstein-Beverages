"""Vision extraction: PDF bytes -> ExtractedInvoice.

Calls Claude Haiku 4.5 via Bedrock Converse with the PDF attached as a
document. Output is constrained by a tool-use JSON schema so the model
returns structured data directly instead of free-form JSON we have to parse.

The schema is the actual guardrail on tricky fields like the IBAN: a German
IBAN must match `^DE[0-9]{20}$`, and the model has no way to emit a string
of the wrong shape and have it accepted. Earlier free-form versions failed
on exactly that — Haiku occasionally dropped or added a trailing digit and
we caught it post-hoc. Now the model can either return a valid IBAN or null.
"""

from __future__ import annotations

import logging
import os
import re

import boto3

from use_cases.automated_invoice_processing.agent.schema import ExtractedInvoice

logger = logging.getLogger(__name__)

_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID",
    "eu.anthropic.claude-haiku-4-5-20251001-v1:0",
)
_REGION = os.environ.get("AWS_REGION", "eu-central-1")
_PROFILE = os.environ.get("AWS_PROFILE")

_TOOL_NAME = "submit_invoice_extraction"
_IBAN_TOOL_NAME = "submit_iban"
_GERMAN_IBAN_PATTERN = re.compile(r"^DE[0-9]{20}$")

_EXTRACTION_INSTRUCTIONS = """Extract the fields from this German B2B
supplier invoice (Rechnung) and submit them via the
`submit_invoice_extraction` tool.

Conversions:
- German numbers use '.' as thousands separator and ',' as decimal
  (1.234,56 -> 1234.56). The tool expects standard decimals.
- Dates appear as DD.MM.YYYY -> emit YYYY-MM-DD.

IBAN guidance (high-error field):
- A German IBAN is always 'DE' + exactly 20 digits (22 chars total). It is
  printed in groups of 4 with a final group of 2; do not drop or duplicate
  the final group.
- If you cannot read all 22 characters with confidence, emit null. The
  schema will reject a wrong-length value anyway.

Use null for any field that is not present on the invoice."""

_INVOICE_LINE_SCHEMA = {
    "type": "object",
    "properties": {
        "line_number": {"type": "integer"},
        "description": {"type": "string", "description": "the Bezeichnung"},
        "quantity": {"type": "number"},
        "unit_price_net_eur": {
            "type": "number",
            "description": "Einzelpreis netto",
        },
        "line_net_eur": {
            "type": "number",
            "description": "Gesamt netto for this line",
        },
    },
    "required": [
        "line_number", "description", "quantity",
        "unit_price_net_eur", "line_net_eur",
    ],
}

_EXTRACTION_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "supplier_name": {
            "type": "string",
            "description": "company name from the invoice header",
        },
        "supplier_vat_id": {
            "type": ["string", "null"],
            "description": "USt-IdNr if present, else null",
        },
        "invoice_number": {
            "type": "string",
            "description": "Rechnungs-Nr. / Rechnungsnummer",
        },
        "invoice_date": {
            "type": ["string", "null"],
            "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
        },
        "due_date": {
            "type": ["string", "null"],
            "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
        },
        "po_number": {
            "type": ["string", "null"],
            "description": "Bestellnummer / PO reference",
        },
        "payment_iban": {
            "type": ["string", "null"],
            "pattern": "^DE[0-9]{20}$",
            "description": (
                "German IBAN with all spaces stripped. Exactly 22 "
                "characters: 'DE' followed by 20 digits. Emit null if "
                "you cannot read all 22 with confidence."
            ),
        },
        "lines": {
            "type": "array",
            "items": _INVOICE_LINE_SCHEMA,
        },
        "total_net_eur": {"type": "number"},
        "total_vat_eur": {"type": "number"},
        "total_gross_eur": {"type": "number"},
    },
    "required": [
        "supplier_name", "invoice_number", "lines",
        "total_net_eur", "total_vat_eur", "total_gross_eur",
    ],
}


def _bedrock_runtime_client():
    session = boto3.Session(profile_name=_PROFILE, region_name=_REGION)
    return session.client("bedrock-runtime")


def _reject_malformed_german_iban(value: str | None) -> str | None:
    """Belt-and-braces on top of the schema pattern.

    Bedrock applies the JSON-schema `pattern` as a hint to the model rather
    than a hard constraint, so a malformed IBAN can still slip through. We
    null it out here so downstream validation flags `iban_missing` (honest
    failure) instead of `iban_mismatch_full` (false fraud signal).
    """
    if value is None:
        return None
    stripped = "".join(value.split())
    if stripped.upper().startswith("DE") and not _GERMAN_IBAN_PATTERN.fullmatch(stripped):
        logger.warning("rejecting malformed DE IBAN from model: %r", value)
        return None
    return stripped


def _extract_tool_payload(response: dict, expected_tool_name: str) -> dict:
    """Pull the tool_use input from a Converse response, or raise."""
    for block in response["output"]["message"]["content"]:
        if "toolUse" in block and block["toolUse"]["name"] == expected_tool_name:
            return block["toolUse"]["input"]
    raise ValueError(
        f"model did not call {expected_tool_name}; "
        f"content blocks: {[list(b.keys()) for b in response['output']['message']['content']]}"
    )


def extract_invoice(pdf_bytes: bytes) -> ExtractedInvoice:
    """Extract structured fields from an invoice PDF via vision + tool use."""
    logger.info(
        "calling bedrock %s with %d KB pdf",
        _MODEL_ID, len(pdf_bytes) // 1024,
    )
    response = _bedrock_runtime_client().converse(
        modelId=_MODEL_ID,
        messages=[{
            "role": "user",
            "content": [
                {"document": {
                    "format": "pdf",
                    "name": "invoice",
                    "source": {"bytes": pdf_bytes},
                }},
                {"text": _EXTRACTION_INSTRUCTIONS},
            ],
        }],
        toolConfig={
            "tools": [{
                "toolSpec": {
                    "name": _TOOL_NAME,
                    "description": "Submit the extracted invoice fields.",
                    "inputSchema": {"json": _EXTRACTION_TOOL_SCHEMA},
                },
            }],
            "toolChoice": {"tool": {"name": _TOOL_NAME}},
        },
        inferenceConfig={"temperature": 0.0, "maxTokens": 2000},
    )
    usage = response.get("usage", {})
    logger.info(
        "bedrock response: %d input tokens, %d output tokens",
        usage.get("inputTokens", 0), usage.get("outputTokens", 0),
    )

    payload = _extract_tool_payload(response, _TOOL_NAME)
    payload["payment_iban"] = _reject_malformed_german_iban(payload.get("payment_iban"))

    # If the IBAN failed the first pass, retry with a focused prompt that
    # ONLY asks for the IBAN. The narrower task + explicit format hint
    # recovers the digit Haiku drops on the tightly-spaced layouts.
    if payload.get("payment_iban") is None:
        retried = _extract_iban_focused(pdf_bytes)
        if retried is not None:
            payload["payment_iban"] = retried

    logger.info(
        "extracted: supplier=%s po=%s lines=%d iban=%s",
        payload.get("supplier_name"),
        payload.get("po_number"),
        len(payload.get("lines", [])),
        "present" if payload.get("payment_iban") else "null",
    )
    return ExtractedInvoice(**payload)


_IBAN_FOCUSED_INSTRUCTIONS = """Find the German IBAN (Internationale
Bankkontonummer) printed on this invoice and submit it via the
`submit_iban` tool.

Format rules — read carefully, errors here have been the dominant source
of failures:
- A German IBAN is EXACTLY 22 characters: the literal 'DE' followed by
  exactly 20 digits. Not 21, not 23. Count them.
- It is printed in groups of 4 separated by spaces, with a FINAL GROUP OF
  2 digits (not 1). Example: 'DE89 3704 0044 0532 0130 00'. The trailing
  '00' is two digits — include both.
- Strip every space in your output, leaving the 22-character string.
- The IBAN often appears near 'Bankverbindung', 'IBAN:', or in a footer
  line that also contains the BIC. Read ONLY the IBAN, not adjacent
  numbers (BIC, customer number, BLZ).
- If you cannot read all 22 characters with full confidence, submit null.
  A null answer is better than a wrong one — downstream code treats null
  as 'unreadable' and routes to human review."""


_IBAN_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "iban": {
            "type": ["string", "null"],
            "pattern": "^DE[0-9]{20}$",
            "description": (
                "22-character German IBAN with all spaces stripped, "
                "or null if it cannot be read with confidence."
            ),
        },
    },
    "required": ["iban"],
}


def _extract_iban_focused(pdf_bytes: bytes) -> str | None:
    """Second-pass extraction targeting only the IBAN.

    Fired when the main extraction returns a null or malformed IBAN. Uses
    the same model with a narrower prompt — small input, small output, so
    the cost is negligible compared to the first call.
    """
    logger.info("retrying iban extraction with focused prompt")
    response = _bedrock_runtime_client().converse(
        modelId=_MODEL_ID,
        messages=[{
            "role": "user",
            "content": [
                {"document": {
                    "format": "pdf",
                    "name": "invoice",
                    "source": {"bytes": pdf_bytes},
                }},
                {"text": _IBAN_FOCUSED_INSTRUCTIONS},
            ],
        }],
        toolConfig={
            "tools": [{
                "toolSpec": {
                    "name": _IBAN_TOOL_NAME,
                    "description": "Submit the IBAN read from the invoice.",
                    "inputSchema": {"json": _IBAN_TOOL_SCHEMA},
                },
            }],
            "toolChoice": {"tool": {"name": _IBAN_TOOL_NAME}},
        },
        inferenceConfig={"temperature": 0.0, "maxTokens": 200},
    )
    payload = _extract_tool_payload(response, _IBAN_TOOL_NAME)
    cleaned = _reject_malformed_german_iban(payload.get("iban"))
    logger.info("iban second pass: %s", "recovered" if cleaned else "still null")
    return cleaned
