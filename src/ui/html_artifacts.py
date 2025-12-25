from __future__ import annotations

import re
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components


def extract_all_html_filenames(text: str):
    return re.findall(r"([\w\-]+\.html)", text or "")


def display_html_file(
    filename: str,
    *,
    maps_dir: Path,
    project_root: Path,
    height: int = 450,
    width: int | None = None,
) -> None:
    path = Path(filename)
    candidates: list[Path] = []

    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.extend(
            [
                maps_dir / path.name,
                project_root / path.name,
                Path.cwd() / path.name,
            ]
        )

    for candidate in candidates:
        if candidate.exists():
            with candidate.open("r", encoding="utf-8") as f:
                html = f.read()
            components.html(html, height=height, width=width)
            return

    st.warning(f"⚠️ HTML file `{filename}` does not exist.")


def display_all_html_from_text(text: str, *, maps_dir: Path, project_root: Path) -> None:
    found = extract_all_html_filenames(text)
    html_files: set[str] = set()
    for root in [maps_dir, project_root, Path.cwd()]:
        if root.exists():
            html_files.update([p.name for p in root.glob("*.html")])

    for name in found:
        if name in html_files:
            st.write(f"### Displaying `{name}`:")
            display_html_file(name, maps_dir=maps_dir, project_root=project_root)
        else:
            st.warning(f"⚠️ HTML file `{name}` not found.")
