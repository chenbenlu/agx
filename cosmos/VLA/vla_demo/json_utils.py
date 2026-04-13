import json
import re
from typing import Any


def dumps_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def loads_json(raw: str, context: str = "payload") -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON for {context}: {exc}") from exc


def extract_json_object(raw: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", raw):
        try:
            payload, _ = decoder.raw_decode(raw[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise ValueError("No JSON object found in model output")
