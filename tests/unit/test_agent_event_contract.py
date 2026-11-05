import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

CONTRACT_PATH = (
    Path(__file__).parents[2]
    / "packages"
    / "shared-models"
    / "contracts"
    / "agent"
    / "v1"
    / "event-envelope.schema.json"
)


def test_agent_event_contract_accepts_a_versioned_event() -> None:
    schema = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    event = {
        "contract_version": 1,
        "event_id": "evt-001",
        "agent_id": "agent-001",
        "sequence": 1,
        "event_type": "job.transition",
        "observed_at": "2026-11-04T12:00:00Z",
        "payload": {"state": "printing"},
    }

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(event)
