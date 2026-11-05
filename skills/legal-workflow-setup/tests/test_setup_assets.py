"""Consistency of the setup wizard and the update skill with the profile contract.

The wizard is instructions, not code; these tests catch the drift that breaks it silently: a step id the
questionnaire does not cover, a context file without a template, a script command that does not exist.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
SKILLS = SKILL.parent
WORKFLOW = SKILLS / "legal-workflow"
UPDATE = SKILLS / "legal-workflow-update"
sys.path.insert(0, str(WORKFLOW / "scripts"))
import legal_profile as lp  # noqa: E402

CATALOG = json.loads((WORKFLOW / "assets" / "modules.json").read_text(encoding="utf-8"))
QUESTIONNAIRE = (SKILL / "references" / "questionnaire.md").read_text(encoding="utf-8")
TEXTS = {
    "setup": (SKILL / "SKILL.md").read_text(encoding="utf-8"),
    "questionnaire": QUESTIONNAIRE,
    "update": (UPDATE / "SKILL.md").read_text(encoding="utf-8"),
}


def frontmatter(text: str) -> dict[str, str]:
    block = text.split("---")[1]
    return dict(line.split(": ", 1) for line in block.strip().splitlines())


class Steps(unittest.TestCase):
    def test_every_catalog_step_has_a_row_and_a_section(self):
        for step in CATALOG["steps"]:
            with self.subTest(step=step):
                self.assertRegex(QUESTIONNAIRE, rf"\| `{re.escape(step)}` \|")
                headings = [line for line in QUESTIONNAIRE.splitlines() if line.startswith("### ")]
                self.assertTrue(any(f"`{step}`" in line for line in headings))

    def test_no_unknown_step_in_the_table(self):
        rows = re.findall(r"^\| `([a-z-]+)` \|", QUESTIONNAIRE, flags=re.M)
        self.assertEqual(rows, list(CATALOG["steps"]))

    def test_every_context_file_has_a_template(self):
        files = {rel for rel in CATALOG["steps"].values() if rel and rel.startswith("context/")}
        files.add("context/house-style.md")  # optional, written by step documents
        for rel in files:
            with self.subTest(file=rel):
                self.assertTrue((SKILL / "assets" / rel).is_file())


class Commands(unittest.TestCase):
    def test_every_script_command_named_exists(self):
        named = set()
        for text in TEXTS.values():
            named |= set(re.findall(r"`(?:<lp>|legal_profile\.py) ([a-z]+(?: (?:init|set|new|log|update|show|list))?)", text))
        self.assertTrue({"where", "status", "profile init", "modules set", "step set"} <= named)
        for command in named:
            with self.subTest(command=command), contextlib.redirect_stdout(io.StringIO()), \
                    self.assertRaises(SystemExit) as ctx:
                lp.main([*command.split(), "--help"])
            self.assertEqual(ctx.exception.code, 0)


class Skills(unittest.TestCase):
    def test_frontmatter(self):
        setup, update = frontmatter(TEXTS["setup"]), frontmatter(TEXTS["update"])
        self.assertEqual(setup["name"], "legal-workflow-setup")
        self.assertIn("настрой юриста", setup["description"])
        self.assertEqual(update["name"], "legal-workflow-update")
        # why: profile changes happen only when the user asks; the model must not start this skill by itself.
        self.assertEqual(update.get("disable-model-invocation"), "true")

    def test_migrations_name_the_current_version(self):
        self.assertIn(f"`schema_version` of `modules.json` and `intake.json`: {lp.SCHEMA_VERSION}.", TEXTS["update"])

    def test_install_hint_triggers_the_wizard(self):
        install = (SKILLS.parent / "install.sh").read_text(encoding="utf-8")
        self.assertIn("настрой юриста", install)



def section(text: str, step: str) -> str:
    """The questionnaire section whose heading names `step`, up to the next `### ` heading."""
    m = re.search(rf"^### [^\n]*`{re.escape(step)}`[^\n]*\n(.*?)(?=^### |^## |\Z)", text, flags=re.M | re.S)
    if not m:
        raise AssertionError(f"no section for step {step}")
    return m.group(1)


class Reading(unittest.TestCase):
    def test_reading_section_states_cost_yes_and_no_key(self):
        text = section(QUESTIONNAIRE, "reading")
        for needed in ("1,000 credits", "literal", "--scope user", "codex mcp add", "codex mcp login",
                       "firecrawl login --browser", "doctor.py", "firecrawl.dev/pricing", "skip"):
            with self.subTest(needed=needed):
                self.assertIn(needed, text)
        # why: the key option may only be named as something never to use.
        for para in text.split("\n\n"):
            if "--api-key" in para or "view-config" in para:
                self.assertIn("Never", para)

    def test_numbering_matches_catalog_order(self):
        numbers = re.findall(r"^\| `[a-z-]+` \| (\d+)\. ", QUESTIONNAIRE, flags=re.M)
        self.assertEqual([int(n) for n in numbers], list(range(1, len(CATALOG["steps"]) + 1)))
        self.assertEqual(len(numbers), 11)

    def test_quick_depth_and_watch_heading_follow_the_numbering(self):
        self.assertIn("steps 1–4", QUESTIONNAIRE)
        self.assertIn("### 7, 8, 11. `niches`, `laws`, `first-run`", QUESTIONNAIRE)

    def test_setup_skill_names_firecrawl_and_no_key(self):
        self.assertIn("Firecrawl", frontmatter(TEXTS["setup"])["description"])
        self.assertIn("Never ask for, read, print or store an API key", TEXTS["setup"])

if __name__ == "__main__":
    unittest.main()
