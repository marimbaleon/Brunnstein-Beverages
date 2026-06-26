"""Emit an ER diagram from the SQLAlchemy models.

Run from project root:
    uv run python -m data.erp.generate_erd                    # mermaid to stdout
    uv run python -m data.erp.generate_erd --png docs/erd.png # render via kroki.io
    uv run python -m data.erp.generate_erd --svg docs/erd.svg # same but svg

Or from Python:
    from data.erp.generate_erd import generate_erd
    generate_erd(format="markdown")                       # mermaid source as str
    generate_erd(format="png", out_path="docs/erd.png")   # png bytes, also written to disk
    generate_erd(format="svg", out_path="docs/erd.svg")   # svg source as str
"""

from __future__ import annotations

import io
import sys
import urllib.request

from PIL import Image

from data.erp.models import Base


def _build_mermaid() -> str:
    lines = ["erDiagram"]

    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_keys:
            child = table.name.upper()
            parent = fk.column.table.name.upper()
            parent_card = "|o" if fk.parent.nullable else "||"
            lines.append(f"    {parent} {parent_card}--o{{ {child} : \"\"")

    return "\n".join(lines)


_KROKI_TIMEOUT_SECONDS = 15


def _kroki(mermaid_src: str, fmt: str) -> bytes:
    req = urllib.request.Request(
        f"https://kroki.io/mermaid/{fmt}",
        data=mermaid_src.encode("utf-8"),
        headers={
            "Content-Type": "text/plain",
            "User-Agent": "Mozilla/5.0 brunnstein-erd",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_KROKI_TIMEOUT_SECONDS) as resp:
        return resp.read()


def _to_png(mermaid_src: str) -> bytes:
    """Render mermaid source to PNG bytes, flattened onto white.

    Kroki returns a transparent PNG. We flatten it so the diagram reads
    against any theme.
    """
    raw = _kroki(mermaid_src, "png")
    img = Image.open(io.BytesIO(raw))
    if img.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", img.size, "white")
        bg.paste(img, mask=img.split()[-1])
        img = bg

    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _to_svg(mermaid_src: str) -> str:
    return _kroki(mermaid_src, "svg").decode("utf-8")


def generate_erd(output_format: str = "markdown", out_path: str | None = None) -> str | bytes:
    """Build the ER diagram.

    output_format="markdown" returns the mermaid source as a string.
    output_format="png" returns rendered PNG bytes via kroki.io.
    output_format="svg" returns rendered SVG source as a string.
    If out_path is given, the result is also written to that path.
    """
    if output_format not in ("markdown", "png", "svg"):
        raise ValueError(
            f"output_format must be 'markdown', 'png', or 'svg', got {output_format!r}"
        )

    src = _build_mermaid()
    result: str | bytes
    if output_format == "png":
        result = _to_png(src)
    elif output_format == "svg":
        result = _to_svg(src)
    else:
        result = src

    if out_path is not None:
        mode = "wb" if isinstance(result, bytes) else "w"
        with open(out_path, mode) as f:
            f.write(result)

    return result


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] in ("--png", "--svg"):
        fmt = args[0][2:]
        out_path = args[1] if len(args) > 1 else f"erd.{fmt}"
        generate_erd(output_format=fmt, out_path=out_path)
        print(f"wrote {out_path}")
    else:
        print(generate_erd())
