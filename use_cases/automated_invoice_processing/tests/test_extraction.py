"""Tests for the pure helpers in the extraction module.

The Bedrock call is not exercised here; that's the eval suite's job. These
tests cover the boundary that pulls the tool-use payload out of a Converse
response, since that's where shape assumptions can drift if AWS changes
the response format.
"""

import pytest

from use_cases.automated_invoice_processing.agent.extraction import (
    _TOOL_NAME,
    _extract_tool_payload,
)


def _converse_response_with_tool_use(tool_input: dict) -> dict:
    return {
        "output": {
            "message": {
                "content": [
                    {"toolUse": {
                        "toolUseId": "tu_1",
                        "name": _TOOL_NAME,
                        "input": tool_input,
                    }},
                ],
            },
        },
    }


def test_extract_tool_payload_returns_input_when_tool_was_called():
    payload = {"supplier_name": "Acme GmbH", "invoice_number": "R-1"}
    response = _converse_response_with_tool_use(payload)
    assert _extract_tool_payload(response, _TOOL_NAME) == payload


def test_extract_tool_payload_raises_when_model_returned_text_instead():
    response = {
        "output": {
            "message": {
                "content": [{"text": "I refuse to use the tool."}],
            },
        },
    }
    with pytest.raises(ValueError, match="did not call"):
        _extract_tool_payload(response, _TOOL_NAME)


def test_extract_tool_payload_raises_on_wrong_tool_name():
    response = {
        "output": {
            "message": {
                "content": [
                    {"toolUse": {
                        "toolUseId": "tu_1",
                        "name": "some_other_tool",
                        "input": {},
                    }},
                ],
            },
        },
    }
    with pytest.raises(ValueError):
        _extract_tool_payload(response, _TOOL_NAME)
