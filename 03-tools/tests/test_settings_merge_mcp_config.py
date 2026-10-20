"""settings_merge.py keeps other permissions and hooks intact; mcp_config.py
keeps other servers intact. Both idempotent."""
import json
import tempfile
import unittest
from pathlib import Path

from lib import mcp_config, settings_merge

KIT = {"hooks": {"PreToolUse": [
    {"matcher": "Bash", "hooks": [{"type": "command", "command": ": metodo-hook; H=\"${METODO_TOOLS:-__TOOLS_DEFAULT__}/hooks\"; exec python3 \"$H/guard_gates.py\"", "timeout": 10}]},
]}}
OWNER_HOOK = {"matcher": "Edit", "hooks": [{"type": "command", "command": "./my-own-hook.sh"}]}
LOOKALIKE = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hooks are fun"}]}


class SettingsMergeTests(unittest.TestCase):
    def setUp(self):
        self.settings = {"permissions": {"allow": ["Bash(git status)", "Read(//x/**)"], "deny": []},
                         "skillOverrides": {"a": 1},
                         "hooks": {"PreToolUse": [OWNER_HOOK, LOOKALIKE]}}

    def test_merge_preserves_everything_but_kit_hooks(self):
        merged, counts = settings_merge.merge_hooks(self.settings, KIT)
        self.assertEqual(merged["permissions"], self.settings["permissions"])
        self.assertEqual(merged["skillOverrides"], {"a": 1})
        self.assertEqual(list(merged.keys())[:2], ["permissions", "skillOverrides"])
        self.assertEqual(merged["hooks"]["PreToolUse"][:2], [OWNER_HOOK, LOOKALIKE])
        self.assertEqual(counts, {"added": 1, "removed": 0})

    def test_tools_default_token_is_rendered(self):
        merged, _ = settings_merge.merge_hooks(self.settings, KIT, tools_default="/example-repo-tools")
        command = merged["hooks"]["PreToolUse"][-1]["hooks"][0]["command"]
        self.assertIn("${METODO_TOOLS:-/example-repo-tools}/hooks", command)
        self.assertNotIn("__TOOLS_DEFAULT__", command)

    def test_second_merge_replaces_kit_entry_not_duplicates(self):
        once, _ = settings_merge.merge_hooks(self.settings, KIT)
        twice, counts = settings_merge.merge_hooks(once, KIT)
        self.assertEqual(once, twice)
        self.assertEqual(counts, {"added": 1, "removed": 1})

    def test_remove_drops_only_marked_entries(self):
        once, _ = settings_merge.merge_hooks(self.settings, KIT)
        removed, counts = settings_merge.remove_hooks(once)
        # negative control: the hook that only mentions "hooks" in its text carries no marker and stays
        self.assertEqual(removed["hooks"]["PreToolUse"], [OWNER_HOOK, LOOKALIKE])
        self.assertEqual(counts["removed"], 1)

    def test_merge_drops_kit_entries_of_events_the_kit_no_longer_ships(self):
        # T1 (D3): an install made when the kit still shipped a Stop hook must lose it on re-install
        old_stop = {"matcher": "", "hooks": [{"type": "command",
                    "command": ": metodo-hook; H=\"x/hooks\"; exec python3 \"$H/reply_lint.py\""}]}
        owner_stop = {"matcher": "", "hooks": [{"type": "command", "command": "./my-stop.sh"}]}
        settings = {"hooks": {"Stop": [owner_stop, old_stop], "PreToolUse": [OWNER_HOOK]}}
        merged, counts = settings_merge.merge_hooks(settings, KIT)
        self.assertEqual(merged["hooks"]["Stop"], [owner_stop])
        self.assertEqual(counts["removed"], 1)

    def test_merge_removes_an_event_left_empty(self):
        old_stop = {"matcher": "", "hooks": [{"type": "command", "command": ": metodo-hook; exec python3 reply_lint.py"}]}
        merged, _ = settings_merge.merge_hooks({"hooks": {"Stop": [old_stop]}}, KIT)
        self.assertNotIn("Stop", merged["hooks"])

    def test_apply_writes_only_when_changed_and_creates_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / ".claude" / "settings.local.json"
            kit_path = Path(tmp) / "kit.json"
            kit_path.write_text(json.dumps(KIT), encoding="utf-8")
            first = settings_merge.apply(settings_path, kit_path, settings_merge.DEFAULT_MARKER, False)
            self.assertTrue(first["changed"])
            second = settings_merge.apply(settings_path, kit_path, settings_merge.DEFAULT_MARKER, False)
            self.assertFalse(second["changed"])
            gone = settings_merge.apply(settings_path, None, settings_merge.DEFAULT_MARKER, True)
            self.assertTrue(gone["changed"])
            # T13: the file only held the kit's hooks, so removing them removes the file
            self.assertFalse(settings_path.exists())

    def test_remove_keeps_the_file_when_other_keys_remain(self):
        # negative control for the delete-when-empty rule
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.local.json"
            once, _ = settings_merge.merge_hooks(self.settings, KIT)
            settings_path.write_text(json.dumps(once, indent=2) + "\n", encoding="utf-8")
            gone = settings_merge.apply(settings_path, None, settings_merge.DEFAULT_MARKER, True)
            self.assertTrue(gone["changed"])
            self.assertEqual(json.loads(settings_path.read_text(encoding="utf-8")), self.settings)
            again = settings_merge.apply(settings_path, None, settings_merge.DEFAULT_MARKER, True)
            self.assertFalse(again["changed"])
            self.assertTrue(settings_path.exists())


class AutoCompactWindowTests(unittest.TestCase):
    """T3 (D1): the orchestrator's auto-compact window is 300k, a documented settings key
    (settings-reference#autocompactwindow), set only when the owner has not set it."""

    def _apply(self, path, remove=False, kit_path=None):
        return settings_merge.apply(path, kit_path, settings_merge.DEFAULT_MARKER, remove)

    def _kit(self, tmp):
        kit_path = Path(tmp) / "kit.json"
        kit_path.write_text(json.dumps(KIT), encoding="utf-8")
        return kit_path

    def test_install_sets_the_window_when_absent(self):
        self.assertEqual(settings_merge.KIT_SETTINGS, {"autoCompactWindow": 300000})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.local.json"
            path.write_text(json.dumps({"permissions": {"allow": []}}), encoding="utf-8")
            result = self._apply(path, kit_path=self._kit(tmp))
            self.assertTrue(result["changed"])
            self.assertEqual(result["keys_added"], ["autoCompactWindow"])
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["autoCompactWindow"], 300000)
            self.assertEqual(data["permissions"], {"allow": []})
            # idempotent: a second pass changes nothing
            self.assertFalse(self._apply(path, kit_path=self._kit(tmp))["changed"])

    def test_install_keeps_an_owner_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.local.json"
            path.write_text(json.dumps({"autoCompactWindow": 500000}), encoding="utf-8")
            result = self._apply(path, kit_path=self._kit(tmp))
            self.assertEqual(result["keys_added"], [])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["autoCompactWindow"], 500000)
            # and remove never takes an owner value out
            gone = self._apply(path, remove=True)
            self.assertEqual(gone["keys_removed"], [])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"autoCompactWindow": 500000})

    def test_remove_takes_the_kit_value_out_and_the_file_with_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".claude" / "settings.local.json"
            self._apply(path, kit_path=self._kit(tmp))
            gone = self._apply(path, remove=True)
            self.assertTrue(gone["changed"])
            self.assertEqual(gone["keys_removed"], ["autoCompactWindow"])
            # the kit created the file and nothing else is in it
            self.assertFalse(path.exists())

    def test_remove_keeps_other_keys_and_an_edited_window(self):
        merged = settings_merge.merge_keys({"permissions": {"allow": ["x"]}})[0]
        removed, keys = settings_merge.remove_keys(merged)
        self.assertEqual(removed, {"permissions": {"allow": ["x"]}})
        self.assertEqual(keys, ["autoCompactWindow"])
        # negative control: the owner changed the kit's value after install, so it is the owner's now
        edited = dict(merged, autoCompactWindow=250000)
        self.assertEqual(settings_merge.remove_keys(edited), (edited, []))


class McpConfigTests(unittest.TestCase):
    def test_merge_keeps_other_servers(self):
        existing = {"mcpServers": {"github": {"type": "http", "url": "https://x"}}}
        merged = mcp_config.merge(existing, mcp_config.render_entry())
        self.assertIn("github", merged["mcpServers"])
        self.assertEqual(merged["mcpServers"]["metodo"]["command"], "python3")
        self.assertIn("mcp/server.py", merged["mcpServers"]["metodo"]["args"][0])

    def test_remove_deletes_file_when_nothing_else_remains(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".mcp.json"
            first = mcp_config.apply(path, mcp_config.DEFAULT_TOOLS_EXPR, mcp_config.DEFAULT_REPO_EXPR, False)
            self.assertTrue(first["changed"] and path.exists())
            again = mcp_config.apply(path, mcp_config.DEFAULT_TOOLS_EXPR, mcp_config.DEFAULT_REPO_EXPR, False)
            self.assertFalse(again["changed"])
            gone = mcp_config.apply(path, mcp_config.DEFAULT_TOOLS_EXPR, mcp_config.DEFAULT_REPO_EXPR, True)
            self.assertTrue(gone["changed"])
            self.assertFalse(path.exists())

    def test_remove_keeps_file_with_other_servers(self):
        # negative control
        existing = {"mcpServers": {"github": {"type": "http"}, "metodo": {"type": "stdio"}}}
        self.assertEqual(mcp_config.remove(existing), {"mcpServers": {"github": {"type": "http"}}})

    def test_pi_override_removal_keeps_other_keys(self):
        existing = {"mcpServers": {"github": {"toolPrefix": "gh"}, "metodo": {"toolPrefix": "mcp"}}, "settings": {"x": 1}}
        self.assertEqual(mcp_config.remove_pi_override(existing),
                         {"mcpServers": {"github": {"toolPrefix": "gh"}}, "settings": {"x": 1}})
        # an owner key on the metodo entry survives; only the kit's toolPrefix goes
        owned = {"mcpServers": {"metodo": {"toolPrefix": "mcp", "timeout": 5}}}
        self.assertEqual(mcp_config.remove_pi_override(owned), {"mcpServers": {"metodo": {"timeout": 5}}})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mcp.json"
            path.write_text(json.dumps({"mcpServers": {"metodo": {"toolPrefix": "mcp"}}}), encoding="utf-8")
            gone = mcp_config.apply(path, "", "", True, pi_override=True)
            self.assertTrue(gone["changed"])
            self.assertFalse(path.exists())
