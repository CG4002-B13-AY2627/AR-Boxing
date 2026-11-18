"""Validate checked-in protocol examples against their JSON Schemas."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_BY_TYPE = {
    "GameEvent": "game-event.schema.json",
    "MatchState": "match-state.schema.json",
}


def main() -> None:
    schemas = {}
    for message_type, schema_name in SCHEMA_BY_TYPE.items():
        schema = json.loads(
            (ROOT / "contracts" / schema_name).read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(schema)
        schemas[message_type] = Draft202012Validator(schema)

    examples = sorted((ROOT / "contracts" / "examples").glob("*.json"))
    if not examples:
        raise RuntimeError("No contract examples were found")

    for example_path in examples:
        example = json.loads(example_path.read_text(encoding="utf-8"))
        message_type = example.get("type")
        if message_type not in schemas:
            raise ValueError(
                f"{example_path.name} has unknown or missing type: {message_type!r}"
            )

        schemas[message_type].validate(example)
        print(f"valid: {example_path.name}")


if __name__ == "__main__":
    main()
