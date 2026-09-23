import json
import tempfile
import unittest
from pathlib import Path

from lib import bench_output_lint

CONFIG = json.loads((Path(__file__).resolve().parent.parent / "config" / "output-lint.json").read_text(encoding="utf-8"))

GOOD = "La respuesta es no.\n\nSiguiente paso: mover la clave fuera del bucle.\nNo probado: el proveedor.\n"
BAD = "Claro, aquí va. Es importante destacar que sí.\n"


class BenchTests(unittest.TestCase):
    def test_rows_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            out.mkdir()
            (out / "m1-sin-estado.md").write_text(BAD, encoding="utf-8")
            (out / "m1-con-estado.md").write_text(GOOD, encoding="utf-8")
            rows, summary = bench_output_lint.run(out, CONFIG, "es", "public", [])
            self.assertEqual([r["file"] for r in rows], ["m1-con-estado.md", "m1-sin-estado.md"])
            self.assertEqual(summary["by_arm"]["con"]["pass"], 1)
            self.assertEqual(summary["by_arm"]["sin"]["pass"], 0)
            self.assertIn("COM-01", summary["by_arm"]["sin"]["fail_by_rule"])
            # negative control: nothing gets worse in the "with" arm
            self.assertEqual(summary["worse_in_con"], {})

    def test_worse_in_con_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            out.mkdir()
            (out / "m1-sin-pregunta.md").write_text("La respuesta es no.\n", encoding="utf-8")
            (out / "m1-con-pregunta.md").write_text(BAD, encoding="utf-8")
            _, summary = bench_output_lint.run(out, CONFIG, "es", "public", [])
            self.assertIn("COM-01", summary["worse_in_con"])

    def test_determinism_and_shas_in_main(self):
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            out.mkdir()
            (out / "m1-con-estado.md").write_text(GOOD, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                bench_output_lint.main([str(out), "--personal", str(Path(tmp) / "none.json")])
            first = (Path(tmp) / "results.json").read_text(encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                bench_output_lint.main([str(out), "--personal", str(Path(tmp) / "none.json")])
            second = (Path(tmp) / "results.json").read_text(encoding="utf-8")
            self.assertEqual(first, second)
            payload = json.loads(first)
            self.assertEqual(len(payload["tool_sha"]), 12)
            self.assertEqual(len(payload["config_sha"]), 12)
            self.assertNotIn(tmp, first)


if __name__ == "__main__":
    unittest.main()
