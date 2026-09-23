import json
import tempfile
import unittest
from pathlib import Path

from lib import findings_schema_validator as fsv

TOOLS_ROOT = Path(__file__).resolve().parent.parent


def _load_schema(name: str) -> dict:
    return json.loads((TOOLS_ROOT / "schemas" / name).read_text(encoding="utf-8"))


VALID_FINDING = {
    "id": "F-01",
    "lens": "money-flow",
    "claim": "el refund es idempotente",
    "attack": "doble reintento con timeout",
    "failure_scenario": "dos cargos por un solo refund",
    "evidence": ["PaymentAttemptStoreTest.kt:42"],
    "verdict": "OK",
    "epistemic": "Probado",
}

VALID_FINDINGS_DOC = {
    "round": 1,
    "role": "adversary",
    "findings": [VALID_FINDING],
    "summary": "todo verde",
}


class ListTypeTests(unittest.TestCase):
    """'round' and 'summary' come out in different shapes depending on the real
    round (round: an iteration integer OR a label like 'metodologia-v3'; summary:
    prose OR a tally {"ok":2,"matiz":4,...}): the schema declares "type" as a
    list of alternatives, and this proves the validator accepts both,
    while still rejecting a third shape."""

    def test_string_alternative_matches(self):
        errors = fsv.validate_value("metodologia-v3", {"type": ["string", "integer"]}, "$.round")
        self.assertEqual(errors, [])

    def test_integer_alternative_matches(self):
        errors = fsv.validate_value(3, {"type": ["string", "integer"]}, "$.round")
        self.assertEqual(errors, [])

    def test_neither_alternative_matches_is_an_error(self):
        # negative control: neither string nor integer -> must fail all the same.
        errors = fsv.validate_value(3.5, {"type": ["string", "integer"]}, "$.round")
        self.assertEqual(len(errors), 1)

    def test_object_alternative_still_validates_nested_shape(self):
        schema = {"type": ["string", "object"]}
        self.assertEqual(fsv.validate_value({"ok": 2}, schema, "$.summary"), [])
        self.assertEqual(fsv.validate_value("todo verde", schema, "$.summary"), [])


class RealMethodologyDocsTests(unittest.TestCase):
    """Real files other agents write live: they are skipped without
    failing if they do not exist yet (they may not have been written
    by the time this runs), but if they exist they must validate clean
    against the schema this same module declares."""

    BASE = Path.home() / "architecture-audit-example" / "ai-harness" / "metodologia-v3"

    def test_001_challenger_validates_as_findings(self):
        path = self.BASE / "001-challenger.json"
        if not path.exists():
            self.skipTest(f"{path} does not exist yet")
        doc = json.loads(path.read_text(encoding="utf-8"))
        result = fsv.validate(doc, _load_schema("findings.schema.json"))
        self.assertIn(result["verdict"], {"PASS", "INCOMPLETE"})

    def test_002_blind_spots_validates_as_blindspots(self):
        path = self.BASE / "002-blind-spot-adversary.json"
        if not path.exists():
            self.skipTest(f"{path} does not exist yet")
        doc = json.loads(path.read_text(encoding="utf-8"))
        result = fsv.validate(doc, _load_schema("blindspots.schema.json"))
        self.assertIn(result["verdict"], {"PASS", "INCOMPLETE"})


class TypeCheckTests(unittest.TestCase):
    def test_string_type_ok(self):
        self.assertEqual(fsv.validate_value("x", {"type": "string"}, "$"), [])

    def test_wrong_type_is_an_error(self):
        errors = fsv.validate_value(123, {"type": "string"}, "$.field")
        self.assertEqual(len(errors), 1)
        self.assertIn("$.field", errors[0])

    def test_bool_is_not_an_integer(self):
        # negative control: bool is a subclass of int in Python; it must not slip through.
        errors = fsv.validate_value(True, {"type": "integer"}, "$.round")
        self.assertEqual(len(errors), 1)

    def test_bool_is_a_valid_boolean(self):
        self.assertEqual(fsv.validate_value(True, {"type": "boolean"}, "$"), [])

    def test_number_accepts_int_and_float(self):
        self.assertEqual(fsv.validate_value(3, {"type": "number"}, "$"), [])
        self.assertEqual(fsv.validate_value(3.5, {"type": "number"}, "$"), [])


class RequiredAndEnumTests(unittest.TestCase):
    def test_missing_required_field_is_an_error(self):
        schema = {"type": "object", "required": ["a", "b"], "properties": {}}
        errors = fsv.validate_value({"a": 1}, schema, "$")
        self.assertEqual(len(errors), 1)
        self.assertIn("'b'", errors[0])

    def test_enum_violation_is_an_error(self):
        schema = {"type": "string", "enum": ["OK", "MATIZ", "ROTO"]}
        errors = fsv.validate_value("MAYBE", schema, "$.verdict")
        self.assertEqual(len(errors), 1)

    def test_enum_valid_value_passes(self):
        schema = {"type": "string", "enum": ["OK", "MATIZ", "ROTO"]}
        self.assertEqual(fsv.validate_value("ROTO", schema, "$.verdict"), [])


class ArrayAndNestedObjectTests(unittest.TestCase):
    def test_array_of_objects_validates_each_item(self):
        schema = _load_schema("findings.schema.json")
        doc = dict(VALID_FINDINGS_DOC)
        doc["findings"] = [VALID_FINDING, {**VALID_FINDING, "verdict": "NOPE"}]
        result = fsv.validate(doc, schema)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("findings[1].verdict" in e for e in result["errors"]))

    def test_clean_findings_doc_passes(self):
        result = fsv.validate(VALID_FINDINGS_DOC, _load_schema("findings.schema.json"))
        self.assertEqual(result, {"verdict": "PASS", "errors": []})


class TruncatedIncompleteTests(unittest.TestCase):
    def test_truncated_valid_doc_is_incomplete_not_pass(self):
        doc = dict(VALID_FINDINGS_DOC)
        doc["truncated"] = True
        doc["not_covered"] = ["lens: race-condition sin revisar"]
        result = fsv.validate(doc, _load_schema("findings.schema.json"))
        self.assertEqual(result["verdict"], "INCOMPLETE")
        self.assertEqual(result["errors"], [])

    def test_truncated_invalid_doc_is_still_fail_not_incomplete(self):
        # negative control: truncated does not rescue a broken document.
        doc = dict(VALID_FINDINGS_DOC)
        doc["truncated"] = True
        del doc["summary"]
        result = fsv.validate(doc, _load_schema("findings.schema.json"))
        self.assertEqual(result["verdict"], "FAIL")

    def test_untruncated_doc_is_plain_pass(self):
        result = fsv.validate(VALID_FINDINGS_DOC, _load_schema("findings.schema.json"))
        self.assertEqual(result["verdict"], "PASS")

    def test_blindspots_truncated_is_incomplete(self):
        blind_spot = {
            "id": "BS-01",
            "what_nobody_looks_at": "el reintento de MBWay",
            "why_it_matters": "puede duplicar el cobro",
            "where_it_should_live": "MBWayComunicationRepository",
            "state": "ABIERTO CON DUEÑO",
            "proposed_owner": "payments-team",
            "epistemic": "Inferido",
        }
        doc = {"round": 2, "role": "critic", "blind_spots": [blind_spot], "summary": "ok", "truncated": True}
        result = fsv.validate(doc, _load_schema("blindspots.schema.json"))
        self.assertEqual(result["verdict"], "INCOMPLETE")

    def test_schema_without_truncated_property_ignores_the_flag(self):
        # brief.schema.json does not declare 'truncated' in its properties: if a
        # document carries it anyway, it must not trigger INCOMPLETE.
        schema = _load_schema("brief.schema.json")
        doc = {
            "ROLE": "proposer", "OBJECTIVE": "x", "INPUTS": [], "CONSTRAINTS": [],
            "OUTPUT": "x", "STOP": "x", "BUDGET": {"max_context_tokens": 1, "max_tool_calls": 1},
            "EVIDENCE": "x", "truncated": True,
        }
        result = fsv.validate(doc, schema)
        self.assertEqual(result["verdict"], "PASS")


class OtherRealSchemasTests(unittest.TestCase):
    def test_verdict_schema_valid_document(self):
        doc = {
            "round": 3, "role": "judge",
            "rulings": [{"finding_id": "F-01", "ruling": "CONFIRMED", "evidence": ["x.kt:1"], "epistemic": "Medido"}],
        }
        result = fsv.validate(doc, _load_schema("verdict.schema.json"))
        self.assertEqual(result["verdict"], "PASS")

    def test_verdict_schema_rejects_wrong_role(self):
        doc = {"round": 3, "role": "adversary", "rulings": []}
        result = fsv.validate(doc, _load_schema("verdict.schema.json"))
        self.assertEqual(result["verdict"], "FAIL")

    def test_claims_schema_valid_document(self):
        doc = {"claims": [{
            "id": "C-01", "statement": "domain no importa Android",
            "assumption": "el audit ARCH-001 es correcto", "files": ["domain/.../Configuration.kt"],
            "evidence_needed": "grep de imports android.*", "epistemic": "Asumido",
        }]}
        result = fsv.validate(doc, _load_schema("claims.schema.json"))
        self.assertEqual(result["verdict"], "PASS")

    def test_brief_schema_valid_document(self):
        doc = {
            "ROLE": "proposer", "OBJECTIVE": "entregar P1", "INPUTS": ["README.md"],
            "CONSTRAINTS": ["Python 3.11 stdlib"], "OUTPUT": "JSON final",
            "STOP": "tests verdes", "BUDGET": {"max_context_tokens": 100000, "max_tool_calls": 200},
            "EVIDENCE": "logs de ejecución",
        }
        result = fsv.validate(doc, _load_schema("brief.schema.json"))
        self.assertEqual(result["verdict"], "PASS")

    def test_brief_schema_missing_budget_subfield_fails(self):
        doc = {
            "ROLE": "proposer", "OBJECTIVE": "x", "INPUTS": [], "CONSTRAINTS": [],
            "OUTPUT": "x", "STOP": "x", "BUDGET": {"max_context_tokens": 1},
            "EVIDENCE": "x",
        }
        result = fsv.validate(doc, _load_schema("brief.schema.json"))
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(any("max_tool_calls" in e for e in result["errors"]))

    def test_handoff_schema_valid_document(self):
        doc = {
            "seq": 1, "from_role": "proposer", "to_role": "adversary",
            "artifact_path": "out/x/deps.json", "repo_sha": "abc123", "tools_sha": "def456",
            "summary": "P1 listo", "residual_risks": ["cobertura parcial de dep_boundaries"],
        }
        result = fsv.validate(doc, _load_schema("handoff.schema.json"))
        self.assertEqual(result["verdict"], "PASS")


class DeterminismTests(unittest.TestCase):
    def test_repeated_validation_is_byte_identical(self):
        schema = _load_schema("findings.schema.json")
        first = fsv.validate(VALID_FINDINGS_DOC, schema)
        second = fsv.validate(VALID_FINDINGS_DOC, schema)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))


class MainCliTests(unittest.TestCase):
    def test_exits_zero_on_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc_path = Path(tmp) / "doc.json"
            doc_path.write_text(json.dumps(VALID_FINDINGS_DOC), encoding="utf-8")
            code = fsv.main([str(doc_path), "--schema", str(TOOLS_ROOT / "schemas" / "findings.schema.json")])
            self.assertEqual(code, 0)

    def test_exits_one_on_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc_path = Path(tmp) / "doc.json"
            doc_path.write_text(json.dumps({"round": 1}), encoding="utf-8")
            code = fsv.main([str(doc_path), "--schema", str(TOOLS_ROOT / "schemas" / "findings.schema.json")])
            self.assertEqual(code, 1)

    def test_exits_zero_on_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = dict(VALID_FINDINGS_DOC)
            doc["truncated"] = True
            doc_path = Path(tmp) / "doc.json"
            doc_path.write_text(json.dumps(doc), encoding="utf-8")
            code = fsv.main([str(doc_path), "--schema", str(TOOLS_ROOT / "schemas" / "findings.schema.json")])
            # negative control: INCOMPLETE must never block the pipeline like FAIL
            self.assertEqual(code, 0)


class AdditionalPropertiesTests(unittest.TestCase):
    """The MCP tools' input schemas close the object with
    additionalProperties: false, so a misspelled flag fails on the
    client and never reaches the script. The agents' output schemas do not
    declare it and keep accepting extra keys."""

    STRICT = {"type": "object", "required": ["repo"], "properties": {"repo": {"type": "string"}},
              "additionalProperties": False}

    def test_declared_keys_only_passes(self):
        self.assertEqual(fsv.validate_value({"repo": "/r"}, self.STRICT, "$"), [])

    def test_unknown_key_is_an_error(self):
        errors = fsv.validate_value({"repo": "/r", "rpeo": "typo"}, self.STRICT, "$")
        self.assertEqual(errors, ["$: undeclared field 'rpeo'"])

    def test_null_type_alternative(self):
        schema = {"type": ["string", "null"]}
        self.assertEqual(fsv.validate_value(None, schema, "$.x"), [])
        self.assertEqual(fsv.validate_value("s", schema, "$.x"), [])
        # negative control: an integer is neither string nor null
        self.assertEqual(len(fsv.validate_value(3, schema, "$.x")), 1)

    def test_open_schema_still_accepts_extra_keys(self):
        # negative control: with no additionalProperties, the extra key is not an error
        open_schema = {"type": "object", "properties": {"repo": {"type": "string"}}}
        self.assertEqual(fsv.validate_value({"repo": "/r", "extra": 1}, open_schema, "$"), [])


if __name__ == "__main__":
    unittest.main()
