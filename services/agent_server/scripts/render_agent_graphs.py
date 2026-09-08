#!/usr/bin/env python3
"""Render LangGraph documentation diagrams for the EO_LLM chat pipeline."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Protocol


SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))


class DrawableGraph(Protocol):
    def draw_mermaid(self) -> str: ...

    def draw_mermaid_png(self) -> bytes: ...


def require_langgraph() -> None:
    if (
        importlib.util.find_spec("langgraph") is None
        or importlib.util.find_spec("langchain_core") is None
    ):
        raise SystemExit(
            "Missing LangGraph/LangChain dependencies. Run this inside the "
            "agent-server environment, or install services/agent_server/requirements.txt."
        )


def build_eo_llm_graph() -> DrawableGraph:
    from eo_llm.graph.builder import build_graph

    compiled = build_graph()
    return compiled.get_graph()


def write_graph(
    graph: DrawableGraph, output_dir: Path, stem: str, *, render_png: bool
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    mermaid = graph.draw_mermaid()
    (output_dir / f"{stem}.mmd").write_text(mermaid, encoding="utf-8")

    if not render_png:
        return

    try:
        png = graph.draw_mermaid_png()
    except Exception as exc:
        print(f"Could not render {stem}.png via LangGraph: {exc}")
        print(f"Mermaid source is still available at {output_dir / f'{stem}.mmd'}")
        return

    (output_dir / f"{stem}.png").write_bytes(png)


def parse_args() -> argparse.Namespace:
    default_output = Path(__file__).resolve().parents[1] / "docs" / "agent_graphs"
    parser = argparse.ArgumentParser(
        description="Render agent_server EO_LLM graph using LangGraph tooling."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_output,
        help=f"Directory for generated graph files. Default: {default_output}",
    )
    parser.add_argument(
        "--no-png",
        action="store_true",
        help="Only write Mermaid source files. Do not call LangGraph PNG renderer.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    require_langgraph()
    write_graph(
        build_eo_llm_graph(),
        args.output_dir,
        "eo_llm_langgraph",
        render_png=not args.no_png,
    )

    print(f"Wrote diagrams to: {args.output_dir}")
    for path in sorted(args.output_dir.iterdir()):
        print(f"- {path}")


if __name__ == "__main__":
    main()
