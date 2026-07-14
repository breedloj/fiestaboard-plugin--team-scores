"""Validate demo templates against declared plugin variables."""

import json
import re
from pathlib import Path

import pytest


MANIFEST_PATH = Path(__file__).resolve().parents[1] / "manifest.json"


def _manifest():
    return json.loads(MANIFEST_PATH.read_text())


def _cases():
    return [(name, demo["template"]) for name, demo in _manifest()["demo"].items()]


@pytest.mark.parametrize("device_type,template", _cases())
def test_demo_variables_are_declared(device_type, template):
    manifest = _manifest()
    plugin_id = manifest["id"]
    variables = manifest["variables"]
    simple = {f"{plugin_id}.{name}" for name in variables.get("simple", {})}
    arrays = variables.get("arrays", {})
    valid = set(simple)
    for array_name, spec in arrays.items():
        for index in range(10):
            for field in spec.get("item_fields", []):
                valid.add(f"{plugin_id}.{array_name}.{index}.{field}")

    references = {
        match.group(1).strip()
        for line in template
        for match in re.finditer(r"\{\{([^}]+)\}\}", line)
    }
    assert references <= valid, f"{device_type} uses undeclared variables: {references - valid}"
