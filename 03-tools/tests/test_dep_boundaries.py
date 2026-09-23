import json
import tempfile
import unittest
from pathlib import Path

from lib import dep_boundaries as db


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_fixture_repo(root: Path) -> None:
    # domain: one clean file and one that breaks purity (Android + vendor).
    _write(root / "domain/src/main/kotlin/com/acme/domain/Foo.kt", """
package com.acme.domain

import kotlin.collections.List

fun computeTotal(): Int = 1
""")
    _write(root / "domain/src/main/kotlin/com/acme/domain/Bad.kt", """
package com.acme.domain

import android.os.Bundle
import com.vendorone.Sdk

fun broken() {}
""")

    # data: clean, importing domain, and one that breaks it (android + app-ui).
    _write(root / "data/src/main/kotlin/com/acme/data/Repo.kt", """
package com.acme.data

import com.acme.domain.Foo

fun save() {}
""")
    _write(root / "data/src/main/kotlin/com/acme/data/BadRepo.kt", """
package com.acme.data

import android.content.Context
import com.acme.app.ui.Screen

fun leaky() {}
""")

    # payment-api: breaks purity by importing Room.
    _write(root / "payment/api/src/main/kotlin/com/acme/payment/api/Api.kt", """
package com.acme.payment.api

import androidx.room.Entity
import kotlin.Unit

fun apiThing() {}
""")

    # payment-vendor: may import the vendor SDK without penalty.
    _write(root / "payment/vendorone/src/main/kotlin/com/acme/payment/vendorone/Gw.kt", """
package com.acme.payment.vendorone

import com.vendorone.Sdk

fun gateway() {}
""")

    # app-framework: cycle candidate toward app-ui, and legacy vendor exempt.
    _write(root / "app/src/main/kotlin/com/acme/app/framework/Handler.kt", """
package com.acme.app.framework

import com.acme.app.ui.Screen
import com.vendortwo.Legacy

fun handle() {}
""")

    # app-ui: cycle candidate toward app-framework, and vendor NOT exempt -> violation.
    _write(root / "app/src/main/kotlin/com/acme/app/ui/Screen.kt", """
package com.acme.app.ui

import com.acme.app.framework.Handler
import com.vendortwo.Direct

fun computeTotal(): Int = 2
""")

    # app-di: may import the vendor (exempt).
    _write(root / "app/src/main/kotlin/com/acme/app/di/Modules.kt", """
package com.acme.app.di

import com.vendorthree.Sdk

fun module() {}
""")

    # app-other (catch-all root of :app).
    _write(root / "app/src/main/kotlin/com/acme/app/App.kt", """
package com.acme.app

fun boot() {}
""")


def _fixture_config() -> dict:
    return {
        "nodes": {
            "domain": ["domain/src/main"],
            "data": ["data/src/main"],
            "payment-api": ["payment/api/src/main"],
            "payment-vendor": ["payment/vendorone/src/main"],
            "app-ui": ["app/src/main/kotlin/com/acme/app/ui"],
            "app-framework": ["app/src/main/kotlin/com/acme/app/framework"],
            "app-di": ["app/src/main/kotlin/com/acme/app/di"],
            "app-other": ["app/src/main/kotlin/com/acme/app"],
        },
        "domain_allowed_external_prefixes": ["kotlin.", "kotlinx.", "java.", "javax."],
        "data_forbidden_raw_prefixes": ["android.", "androidx."],
        "data_forbidden_node_prefix": "app-",
        "payment_purity_nodes": ["payment-api", "payment-runtime"],
        "payment_purity_forbidden_prefixes": [
            "android.", "androidx.", "com.vendorone", "com.vendortwo", "com.vendorthree",
            "dagger.", "javax.inject", "org.greenrobot", "com.google.protobuf", "androidx.room",
        ],
        "vendor_packages": ["com.vendorone", "com.vendortwo", "com.vendorthree"],
        "vendor_exempt_nodes": ["payment-vendor", "app-framework", "app-di"],
        "cycle_pair": ["app-framework", "app-ui"],
    }


class MinimalPrefixesTests(unittest.TestCase):
    def test_reduces_nested_packages_to_shortest_common_prefix(self):
        result = db._minimal_prefixes({"a.b", "a.b.c", "a.b.c.d"})
        self.assertEqual(result, ["a.b"])

    def test_keeps_unrelated_packages_separate(self):
        result = db._minimal_prefixes({"a.b", "c.d"})
        self.assertEqual(result, ["a.b", "c.d"])


class ResolveNodeTests(unittest.TestCase):
    def test_picks_the_most_specific_match(self):
        index = db._prefix_index({"app-other": ["com.acme.app"], "domain": ["com.acme.domain"]})
        self.assertEqual(db.resolve_node("com.acme.domain.Foo", index), "domain")
        self.assertEqual(db.resolve_node("com.acme.app.Something", index), "app-other")

    def test_unresolved_import_returns_none(self):
        index = db._prefix_index({"domain": ["com.acme.domain"]})
        self.assertIsNone(db.resolve_node("org.json.JSONObject", index))

    def test_wildcard_import_resolves_like_a_normal_one(self):
        index = db._prefix_index({"domain": ["com.acme.domain"]})
        self.assertEqual(db.resolve_node("com.acme.domain.*", index), "domain")


class BuildDepsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _build_fixture_repo(self.root)
        self.config = _fixture_config()

    def tearDown(self):
        self.tmp.cleanup()

    def test_domain_purity_violation_is_detected(self):
        # negative control: the android.os.Bundle import in domain must show up.
        payload = db.build_deps(self.root, self.config)
        domain_violations = [v for v in payload["violations"] if v["rule"] == "domain-purity"]
        self.assertTrue(any(v["import"] == "android.os.Bundle" for v in domain_violations))

    def test_domain_vendor_import_flags_both_rules(self):
        payload = db.build_deps(self.root, self.config)
        vendor_hits = [v for v in payload["violations"] if v["import"] == "com.vendorone.Sdk" and v["from_node"] == "domain"]
        rules = {v["rule"] for v in vendor_hits}
        # negative control: domain importing a vendor breaks purity AND vendor lockdown.
        self.assertEqual(rules, {"domain-purity", "vendor-lockdown"})

    def test_domain_clean_import_has_no_violation(self):
        payload = db.build_deps(self.root, self.config)
        clean_hits = [v for v in payload["violations"] if v["file"].endswith("domain/Foo.kt")]
        self.assertEqual(clean_hits, [])

    def test_data_boundary_android_and_app_are_detected(self):
        payload = db.build_deps(self.root, self.config)
        data_violations = {v["import"] for v in payload["violations"] if v["rule"] == "data-boundary"}
        self.assertIn("android.content.Context", data_violations)
        self.assertIn("com.acme.app.ui.Screen", data_violations)

    def test_data_importing_domain_is_not_a_violation(self):
        payload = db.build_deps(self.root, self.config)
        hits = [v for v in payload["violations"] if v["file"].endswith("data/Repo.kt")]
        self.assertEqual(hits, [])

    def test_payment_api_purity_violation(self):
        payload = db.build_deps(self.root, self.config)
        hits = [v for v in payload["violations"] if v["rule"] == "payment-purity"]
        self.assertTrue(any(v["import"] == "androidx.room.Entity" for v in hits))

    def test_vendor_lockdown_hits_unexempt_node_only(self):
        payload = db.build_deps(self.root, self.config)
        vendor_hits = {(v["from_node"], v["import"]) for v in payload["violations"] if v["rule"] == "vendor-lockdown"}
        self.assertIn(("app-ui", "com.vendortwo.Direct"), vendor_hits)
        # negative control: app-framework and app-di are exempt and must NOT appear.
        self.assertNotIn(("app-framework", "com.vendortwo.Legacy"), vendor_hits)
        self.assertFalse(any(v[0] == "app-di" for v in vendor_hits))
        self.assertFalse(any(v[0] == "payment-vendor" for v in vendor_hits))

    def test_cycle_candidates_count_both_directions(self):
        payload = db.build_deps(self.root, self.config)
        cycles = payload["cycle_candidates"]
        self.assertEqual(cycles["app-framework->app-ui"]["count"], 1)
        self.assertEqual(cycles["app-ui->app-framework"]["count"], 1)

    def test_adapter_law_candidate_by_name_match(self):
        payload = db.build_deps(self.root, self.config)
        names = {c["function"] for c in payload["adapter_law_candidates"]}
        # negative control: computeTotal exists in domain AND app-ui -> it must show up.
        self.assertIn("computeTotal", names)
        hit = next(c for c in payload["adapter_law_candidates"] if c["function"] == "computeTotal")
        self.assertEqual(hit["epistemic"], "Inferido")
        self.assertTrue(any("domain/Foo.kt" in m for m in hit["matches"]))

    def test_nodes_seen_reports_file_counts(self):
        payload = db.build_deps(self.root, self.config)
        self.assertEqual(payload["nodes_seen"]["domain"], 2)
        self.assertEqual(payload["nodes_seen"]["app-ui"], 1)

    def test_ancestor_catchall_dir_does_not_reclaim_more_specific_nodes(self):
        # negative control: app-other declares "app/.../app" (an ancestor of
        # app-ui/app-framework/app-di); without disambiguating by specificity,
        # its rglob would repeat Screen.kt/Handler.kt/Modules.kt as if they were
        # its own. Only App.kt (which does not live under any more
        # specific folder) should count for app-other.
        payload = db.build_deps(self.root, self.config)
        self.assertEqual(payload["nodes_seen"]["app-other"], 1)
        self.assertTrue(payload["nodes_seen"]["app-other"] > 0)
        node_files = db.node_files(self.root, self.config["nodes"])
        self.assertEqual([Path(f).name for f in node_files["app-other"]], ["App.kt"])

    def test_derived_prefixes_recorded_for_review(self):
        payload = db.build_deps(self.root, self.config)
        self.assertIn("com.acme.domain", payload["derived_prefixes"]["domain"])

    def test_empty_node_reports_zero_not_an_error(self):
        config = dict(self.config)
        config["nodes"] = dict(config["nodes"])
        config["nodes"]["services"] = ["services/src/main"]
        payload = db.build_deps(self.root, config)
        # negative control: a node with no .kt files must not blow up, only come out at 0.
        self.assertEqual(payload["nodes_seen"]["services"], 0)
        self.assertEqual(payload["derived_prefixes"]["services"], [])

    def test_determinism_across_runs(self):
        first = db.build_deps(self.root, self.config)
        second = db.build_deps(self.root, self.config)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))


class MainCliTests(unittest.TestCase):
    def test_main_writes_deps_json_and_md(self):
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_fixture_repo(root)
            config_path = root / "dep-boundaries.json"
            config_path.write_text(json.dumps(_fixture_config()), encoding="utf-8")

            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
            subprocess.run(["git", "add", "-A"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)
            repo_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
            ).stdout.strip()

            code = db.main([str(root), "--config", str(config_path)])
            self.assertEqual(code, 0)

            out_dir = db.TOOLS_ROOT / "out" / repo_sha
            self.addCleanup(lambda: __import__("shutil").rmtree(out_dir, ignore_errors=True))
            deps = json.loads((out_dir / "deps.json").read_text(encoding="utf-8"))
            self.assertEqual(deps["repo_sha"], repo_sha)
            self.assertIn("violations", deps)
            self.assertTrue((out_dir / "deps.md").exists())


if __name__ == "__main__":
    unittest.main()
