"""Canonical v2 schemas; integration must never silently skip validation."""
import json
import os
import math
from pathlib import Path
from functools import lru_cache
from jsonschema import Draft202012Validator


def contracts_directory(explicit=None):
    configured = explicit or os.environ.get("CG4002_CONTRACTS_DIR")
    root = Path(__file__).resolve().parents[2]
    candidates = [Path(configured)] if configured else [
        root.parent / "CG4002-Viz" / "contracts", root / "CG4002-Viz" / "contracts"]
    for path in candidates:
        if all((path / (name + ".schema.json")).is_file() for name in (
                "client-hello", "player-command", "pickup-observation", "punch-observation")):
            return path
    raise RuntimeError("Matching v2 contracts are required; set CG4002_CONTRACTS_DIR or --contracts-dir")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON property")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError("non-finite JSON number")


def decode(raw):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 65536:
        return None
    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_nonfinite)
        pending = [value]
        while pending:
            current = pending.pop()
            if isinstance(current, float) and not math.isfinite(current):
                return None
            if isinstance(current, dict): pending.extend(current.values())
            elif isinstance(current, list): pending.extend(current)
        return value if isinstance(value, dict) else None
    except (ValueError, TypeError, RecursionError):
        return None


@lru_cache(maxsize=32)
def validator(name, directory=None):
    schema = json.loads((contracts_directory(directory) / (name + ".schema.json")).read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)
