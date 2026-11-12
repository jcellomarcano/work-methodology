"""AGENTS.md: artifacts are in English. The Spanish card labels, epistemic
tags and verdicts stay accepted as aliases by the machine checks
(test_english_labels.py); they are never the wording a role, a skill, a
template or a schema comment uses. One test per surface, with the alias
path as the negative control.

Out of scope on purpose: language data the kit lints (config/output-lint*.json)
and the alias lists a schema documents as accepted input (enum values,
`aliases`, `allowed_values_for_na`, `section_heading`, `value_format`)."""
import json
import re
import unittest
from pathlib import Path


TOOLS = Path(__file__).resolve().parent.parent
KIT = TOOLS.parent
CARD_TEMPLATE = TOOLS / "config" / "change-card.template.md"

SPANISH_LABELS = re.compile(
    r"Medido|Probado|Inferido|Asumido|Desconocido|\bROTO\b|\bMATIZ\b|\bCERRADO\b|\bABIERTO\b|\bCONTENIDO\b"
    r"|Por qu[eé]\b|Para qu[eé]\b|Qu[eé] arriesga|Cu[aá]ndo|C[oó]mo\b|Hasta d[oó]nde|Invariante\b|sin ticket"
    r"|Ficha de cambio")
SPANISH_PROSE = re.compile(
    r"\b(del|que|qué|para|antes|está|están|además|nombre|salida|rutas|recibo|herramientas|patrones|contrato"
    r"|lista ordenada|ej\.)\b", re.IGNORECASE)
# Schema keys that hold prose for a reader, never an accepted input value.
SCHEMA_PROSE_KEYS = re.compile(
    r'"(_comment|note|description|agent|changed_paths|forbidden_hits|outside_allowlist|verdict)": "')


def offenders(paths, pattern):
    found = []
    for path in sorted(paths):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                found.append(f"{path.relative_to(KIT)}:{number}")
    return found


class EnglishArtifactsTests(unittest.TestCase):
    def test_roles_use_the_english_labels(self):
        roles = [p for p in (KIT / "01-roles" / "agents").iterdir() if p.suffix in (".md", ".json")]
        self.assertGreater(len(roles), 10)
        self.assertEqual(offenders(roles, SPANISH_LABELS), [])

    def test_skills_use_the_english_labels(self):
        skills = [p for p in (KIT / "02-skills").rglob("*") if p.is_file() and p.suffix in (".md", ".json")]
        self.assertGreater(len(skills), 10)
        self.assertEqual(offenders(skills, SPANISH_LABELS), [])

    def test_templates_use_the_english_labels(self):
        templates = [p for p in (KIT / "04-templates").iterdir() if p.is_file()]
        self.assertGreater(len(templates), 5)
        templates.append(CARD_TEMPLATE)
        self.assertEqual(offenders(templates, SPANISH_LABELS), [])

    def test_the_card_template_carries_the_nine_english_labels_in_order(self):
        text = CARD_TEMPLATE.read_text(encoding="utf-8")
        labels = re.findall(r"^\*\*([^*]+)\*\*:", text, flags=re.MULTILINE)
        self.assertEqual(labels, ["Why", "For what", "What it risks", "When", "How", "How far", "How we'll know",
                                  "Invariant", "Ticket"])

    def test_schema_comments_and_notes_are_english(self):
        found = []
        for path in sorted((TOOLS / "schemas").glob("*.json")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if SCHEMA_PROSE_KEYS.search(line) and SPANISH_PROSE.search(line):
                    found.append(f"{path.relative_to(KIT)}:{number}")
        self.assertEqual(found, [])

    def test_the_findings_example_shows_the_english_values_the_schema_accepts(self):
        example = json.loads((KIT / "04-templates" / "findings.example.json").read_text(encoding="utf-8"))
        properties = json.loads((TOOLS / "schemas" / "findings.schema.json").read_text(encoding="utf-8"))[
            "properties"]["findings"]["items"]["properties"]
        for finding in example["findings"]:
            self.assertIn(finding["verdict"], ("OK", "NUANCE", "BROKEN"))
            self.assertIn(finding["verdict"], properties["verdict"]["enum"])
            self.assertIn(finding["epistemic"], ("Measured", "Tested", "Inferred", "Assumed", "Unknown"))
            self.assertIn(finding["epistemic"], properties["epistemic"]["enum"])

    def test_the_spanish_card_still_validates_as_an_alias(self):
        # negative control: removing Spanish from the wording must not remove it from the parser
        schema = json.loads((TOOLS / "schemas" / "change-card.schema.json").read_text(encoding="utf-8"))
        aliases = [alias for field in schema["fields"] for alias in field.get("aliases", [])]
        for label in ("Por qué", "Para qué", "Qué arriesga", "Cuándo", "Cómo", "Hasta dónde", "Cómo lo sabremos"):
            self.assertIn(label, aliases)
        self.assertIn("Medido", schema["epistemic_tags"])

    def test_the_spanish_round_values_still_validate_as_aliases(self):
        # negative control: the round schemas keep every Spanish enum value they accepted before
        schemas = {name: (TOOLS / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8")
                   for name in ("findings", "blindspots", "verdict")}
        for name, values in (("findings", ("MATIZ", "ROTO", "Medido", "Desconocido")),
                             ("blindspots", ("CERRADO", "ABIERTO CON DUEÑO", "CONTENIDO", "Probado")),
                             ("verdict", ("Inferido", "Asumido"))):
            for value in values:
                self.assertIn(json.dumps(value, ensure_ascii=False), schemas[name], (name, value))

    def test_the_guard_catches_the_spanish_forms(self):
        # negative control on the guard itself: accented and unaccented labels, tags and verdicts are all seen
        for line in ("a ROTO gets one", "state is CERRADO", "ABIERTO CON DUEÑO", "[Medido]", "the card's `Hasta dónde`",
                     "Para que/Que arriesga", "## Ficha de cambio", '"sin ticket"'):
            self.assertIsNotNone(SPANISH_LABELS.search(line), line)
        for line in ("a BROKEN gets one", "state is CLOSED", "OPEN WITH OWNER", "[Measured]", "the card's `How far`",
                     '"summary": {"ok": 0, "matiz": 0, "roto": 1}', "invariants", "mcp__metodo__output_write"):
            self.assertIsNone(SPANISH_LABELS.search(line), line)


if __name__ == "__main__":
    unittest.main()
