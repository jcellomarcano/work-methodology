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

    def test_agents_md_fits_its_token_budget(self):
        text = AGENTS.read_text(encoding="utf-8")
        tokens = -(-len(text) // 4)  # ceil(chars/4), the method of config/token-caps.json
        self.assertLessEqual(tokens, 600)

    def test_agents_md_sends_readers_to_readme_sections_not_the_whole_readme(self):
        text = AGENTS.read_text(encoding="utf-8")
        read_first = text.split("## Read first", 1)[1].split("\n## ", 1)[0]
        readme_item = next(line for line in read_first.splitlines() if "`README.md`" in line)
        self.assertIn("status block", readme_item)
        self.assertIn("Repository map", readme_item)
        # negative control: the old wording sent every agent through the whole README
        self.assertNotIn("the kit map and the measured status block", text)
        self.assertNotRegex(text.lower(), r"(read|the) (the )?whole readme")
        readme = (KIT_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("<!-- kit-status:start -->", readme)
        self.assertIn("## Repository map", readme)
        self.assertIn("## Start here", readme)

    def test_agents_md_lints_the_checkout_it_lives_in(self):
        text = AGENTS.read_text(encoding="utf-8")
        # run from the repo root, so `--root .` is this checkout, never the config's docs_root
        self.assertRegex(text, r"`python3 03-tools/lib/docs_lint\.py 03-tools/config/docs-caps\.json[^`]*--root \.[ `]")
        self.assertNotIn("cd 03-tools && python3 lib/docs_lint.py", text)

    def test_agents_md_keeps_its_safety_rules(self):
        text = AGENTS.read_text(encoding="utf-8")
        self.assertIn("Evidence or silence", text)
        self.assertIn("*.personal.*", text)
        self.assertIn("owner's decision", text)
        self.assertIn("Test-first", text)

    def test_personal_assets_are_never_named_as_something_to_read(self):
        text = AGENTS.read_text(encoding="utf-8")
        self.assertNotIn("bench/tmp", text.replace("`07-communication/bench/tmp/`", ""))


if __name__ == "__main__":
    unittest.main()
