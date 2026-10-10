"""Syntax/duplicate-key checks; executes the JS contained in the actual card YAML."""
import ast
import json
import pathlib
import subprocess
import tempfile

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


class UniqueLoader(yaml.SafeLoader):
    pass


def mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError("Doppelter YAML-Schlüssel: " + str(key))
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
templates = []


def walk(value):
    if isinstance(value, str) and value.strip().startswith("[[["):
        assert value.strip().endswith("]]]")
        templates.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            walk(item)
    elif isinstance(value, list):
        for item in value:
            walk(item)


for path in ROOT.rglob("*.py"):
    ast.parse(path.read_text(), filename=str(path))
for path in ROOT.rglob("*.json"):
    json.loads(path.read_text())
for path in ROOT.rglob("*.yaml"):
    yaml.load(path.read_text(), Loader=UniqueLoader)
card = yaml.load((ROOT / "system_pruefexport_karte.yaml").read_text(), Loader=UniqueLoader)
assert card["type"] == "vertical-stack"
walk(card)
with tempfile.TemporaryDirectory() as temporary:
    data = pathlib.Path(temporary) / "card.json"
    data.write_text(json.dumps({"card": card, "templates": templates}))
    subprocess.run(["node", str(ROOT / "tests/test_card.js"), str(data)], check=True)
print("Python, JSON und YAML inklusive doppelter Schlüssel geprüft;", len(templates), "JavaScript-Templates kompiliert.")
