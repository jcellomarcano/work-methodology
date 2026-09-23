import json
import re
import unittest
from pathlib import Path

from lib import output_lint

TOOLS = Path(__file__).resolve().parent.parent
CONFIG = json.loads((TOOLS / "config" / "output-lint.json").read_text(encoding="utf-8"))
PERSONAL = output_lint.load_personal(TOOLS / "config" / "output-lint.personal.json")
PLANTILLAS = TOOLS.parent / "07-communication" / "templates.md"

CLEAN_ESTADO = """La migración está al 80 %: quedan dos pantallas y el test de muerte de proceso.

- Hecho: modelo de datos y repositorio, con tests verdes en cada commit.
- Falta: pantalla de resumen y pantalla de error.
- Bloquea: el banco de pruebas lo tiene otra sesión hasta mañana.

Siguiente paso: cerrar la pantalla de resumen y pedir el banco para el jueves.

No probado: el arranque en frío con red caída.

## Detalle técnico

- Repositorio en `PaymentRepo.kt:41-88` @ a1b2c3d, con test de idempotencia [Probado]
- Tiempo medio de sincronización 320 ms en 5 corridas (mediana) [Medido]
- El proveedor antiguo no se toca; se deshace revirtiendo el commit [Inferido]
"""

TECH = "\n\n## Detalle técnico\n\n"


def status(result, rule_id):
    return next(r["status"] for r in result["rules"] if r["id"] == rule_id)


def rule(result, rule_id):
    return next(r for r in result["rules"] if r["id"] == rule_id)


class CleanSampleTests(unittest.TestCase):
    def test_clean_estado_passes_every_active_rule(self):
        # negative control for the set: a compliant reply must not produce any FAIL
        result = output_lint.check(CLEAN_ESTADO, CONFIG, kind="estado", lang="es", audience="public", personal_terms=PERSONAL)
        self.assertEqual(result["verdict"], "PASS", result)
        for rule_id in ("COM-01", "COM-02", "COM-03", "COM-04", "COM-05", "COM-06", "COM-08", "COM-09", "COM-10", "COM-11", "COM-12", "COM-14", "COM-15", "COM-18"):
            self.assertIn(status(result, rule_id), ("PASS", "WARN"), rule_id)

    def test_proposed_rules_are_skip_with_reviewer_detector(self):
        result = output_lint.check(CLEAN_ESTADO, CONFIG)
        for rule_id in ("COM-07", "COM-13", "COM-16", "COM-17"):
            self.assertEqual(rule(result, rule_id)["status"], "SKIP")
            self.assertEqual(rule(result, rule_id)["detector"], "reviewer")

    @unittest.skipUnless(PLANTILLAS.exists(), "templates.md no está junto a 03-tools")
    def test_every_template_skeleton_passes_its_type(self):
        # templates.md:4 claims every skeleton passes the lint with its --type: here it is tested, not just claimed
        text = PLANTILLAS.read_text(encoding="utf-8")
        blocks = []
        for section in re.split(r"^## \d\. ", text, flags=re.M)[1:]:
            kind = re.search(r"\(`--type (\w+)`\)", section)
            if kind:
                blocks += [(kind.group(1), body) for body in re.findall(r"```markdown\n(.*?)```", section, flags=re.S)]
        self.assertGreaterEqual(len(blocks), 7)
        for kind, body in blocks:
            result = output_lint.check(body, CONFIG, kind=kind, lang="en", audience="public", personal_terms=PERSONAL)
            self.assertEqual(result["verdict"], "PASS", (kind, [r for r in result["rules"] if r["status"] == "FAIL"]))


class RuleTests(unittest.TestCase):
    def test_com01_preamble_fails_including_inverted_marks(self):
        self.assertEqual(status(output_lint.check("Claro, aquí tienes la respuesta.\n\nLa migración está al 80 %.\n", CONFIG), "COM-01"), "FAIL")
        # real case from the challenger (C-04): the opening exclamation mark hid the preamble
        self.assertEqual(status(output_lint.check("¡Claro que sí! La respuesta es no.\n", CONFIG), "COM-01"), "FAIL")
        self.assertEqual(status(output_lint.check("**Claro** que hay riesgo.\n", CONFIG), "COM-01"), "FAIL")
        self.assertEqual(status(output_lint.check("La migración está al 80 %.\n", CONFIG), "COM-01"), "PASS")

    def test_com02_long_reply_without_technical_heading_fails(self):
        self.assertEqual(status(output_lint.check("\n".join(f"Línea {i} de la respuesta." for i in range(20)), CONFIG), "COM-02"), "FAIL")
        self.assertEqual(status(output_lint.check("\n".join(f"Línea {i}." for i in range(5)), CONFIG), "COM-02"), "PASS")

    def test_com03_counts_only_unordered_top_level_bullets(self):
        six = "Respuesta.\n" + "\n".join(f"- punto {i}" for i in range(6))
        self.assertEqual(status(output_lint.check(six, CONFIG), "COM-03"), "FAIL")
        nested = "Respuesta.\n- a\n  - a1\n  - a2\n  - a3\n  - a4\n  - a5\n- b\n"
        self.assertEqual(status(output_lint.check(nested, CONFIG), "COM-03"), "PASS")
        # real case from blind spots (B-04): a seven-step numbered runbook is not an opinion list
        steps = "Hazlo en este orden.\n" + "\n".join(f"{i}. paso {i}" for i in range(1, 8))
        self.assertEqual(status(output_lint.check(steps, CONFIG), "COM-03"), "PASS")

    def test_com04_marker_must_be_in_human_layer(self):
        text = "Respuesta sin siguiente paso.\n"
        self.assertEqual(status(output_lint.check(text, CONFIG, kind="estado"), "COM-04"), "FAIL")
        self.assertEqual(status(output_lint.check(text, CONFIG, kind="pregunta"), "COM-04"), "SKIP")
        self.assertEqual(status(output_lint.check(text, CONFIG), "COM-04"), "SKIP")
        self.assertEqual(status(output_lint.check(text + "\nNext step: pedir el banco.\n", CONFIG, kind="decision"), "COM-04"), "PASS")
        # real case from the challenger (C-05): a marker hidden in the technical layer does not count
        hidden = text + TECH + "- dato [Medido]\n- Siguiente paso: pedir el banco\n"
        self.assertEqual(status(output_lint.check(hidden, CONFIG, kind="estado"), "COM-04"), "FAIL")
        # blind spots (B-17): an empty marker warns
        self.assertEqual(status(output_lint.check(text + "\nSiguiente paso: ninguno.\n", CONFIG, kind="estado"), "COM-04"), "WARN")
        self.assertEqual(status(output_lint.check("¿Qué proveedor?\n\nNecesito de ti: el nombre del proveedor.\n", CONFIG, kind="aclaracion"), "COM-04"), "PASS")

    def test_com05_sentence_length_thresholds(self):
        self.assertEqual(status(output_lint.check("Respuesta. " + " ".join(["palabra"] * 30) + ".\n", CONFIG), "COM-05"), "WARN")
        self.assertEqual(status(output_lint.check("Respuesta. " + " ".join(["palabra"] * 45) + ".\n", CONFIG), "COM-05"), "FAIL")
        self.assertEqual(status(output_lint.check("Respuesta corta. Otra frase corta.\n", CONFIG), "COM-05"), "PASS")

    def test_com05_ignores_technical_layer_and_tables(self):
        long_sentence = " ".join(["palabra"] * 45) + "."
        text = f"Respuesta.\n\n| a | b |\n|---|---|\n| {long_sentence} | x |{TECH}- {long_sentence} [Medido]\n"
        self.assertEqual(status(output_lint.check(text, CONFIG), "COM-05"), "PASS")

    def test_com06_filler_fails_but_irreversible_warning_only_warns(self):
        self.assertEqual(status(output_lint.check("Respuesta. Es importante destacar que sí.\n", CONFIG), "COM-06"), "FAIL")
        self.assertEqual(status(output_lint.check("Answer. It's worth noting that yes.\n", CONFIG), "COM-06"), "FAIL")
        self.assertEqual(status(output_lint.check("Respuesta sin relleno.\n", CONFIG), "COM-06"), "PASS")
        # blind spots (B-03): a filler wrapping an irreversible warning is not punished with FAIL
        guarded = "Respuesta. Cabe señalar que la operación no tiene deshacer y borra recibos.\n"
        result = output_lint.check(guarded, CONFIG)
        self.assertEqual(status(result, "COM-06"), "WARN")
        self.assertIn("keep the warning", rule(result, "COM-06")["note"])

    def test_com08_language_mismatch_and_quotes_are_ignored(self):
        english = "The answer is that the build fails because the file is not in the path and the test does not run.\n"
        self.assertEqual(status(output_lint.check(english, CONFIG, lang="es"), "COM-08"), "FAIL")
        self.assertEqual(status(output_lint.check(english, CONFIG, lang="en"), "COM-08"), "PASS")
        self.assertEqual(status(output_lint.check(english, CONFIG), "COM-08"), "SKIP")
        # real case from the challenger (C-02): a literal English quote inside a Spanish reply
        spanish_with_quote = ("La carga extra viene de juntar dos sources en la cabeza. Los autores lo dicen así: "
                              "\"Learners must mentally integrate two sources of information in order to understand the solution, a process that yields a high cognitive load and hampers learning.\" "
                              "Por eso la documentación pone el rótulo dentro del diagrama y no en una leyenda aparte, y el lector no salta de un sitio a otro.\n")
        self.assertEqual(status(output_lint.check(spanish_with_quote, CONFIG, lang="es"), "COM-08"), "PASS")
        # blind spots (B-06): Catalan and German can be declared and are detected
        catalan = "La resposta és que la migració no està acabada i els tests no passen amb la base de dades nova, però el servei ja funciona amb els clients.\n"
        self.assertEqual(status(output_lint.check(catalan, CONFIG, lang="ca"), "COM-08"), "PASS")
        self.assertEqual(status(output_lint.check(catalan, CONFIG, lang="es"), "COM-08"), "FAIL")
        german = "Die Antwort ist, dass die Migration nicht fertig ist und die Tests mit der neuen Datenbank nicht laufen, aber der Dienst ist schon für die Kunden da.\n"
        self.assertEqual(status(output_lint.check(german, CONFIG, lang="de"), "COM-08"), "PASS")
        self.assertEqual(status(output_lint.check(german, CONFIG, lang="es"), "COM-08"), "FAIL")

    def test_com09_untagged_units_fail_including_prose(self):
        text = f"Respuesta.{TECH}- afirmación sin etiqueta\n- otra con etiqueta [Inferido]\n"
        result = output_lint.check(text, CONFIG)
        self.assertEqual(status(result, "COM-09"), "FAIL")
        self.assertEqual(len(rule(result, "COM-09")["evidence"]), 1)
        self.assertEqual(status(output_lint.check("Respuesta.\n", CONFIG), "COM-09"), "SKIP")
        # real case from the challenger (C-07): prose in the technical layer is also a claim
        prose = f"Respuesta.{TECH}El tiempo medio fue de 320 ms en cinco corridas y el proveedor\nantiguo no se toca.\n"
        self.assertEqual(status(output_lint.check(prose, CONFIG), "COM-09"), "FAIL")
        prose_tagged = f"Respuesta.{TECH}El tiempo medio fue de 320 ms en cinco corridas y el proveedor\nantiguo no se toca [Medido].\n"
        self.assertEqual(status(output_lint.check(prose_tagged, CONFIG), "COM-09"), "PASS")

    def test_com09_marker_lines_and_table_header_are_exempt(self):
        text = f"Respuesta.{TECH}- dato [Medido]\n- No probado: arranque sin red\n- Siguiente paso: pedir el banco\n\n| Opción | Riesgo |\n|---|---|\n| A | bajo [Inferido] |\n"
        self.assertEqual(status(output_lint.check(text, CONFIG), "COM-09"), "PASS")
        untagged_row = f"Respuesta.{TECH}| Opción | Riesgo |\n|---|---|\n| A | bajo |\n"
        self.assertEqual(status(output_lint.check(untagged_row, CONFIG), "COM-09"), "FAIL")

    def test_com09_unknown_tag_only_where_a_tag_would_go(self):
        # real case from the cold test: '[Citado]' and '[Verificado en contexto]' are not the kit's vocabulary
        text = f"Respuesta.{TECH}[Citado] frase con fuente\n- otra [Verificado en contexto]\n"
        result = output_lint.check(text, CONFIG)
        self.assertEqual(status(result, "COM-09"), "FAIL")
        self.assertIn("Citado", rule(result, "COM-09")["note"])
        self.assertIn("Verificado", rule(result, "COM-09")["note"])
        # real case from the challenger (C-03): [Docker] mid-sentence and a markdown link are not tags
        ok = f"Respuesta.{TECH}- Reproducido en el entorno [Docker] con la imagen 3.11-slim [Medido]\n- ver [la guía](https://x) [Inferido]\n- dato [Asumido: sin cobertura]\n\nVer la nota [1] y la casilla [x] [Medido].\n"
        self.assertEqual(status(output_lint.check(ok, CONFIG), "COM-09"), "PASS")

    def test_com10_not_tested_required_by_type_in_human_layer(self):
        text = "Respuesta.\n"
        self.assertEqual(status(output_lint.check(text, CONFIG, kind="fallo"), "COM-10"), "FAIL")
        self.assertEqual(status(output_lint.check(text, CONFIG, kind="decision"), "COM-10"), "SKIP")
        self.assertEqual(status(output_lint.check(text + "\nLo que NO es: un fallo de red.\n", CONFIG, kind="fallo"), "COM-10"), "PASS")
        self.assertEqual(status(output_lint.check(text + TECH + "- No probado: nada [Medido]\n", CONFIG, kind="fallo"), "COM-10"), "FAIL")

    def test_com11_closing_repeat_fails(self):
        self.assertEqual(status(output_lint.check("Respuesta.\n\nDetalle.\n\nEn resumen, la respuesta es la de arriba.\n", CONFIG), "COM-11"), "FAIL")
        self.assertEqual(status(output_lint.check("Respuesta.\n\nDetalle.\n", CONFIG), "COM-11"), "PASS")

    def test_com12_analogy_without_limit_warns_and_with_limit_passes(self):
        without = "Respuesta.\n\nEs como una cola del supermercado: cada petición espera su turno.\n"
        self.assertEqual(status(output_lint.check(without, CONFIG), "COM-12"), "WARN")
        with_limit = without + "A diferencia de la cola, aquí dos cajas pueden atender al mismo cliente por error.\n"
        self.assertEqual(status(output_lint.check(with_limit, CONFIG), "COM-12"), "PASS")
        self.assertEqual(status(output_lint.check("Respuesta sin analogía.\n", CONFIG), "COM-12"), "PASS")

    def test_com14_personal_terms_case_insensitive_and_meme_tags(self):
        text = "Respuesta. El orquestador es como Thrawn: estudia antes de actuar. A diferencia de él, no manda flotas.\n"
        self.assertEqual(status(output_lint.check(text, CONFIG, audience="public", personal_terms=PERSONAL), "COM-14"), "FAIL")
        self.assertEqual(status(output_lint.check(text, CONFIG, audience="owner", personal_terms=PERSONAL), "COM-14"), "SKIP")
        self.assertEqual(status(output_lint.check(text, CONFIG, audience="public", personal_terms=[]), "COM-14"), "SKIP")
        # real case from blind spots (B-07): lowercase and meme tags
        leaks = "El pipeline queda en modo jedi, como cuando Yoda entrena a Luke Skywalker en Dagobah. [bad feeling]\n"
        result = output_lint.check(leaks, CONFIG, audience="public", personal_terms=PERSONAL)
        self.assertEqual(status(result, "COM-14"), "FAIL")
        # negative control: lowercase 'stark' inside another English sentence is not Iron Man; 'Bond' is
        self.assertEqual(status(output_lint.check("A stark contrast between the two.\n", CONFIG, audience="public", personal_terms=PERSONAL), "COM-14"), "PASS")

    def test_com15_h1_em_dash_and_open_fence_fail_en_dash_warns(self):
        self.assertEqual(status(output_lint.check("# Título\n\nRespuesta.\n", CONFIG), "COM-15"), "FAIL")
        self.assertEqual(status(output_lint.check("Respuesta — con guion largo.\n", CONFIG), "COM-15"), "FAIL")
        self.assertEqual(status(output_lint.check("Respuesta – con guion medio.\n", CONFIG), "COM-15"), "WARN")
        self.assertEqual(status(output_lint.check("Respuesta.\n\n## Sección\n\n### Subsección\n", CONFIG), "COM-15"), "PASS")
        # real case from blind spots (B-05): an unclosed fence turned off the detector with a green verdict
        gamed = "Respuesta.\n\nSiguiente paso: ninguno.\n\n```\n" + "\n".join("Claro, es importante destacar — todo" for _ in range(20))
        result = output_lint.check(gamed, CONFIG, kind="estado")
        self.assertEqual(status(result, "COM-15"), "FAIL")
        self.assertEqual(result["verdict"], "FAIL")

    def test_com15_bold_over_cap_warns(self):
        text = "Respuesta.\n" + "\n".join(f"**punto {i}** con texto" for i in range(6))
        self.assertEqual(status(output_lint.check(text, CONFIG), "COM-15"), "WARN")

    def test_com18_irreversible_fact_hidden_in_technical_layer_fails(self):
        # real case from blind spots (B-01): the irreversible fact only in the technical layer and a green verdict
        hidden = "Todo listo, puedes anunciarlo al cliente.\n\nSiguiente paso: anunciar.\nNo probado: nada nuevo.\n" + TECH + "- Se ejecutó DROP TABLE payments_legacy sin copia; 40.000 recibos ya no existen [Medido]\n"
        result = output_lint.check(hidden, CONFIG, kind="estado")
        self.assertEqual(status(result, "COM-18"), "FAIL")
        self.assertEqual(result["verdict"], "FAIL")
        surfaced = "Se borró la tabla antigua sin copia: 40.000 recibos ya no existen (drop table).\n\nSiguiente paso: decidir si se restaura.\nNo probado: nada nuevo.\n" + TECH + "- Se ejecutó DROP TABLE payments_legacy sin copia [Medido]\n"
        self.assertEqual(status(output_lint.check(surfaced, CONFIG, kind="estado"), "COM-18"), "PASS")
        self.assertEqual(status(output_lint.check("Respuesta.\n", CONFIG), "COM-18"), "SKIP")

    def test_allow_downgrades_fail_to_warn_and_records_it(self):
        steps = "Respuesta.\n" + "\n".join(f"- punto {i}" for i in range(7))
        result = output_lint.check(steps, CONFIG, allow=["COM-03"])
        self.assertEqual(status(result, "COM-03"), "WARN")
        self.assertIn("--allow", rule(result, "COM-03")["note"])
        self.assertEqual(result["allow"], ["COM-03"])
        self.assertEqual(result["verdict"], "PASS")

    def test_code_fences_are_not_linted_when_closed(self):
        text = "Respuesta.\n\n```\n# not a heading — inside code\nClaro, esto es código\n```\n"
        result = output_lint.check(text, CONFIG)
        self.assertEqual(status(result, "COM-15"), "PASS")
        self.assertEqual(status(result, "COM-01"), "PASS")
        self.assertEqual(result["layers"]["code_fence_lines"], 2)


class DeterminismTests(unittest.TestCase):
    def test_same_input_same_output(self):
        first = output_lint.check(CLEAN_ESTADO, CONFIG, kind="estado", lang="es", audience="public", personal_terms=PERSONAL)
        second = output_lint.check(CLEAN_ESTADO, CONFIG, kind="estado", lang="es", audience="public", personal_terms=PERSONAL)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_rules_sorted_and_no_absolute_paths(self):
        result = output_lint.check(CLEAN_ESTADO, CONFIG)
        ids = [r["id"] for r in result["rules"]]
        self.assertEqual(ids, sorted(ids))
        self.assertNotIn("/Users/", json.dumps(result))
        self.assertNotIn("/home/", json.dumps(result))


class MainTests(unittest.TestCase):
    def test_main_exit_code_and_shas(self):
        import contextlib
        import io
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.md"
            path.write_text("Claro, aquí va.\n", encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = output_lint.main([str(path)])
            self.assertEqual(code, 1)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["verdict"], "FAIL")
            self.assertEqual(len(payload["tool_sha"]), 12)
            self.assertEqual(len(payload["config_sha"]), 12)

            path.write_text("Respuesta directa.\n", encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = output_lint.main([str(path), "--type", "pregunta", "--lang", "es", "--audience", "public", "--personal", str(Path(tmp) / "missing.json")])
            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertEqual(status(payload, "COM-14"), "SKIP")


if __name__ == "__main__":
    unittest.main()
