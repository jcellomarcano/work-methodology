"""Root entry points for agents (S14): AGENTS.md and CLAUDE.md exist, CLAUDE.md
imports AGENTS.md instead of duplicating it, and every repository path and
kit command AGENTS.md names exists, so an agent that follows it never lands
on a dead reference."""
import re
import unittest
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent.parent
AGENTS = KIT_ROOT / "AGENTS.md"
CLAUDE = KIT_ROOT / "CLAUDE.md"
PATH_RE = re.compile(r"`((?:0[0-8]-[\w-]+|odd|ejemplos|CONTEXT-PACK\.md|README\.md)[^`\s]*)`")
COMMAND_RE = re.compile(r"`(03-tools/bin/[\w.-]+\.sh)[^`]*`")
# Named only as never-to-read; they live on the owner's machine, not in a clone.
PERSONAL = ("07-communication/bench/tmp",)


@unittest.skipUnless((KIT_ROOT / "01-roles").is_dir(), "kit only: an instance has no root entry points")
class EntryPointTests(unittest.TestCase):
    def test_agents_md_exists_and_points_to_the_context_pack_first(self):
        text = AGENTS.read_text(encoding="utf-8")
        first_path = PATH_RE.search(text)
        self.assertIsNotNone(first_path)
        self.assertEqual(first_path.group(1), "CONTEXT-PACK.md")

    def test_claude_md_imports_agents_md(self):
        text = CLAUDE.read_text(encoding="utf-8")
        self.assertIn("@AGENTS.md", text)
        self.assertLess(len(text.splitlines()), 15, "CLAUDE.md imports, it does not duplicate")

    def test_every_path_named_in_agents_md_exists(self):
        text = AGENTS.read_text(encoding="utf-8")
        paths = sorted({m.group(1).rstrip("/").split("#")[0] for m in PATH_RE.finditer(text)})
        self.assertTrue(paths)
        missing = [p for p in paths if "*" not in p and "<" not in p and p not in PERSONAL and not (KIT_ROOT / p).exists()]
        self.assertEqual(missing, [])

    def test_every_kit_command_named_in_agents_md_exists(self):
        text = AGENTS.read_text(encoding="utf-8")
        commands = sorted({m.group(1) for m in COMMAND_RE.finditer(text)})
        self.assertIn("03-tools/bin/init.sh", commands)
        self.assertIn("03-tools/bin/route.sh", commands)
        self.assertEqual([c for c in commands if not (KIT_ROOT / c).is_file()], [])

    def test_personal_assets_are_never_named_as_something_to_read(self):
        text = AGENTS.read_text(encoding="utf-8")
        self.assertNotIn("bench/tmp", text.replace("`07-communication/bench/tmp/`", ""))


if __name__ == "__main__":
    unittest.main()
