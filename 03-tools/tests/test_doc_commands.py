"""The team-facing pages name only what this tree holds (team-adoption S6).

A team lead copies commands out of docs/07-adoption.md, docs/09-measurement.md
and docs/10-position.md. Every kit path those pages write in backticks or in a
fenced block (a numbered folder, docs/, odd/ or a root entry file), every
`<instance>/bin|lib|hooks|config/...` path (the instance is a copy of 03-tools)
and every relative link must exist here, so a renamed script fails this test
instead of failing the reader. The failure names the page and the path.
"""
import re
import unittest
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent.parent
PAGES = ("docs/07-adoption.md", "docs/09-measurement.md", "docs/10-position.md")
CODE_RE = re.compile(r"```.*?```|`[^`\n]+`", re.S)
# A kit path, never the tail of a longer one (<instance>/out/..., ~/.claude/..., <run>/report.md).
PATH_RE = re.compile(r"(?<![\w./>~-])((?:0[0-8]-[\w-]+|docs|odd)/[\w./-]*|(?:AGENTS|CLAUDE|CONTEXT-PACK|README)\.md)")
INSTANCE_RE = re.compile(r"<instance>/((?:bin|lib|hooks|config)/[\w./-]+)")
LINK_RE = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
PLACEHOLDER_START = ("*", "<", "{")


def named_paths(text: str) -> set[str]:
    """Repo-relative paths a page names inside code spans and fenced blocks."""
    found = set()
    for span in CODE_RE.findall(text):
        for match in PATH_RE.finditer(span):
            token = match.group(1)
            if span[match.end():match.end() + 1] in PLACEHOLDER_START:  # a glob or a placeholder: its folder
                token = token.rsplit("/", 1)[0]
            found.add(token.rstrip("./"))
        found.update("03-tools/" + m.group(1).rstrip("./") for m in INSTANCE_RE.finditer(span))
    return found


def missing(page: str, text: str, root: Path = KIT_ROOT) -> list[str]:
    """One line per path or relative link of `page` that is not under `root`."""
    paths = {p: root / p for p in named_paths(text)}
    for target in LINK_RE.findall(text):
        if "://" not in target and not target.startswith("mailto:"):
            paths[target] = root / Path(page).parent / target
    return sorted(f"{page} names `{name}`, which is not in this tree" for name, where in paths.items()
                  if not where.exists())


@unittest.skipUnless((KIT_ROOT / "01-roles").is_dir(), "kit only: an instance has no docs/")
class DocCommandTests(unittest.TestCase):
    def test_every_path_the_team_pages_name_exists(self):
        problems = []
        for page in PAGES:
            source = KIT_ROOT / page
            self.assertTrue(source.is_file(), f"{page} is missing")
            text = source.read_text(encoding="utf-8")
            self.assertTrue(named_paths(text), f"{page} names no kit path: the extractor read nothing")
            problems += missing(page, text)
        self.assertEqual(problems, [])

    def test_the_adoption_page_names_the_commands_of_every_step(self):
        paths = named_paths((KIT_ROOT / PAGES[0]).read_text(encoding="utf-8"))
        for script in ("03-tools/bin/init.sh", "03-tools/bin/doctor.sh", "03-tools/bin/smoke-loop.sh",
                       "03-tools/bin/bench.sh", "03-tools/bin/mark-fp.sh", "03-tools/lib/hooks_report.py"):
            self.assertIn(script, paths)

    def test_negative_control_a_planted_path_is_reported_with_its_page(self):
        text = ("Run `03-tools/bin/no-such-script.sh <repo>`, then `<instance>/bin/no-such-wrapper.sh status`.\n"
                "```bash\npython3 08-benchmark/lib/no_such_module.py --run <run>\n```\n"
                "See [the runbook](no-such-page.md) and `03-tools/bin/init.sh`, `docs/07-adoption.md`.\n")
        self.assertEqual(missing("docs/x.md", text), [
            "docs/x.md names `03-tools/bin/no-such-script.sh`, which is not in this tree",
            "docs/x.md names `03-tools/bin/no-such-wrapper.sh`, which is not in this tree",
            "docs/x.md names `08-benchmark/lib/no_such_module.py`, which is not in this tree",
            "docs/x.md names `no-such-page.md`, which is not in this tree",
        ])

    def test_placeholders_globs_and_runtime_outputs_are_not_mistaken_for_kit_paths(self):
        text = ("`01-roles/agents/<role>.contract.json`, `02-skills/*/SKILL.md`, `<instance>/out/hooks/report.json`, "
                "`~/.claude/projects/`, `<run>/report.md`, `08-benchmark/data/README.md`")
        self.assertEqual(named_paths(text), {"01-roles/agents", "02-skills", "08-benchmark/data/README.md"})


if __name__ == "__main__":
    unittest.main()
