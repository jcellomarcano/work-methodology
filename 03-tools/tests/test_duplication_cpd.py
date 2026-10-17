import json
import tempfile
import unittest
from pathlib import Path

from lib import duplication_cpd

PMD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<pmd-cpd xmlns="https://pmd-code.org/schema/cpd-report" pmdVersion="7.27.0" timestamp="2026-01-01T00:00:00Z">
   <file path="/repo/app/src/main/A.kt" totalNumberOfTokens="500"/>
   <file path="/repo/app/src/main/B.kt" totalNumberOfTokens="300"/>
   <duplication lines="20" tokens="120">
      <file line="10" endline="29" path="/repo/app/src/main/A.kt"/>
      <file line="5" endline="24" path="/repo/app/src/main/B.kt"/>
      <codefragment><![CDATA[dummy]]></codefragment>
   </duplication>
</pmd-cpd>
"""

SHARED_BLOCK = "\n".join(f"    val field{i} = compute({i})" for i in range(12))


class ParsePmdXmlTests(unittest.TestCase):
    def test_relativizes_paths_and_builds_pairwise(self):
        result = duplication_cpd._parse_pmd_xml(PMD_XML, Path("/repo"))
        self.assertEqual(len(result["clusters"]), 1)
        cluster = result["clusters"][0]
        self.assertEqual(cluster["tokens"], 120)
        self.assertEqual(cluster["lines"], 20)
        self.assertEqual(
            cluster["occurrences"],
            [
                {"file": "app/src/main/A.kt", "start_line": 10, "end_line": 29},
                {"file": "app/src/main/B.kt", "start_line": 5, "end_line": 24},
            ],
        )
        self.assertEqual(result["pairwise"], {"app/src/main/A.kt|app/src/main/B.kt": 120})

    def test_empty_report_has_no_clusters(self):
        empty_xml = '<?xml version="1.0"?><pmd-cpd xmlns="https://pmd-code.org/schema/cpd-report"/>'
        result = duplication_cpd._parse_pmd_xml(empty_xml, Path("/repo"))
        self.assertEqual(result, {"clusters": [], "pairwise": {}})


class FallbackLinehashTests(unittest.TestCase):
    def test_detects_shared_block_between_two_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fa = root / "A.kt"
            fb = root / "B.kt"
            fa.write_text(f"package a\n\n{SHARED_BLOCK}\n", encoding="utf-8")
            fb.write_text(f"package b\n\n{SHARED_BLOCK}\n", encoding="utf-8")
            result = duplication_cpd.fallback_linehash(root, [fa, fb], min_tokens=5)
            self.assertGreaterEqual(len(result["clusters"]), 1)
            self.assertEqual(result["tool"], "fallback-linehash")
            self.assertEqual(result["epistemic"], "Inferido")
            self.assertEqual(len(result["pairwise"]), 1)
            self.assertEqual(result["pairwise"], {"A.kt|B.kt": list(result["pairwise"].values())[0]})
            self.assertGreater(list(result["pairwise"].values())[0], 0)

    def test_clean_files_produce_no_clusters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fa = root / "A.kt"
            fb = root / "B.kt"
            fa.write_text("package a\nfun onlyInA() = 1\n", encoding="utf-8")
            fb.write_text("package b\nfun onlyInB() = 2\n", encoding="utf-8")
            # negative control: with no shared blocks of 12 lines, zero clusters
            result = duplication_cpd.fallback_linehash(root, [fa, fb], min_tokens=1)
            self.assertEqual(result["clusters"], [])
            self.assertEqual(result["pairwise"], {})

    def test_min_tokens_filters_out_small_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fa = root / "A.kt"
            fb = root / "B.kt"
            fa.write_text(f"package a\n\n{SHARED_BLOCK}\n", encoding="utf-8")
            fb.write_text(f"package b\n\n{SHARED_BLOCK}\n", encoding="utf-8")
            result = duplication_cpd.fallback_linehash(root, [fa, fb], min_tokens=10_000)
            self.assertEqual(result["clusters"], [])

    def test_determinism(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fa = root / "A.kt"
            fb = root / "B.kt"
            fa.write_text(f"package a\n\n{SHARED_BLOCK}\n", encoding="utf-8")
            fb.write_text(f"package b\n\n{SHARED_BLOCK}\n", encoding="utf-8")
            first = duplication_cpd.fallback_linehash(root, [fa, fb], min_tokens=5)
            second = duplication_cpd.fallback_linehash(root, [fa, fb], min_tokens=5)
            self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))


class ChooseDefaultMinTokensTests(unittest.TestCase):
    def test_picks_smallest_threshold_at_or_under_40_clusters(self):
        calibration = {
            "50": {"clusters": 60, "tokens": 1},
            "75": {"clusters": 40, "tokens": 1},
            "100": {"clusters": 10, "tokens": 1},
            "150": {"clusters": 2, "tokens": 1},
        }
        self.assertEqual(duplication_cpd.choose_default_min_tokens(calibration), 75)

    def test_falls_back_to_100_when_none_qualify(self):
        calibration = {
            "50": {"clusters": 200, "tokens": 1},
            "75": {"clusters": 120, "tokens": 1},
            "100": {"clusters": 90, "tokens": 1},
            "150": {"clusters": 41, "tokens": 1},
        }
        # negative control: even the loosest threshold (150) is still above 40
        self.assertEqual(duplication_cpd.choose_default_min_tokens(calibration), 100)


class FindPmdBinTests(unittest.TestCase):
    def test_returns_none_when_vendor_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "vendor").mkdir()
            self.assertIsNone(duplication_cpd.find_pmd_bin(root))

    def test_finds_pmd_binary_under_vendor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pmd_bin = root / "vendor" / "pmd-bin-7.27.0" / "bin" / "pmd"
            pmd_bin.parent.mkdir(parents=True)
            pmd_bin.write_text("#!/bin/sh\n")
            self.assertEqual(duplication_cpd.find_pmd_bin(root), pmd_bin)


class LoadCalibrationTargetsTests(unittest.TestCase):
    def test_missing_config_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(duplication_cpd.load_calibration_targets(root), [])

    def test_reads_targets_from_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / "config"
            config_dir.mkdir()
            (config_dir / "duplication-targets.json").write_text(
                json.dumps({"targets": ["a.kt", "b.kt"]}), encoding="utf-8"
            )
            self.assertEqual(duplication_cpd.load_calibration_targets(root), ["a.kt", "b.kt"])


if __name__ == "__main__":
    unittest.main()
