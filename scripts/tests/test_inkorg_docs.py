"""Kontrollera att inkorgens dokumenterade kökontrakt går att slå upp och läsa som JSON."""

import json
from pathlib import Path


def test_queue_contract():
    doc = (Path(__file__).resolve().parents[2] / "docs/inkorg.md").read_text()
    for endpoint in ("POST /api/v2/inkorg/{id}/slapp", "POST /api/v2/inkorg/angra", "GET /api/v2/inkorg/tilldela"):
        assert f"### `{endpoint}`" in doc
    queue = doc.split("### `GET /api/v2/inkorg`", 1)[1].split("\n### ", 1)[0]
    for param in ("mode", "order", "herd_prefix"):
        assert f"| `{param}=" in queue
    example = json.loads(queue.split("```json", 1)[1].split("```", 1)[0])
    assert {"mode_counts", "next_untaken"} <= example.keys()
    assert "subject" in example["items"][0]
    for event in ("slappt", "angrad"):
        assert f"| `{event}` |" in doc
