"""
Generates docs/graph_schema_reference.md from live Neo4j introspection
(Layer 1 of the AI-layer grounding design). Run manually whenever the
graph schema changes — a new _load_*_edges function added to loader.py,
a relationship renamed, etc. Not called on every agent request.

Usage:
    uv run python scripts/generate_schema_reference.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.graph.client import get_driver, close_driver
from app.graph.schema_introspection import generate_schema_reference


def main() -> None:
    driver = get_driver()
    content = generate_schema_reference(driver)
    close_driver()

    out_path = Path(__file__).resolve().parent.parent / "docs" / "graph_schema_reference.md"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(content, encoding="utf-8")

    print(f"Written to {out_path}")
    print(f"({len(content)} characters)")


if __name__ == "__main__":
    main()