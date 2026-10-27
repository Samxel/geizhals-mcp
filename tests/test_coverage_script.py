"""The badge script reads the homepage's "Zahlen & Fakten" block."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "update_coverage.py"
spec = importlib.util.spec_from_file_location("update_coverage", SCRIPT)
update_coverage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update_coverage)

FACTS = """
<div class="facts">
  <span class="facts__value">3.839.927</span> <span class="facts__label">gelistete Artikel</span>
  <span class="facts__value">244.714.254</span> <span class="facts__label">Preise</span>
  <span class="facts__value">371.460</span> <span class="facts__label">aktive H&auml;ndler</span>
</div>
"""


def test_parse_counts_reads_all_three_facts():
    assert update_coverage.parse_counts(FACTS) == {
        "products": 3839927, "prices": 244714254, "merchants": 371460}


def test_parse_counts_fails_loudly_on_a_changed_page():
    with pytest.raises(SystemExit, match="could not parse"):
        update_coverage.parse_counts("<html>Sichere Verbindung wird überprüft</html>")


def test_human_shortens_the_counts():
    assert [update_coverage.human(n) for n in (3839927, 371460, 999)] == ["3.8M", "371k", "999"]
