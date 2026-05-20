"""Emit an ER diagram from the SQLAlchemy models.

Run from project root:
    uv run python -m data.generate_erd                    # mermaid to stdout
    uv run python -m data.generate_erd --png docs/erd.png # render via kroki.io

Or from Python:
    from data.generate_erd import generate_erd
    generate_erd(format="markdown")                      # mermaid source as str
    generate_erd(format="png", out_path="docs/erd.png")  # png bytes, also written to disk
"""

from __future__ import annotations

import io
import sys
import urllib.request

from PIL import Image

from data.models import Base


def _build_mermaid() -> str:
    lines = ["erDiagram"]

    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_keys:
            child = table.name.upper()
            parent = fk.column.table.name.upper()
            parent_card = "|o" if fk.parent.nullable else "||"
            lines.append(f"    {parent} {parent_card}--o{{ {child} : \"\"")

    return "\n".join(lines)


def _to_png(mermaid_src: str) -> bytes:
    """Render mermaid source to PNG bytes via the kroki.io web service.

    Kroki returns a transparent PNG. We flatten it onto a white background
    so it reads correctly against dark notebook themes.
    """
    req = urllib.request.Request(
        "https://kroki.io/mermaid/png",
        data=mermaid_src.encode("utf-8"),
        headers={
            "Content-Type": "text/plain",
            "User-Agent": "Mozilla/5.0 brunnstein-erd",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        raw = resp.read()

    img = Image.open(io.BytesIO(raw))
    if img.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", img.size, "white")
        bg.paste(img, mask=img.split()[-1])
        img = bg

    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def generate_erd(format: str = "markdown", out_path: str | None = None) -> str | bytes:
    """Build the ER diagram.

    format="markdown" returns the mermaid source as a string.
    format="png" returns rendered PNG bytes via kroki.io.
    If out_path is given, the result is also written to that path.
    """
    if format not in ("markdown", "png"):
        raise ValueError(f"format must be 'markdown' or 'png', got {format!r}")

    src = _build_mermaid()
    result: str | bytes = _to_png(src) if format == "png" else src

    if out_path is not None:
        mode = "wb" if isinstance(result, bytes) else "w"
        with open(out_path, mode) as f:
            f.write(result)

    return result


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--png":
        out_path = args[1] if len(args) > 1 else "erd.png"
        generate_erd(format="png", out_path=out_path)
        print(f"wrote {out_path}")
    else:
        print(generate_erd())
