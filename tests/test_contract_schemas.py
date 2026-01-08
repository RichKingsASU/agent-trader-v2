from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend.contracts.registry import get_schema_path_for_topic


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


class TestContractSchemas(unittest.TestCase):
    def test_schemas_are_valid_json_schema_and_fixtures_validate(self) -> None:
        # Lazy import so this test is the only place that hard-requires jsonschema.
        from jsonschema import Draft202012Validator  # type: ignore

        repo = _repo_root()
        schemas_dir = repo / "contracts" / "schemas"
        fixtures_dir = repo / "contracts" / "fixtures"

        self.assertTrue(schemas_dir.exists(), "contracts/schemas must exist")
        self.assertTrue(fixtures_dir.exists(), "contracts/fixtures must exist")

        topics = ["system-events", "market-ticks", "market-bars-1m", "trade-signals"]

        # Load + validate schemas.
        validators: dict[str, Draft202012Validator] = {}
        for topic in topics:
            schema_path = get_schema_path_for_topic(topic)
            self.assertTrue(schema_path.exists(), f"missing schema for topic: {topic}")
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            validators[topic] = Draft202012Validator(schema)

        # Validate fixtures against their topic schema.
        for topic in topics:
            topic_dir = fixtures_dir / topic
            self.assertTrue(topic_dir.exists(), f"missing fixture dir for topic: {topic}")
            fixtures = sorted(topic_dir.glob("*.json"))
            self.assertTrue(fixtures, f"no fixtures found for topic: {topic}")

            v = validators[topic]
            for fx in fixtures:
                obj = json.loads(fx.read_text(encoding="utf-8"))
                errors = sorted(v.iter_errors(obj), key=lambda e: (list(e.path), str(e.message)))
                if errors:
                    sample = errors[0]
                    self.fail(
                        "fixture failed schema validation\n"
                        f"topic={topic}\n"
                        f"fixture={fx}\n"
                        f"first_error_path={'.'.join(str(p) for p in sample.path)}\n"
                        f"first_error={sample.message}\n"
                    )

