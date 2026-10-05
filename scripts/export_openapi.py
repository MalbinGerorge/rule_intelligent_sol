"""Export the API contract from the FastAPI app.

Writes two generated files (never edit them by hand):
  docs/api/openapi.json   the machine-readable contract; the frontend generates
                          its typed client and Zod schemas from this file
  docs/api/README.md      a human-readable endpoint reference

Usage:
  uv run python scripts/export_openapi.py           # regenerate both files
  uv run python scripts/export_openapi.py --check   # CI: fail if either is out of date

Run it whenever you change a route or a request/response schema, and commit
the result together with the code change -- the diff of openapi.json is the
API change your reviewers (and the frontend) need to see.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.api.main import app  # noqa: E402

SPEC_FILE = ROOT / "docs" / "api" / "openapi.json"
REFERENCE_FILE = ROOT / "docs" / "api" / "README.md"
HTTP_METHODS = ("get", "post", "put", "patch", "delete")


def render_spec(spec: dict) -> str:
    return json.dumps(spec, indent=2, ensure_ascii=False) + "\n"


def _schema_name(schema: dict | None) -> str:
    if not schema:
        return "–"
    if "$ref" in schema:
        return f"`{schema['$ref'].rsplit('/', 1)[-1]}`"
    if schema.get("type") == "array":
        return f"list of {_schema_name(schema.get('items'))}"
    if "anyOf" in schema:
        return " or ".join(_schema_name(s) for s in schema["anyOf"])
    return f"`{schema.get('type', 'object')}`"


def _json_schema(container: dict) -> dict | None:
    return container.get("content", {}).get("application/json", {}).get("schema")


def render_reference(spec: dict) -> str:
    lines = [
        "# API reference",
        "",
        "> Generated from the FastAPI app by `scripts/export_openapi.py` — do not edit.",
        "> The machine-readable contract is [`openapi.json`](openapi.json).",
        "",
        f"**{spec['info']['title']}** · version {spec['info']['version']} · OpenAPI {spec['openapi']}",
        "",
    ]
    by_tag: dict[str, list[tuple[str, str, dict]]] = {}
    for path, ops in spec["paths"].items():
        for method in HTTP_METHODS:
            if method in ops:
                tag = (ops[method].get("tags") or ["other"])[0]
                by_tag.setdefault(tag, []).append((method, path, ops[method]))

    for tag, ops in by_tag.items():
        lines += [
            f"## {tag}",
            "",
            "| Method | Path | Parameters | Request body | Response (200) |",
            "|---|---|---|---|---|",
        ]
        for method, path, op in ops:
            params = ", ".join(
                f"`{p['name']}`" + ("" if p.get("required") else "?") + f" ({p['in']})"
                for p in op.get("parameters", [])
            )
            body = (
                _schema_name(_json_schema(op.get("requestBody", {})))
                if "requestBody" in op
                else "–"
            )
            ok = op.get("responses", {}).get("200", {})
            response = (
                _schema_name(_json_schema(ok))
                if _json_schema(ok)
                else ("stream (`text/event-stream`)" if path.endswith("/stream") else "–")
            )
            lines.append(
                f"| `{method.upper()}` | `{path}` | {params or '–'} | {body} | {response} |"
            )
        lines.append("")

    lines += ["## Schemas", ""]
    for name, schema in spec.get("components", {}).get("schemas", {}).items():
        fields = ", ".join(
            f"`{f}`" + ("" if f in schema.get("required", []) else "?")
            for f in schema.get("properties", {})
        )
        lines.append(f"- **`{name}`**: {fields or '–'}")
    return "\n".join(lines) + "\n"


def main() -> int:
    spec = app.openapi()
    outputs = {SPEC_FILE: render_spec(spec), REFERENCE_FILE: render_reference(spec)}

    if "--check" in sys.argv:
        stale = [
            p
            for p, text in outputs.items()
            if not p.exists() or p.read_text(encoding="utf-8") != text
        ]
        for p in stale:
            print(f"OUT OF DATE: {p.relative_to(ROOT)}")
        if stale:
            print(
                "The API changed but the committed contract didn't. Run:\n"
                "  uv run python scripts/export_openapi.py\nand commit the result."
            )
            return 1
        print(f"API contract up to date ({len(spec['paths'])} paths).")
        return 0

    for p, text in outputs.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
