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
            self.assertNotIn("hooks", json.loads(settings_path.read_text(encoding="utf-8")))


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
