"""Run the agent on a single PDF and print the verdict.

    uv run python -m use_cases.automated_invoice_processing.agent.run \\
        use_cases/automated_invoice_processing/test_invoices/01_clean_match/tc-001-clean.pdf
"""

from __future__ import annotations

import json
import sys

from use_cases.automated_invoice_processing.agent.graph import run_on_pdf


def main(pdf_path: str) -> None:
    verdict = run_on_pdf(pdf_path)
    print(json.dumps(verdict.model_dump(mode="json"), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m use_cases.automated_invoice_processing.agent.run <pdf_path>", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1])
