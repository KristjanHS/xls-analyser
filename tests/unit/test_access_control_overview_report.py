from __future__ import annotations

from pathlib import Path

from weasyprint import HTML

from backend.access_control_overview_report import _relative_url_fetcher, _rewrite_links_to_relative


def test_pdf_links_are_relative(tmp_path: Path) -> None:
    base_dir = tmp_path
    html = '<a href="team_floor_wing.xlsx">xlsx</a>'

    doc = HTML(string=html, base_url=str(base_dir), url_fetcher=_relative_url_fetcher(base_dir)).render()
    kind, target, *_ = doc.pages[0].links[0]
    assert kind == "external"
    assert target.startswith("file://")

    _rewrite_links_to_relative(doc, base_dir)

    kind, target, *_ = doc.pages[0].links[0]
    assert target == "team_floor_wing.xlsx"
