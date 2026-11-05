"""Tests of tools/check.py. Fake values are assembled at runtime so this file passes the check itself."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import check  # noqa: E402

FAKE_HOME = "/" + "Users" + "/somebody/project"
FAKE_CODE = "2" + "0" * 12
FAKE_IBAN = "MD" + "24" + "AG" + "0" * 18
FAKE_MAIL = "ion" + "@" + "firma.md"
FAKE_PHONE = "+" + "373 69 123 456"
FAKE_KEY = "sk-" + "a" * 24


def write(base: Path, rel: str, text: str) -> None:
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def make_docx(path: Path, text: str) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f"<w:document><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:document>")


class ScanLines(unittest.TestCase):
    def fails(self, line: str, deny: list[str] | None = None) -> list[str]:
        return check.scan_lines("f.md", line, deny or [])[0]

    def test_clean_line_passes(self):
        self.assertEqual(self.fails("Contract de prestări servicii, art. 2.1"), [])

    def test_each_pattern_fails(self):
        for value in (FAKE_HOME, FAKE_CODE, FAKE_IBAN, FAKE_MAIL, FAKE_PHONE, FAKE_KEY):
            with self.subTest(value=value):
                self.assertEqual(len(self.fails(f"x {value} y")), 1, value)

    def test_placeholders_and_example_mail_pass(self):
        for value in ("/" + "Users/you/legal-profile", "/home/user/x", "ana@example.com",
                      "noreply@anthropic.com", "~/legal-profile"):
            with self.subTest(value=value):
                self.assertEqual(self.fails(value), [])

    def test_allow_marker_skips_patterns_but_not_private_marker(self):
        self.assertEqual(self.fails(f"{FAKE_CODE} leak-ok"), [])
        self.assertEqual(len(self.fails("<!-- " + "private:start --> leak-ok")), 1)

    def test_example_md_and_ro_are_real_domains(self):
        # only example.com / .net / .org are reserved (RFC 2606); example.md and example.ro can belong to someone
        for value in ("ana" + "@example.md", "ana" + "@example.ro"):
            self.assertEqual(len(self.fails(value)), 1, value)

    def test_denylist_is_case_insensitive(self):
        self.assertEqual(len(self.fails("Semnat de ACME Grup", ["acme grup"])), 1)
        self.assertEqual(self.fails("github.com/xacme/repo", ["acme"]), [])

    def test_decision_number_is_a_warning(self):
        fails, warns = check.scan_lines("f.md", "conform D" + "249", [])
        self.assertEqual(fails, [])
        self.assertEqual(len(warns), 1)

    def test_twelve_and_fourteen_digits_are_not_codes(self):
        self.assertEqual(self.fails("1" * 12), [])
        self.assertEqual(self.fails("1" * 14), [])


class Scan(unittest.TestCase):
    def test_tree_scan_skips_owner_docs_and_reads_docx(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write(base, "docs/owner/PLAN.md", FAKE_MAIL)
            write(base, ".venv/lib/x.py", FAKE_MAIL)
            write(base, "skills/a/SKILL.md", "ok")
            make_docx(base / "skills/a/model.docx", f"Administrator {FAKE_CODE}")
            fails, _ = check.scan(base, deny=["x-firm"])
            self.assertEqual(len(fails), 1)
            self.assertIn("model.docx", fails[0])

    def test_env_file_fails_and_bad_docx_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            write(base, ".env", "A=1")
            write(base, "x.docx", "not a zip")
            fails, _ = check.scan(base, deny=["x"])
            self.assertEqual(len(fails), 2)

    def test_docx_metadata_authors_and_links_are_scanned(self):
        """Codex review: a name only in docProps, w:author or a link target passed the check."""
        cases = {
            "docProps/core.xml": "<cp:coreProperties><dc:creator>Ion Fictiv</dc:creator></cp:coreProperties>",
            "word/comments.xml": '<w:comments><w:comment w:author="Ion Fictiv" w:id="1"/></w:comments>',
            "word/_rels/document.xml.rels": f'<Relationships><Relationship Target="mailto:{FAKE_MAIL}"/></Relationships>',
        }
        for part, xml in cases.items():
            with self.subTest(part=part), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "m.docx"
                with zipfile.ZipFile(path, "w") as z:
                    z.writestr("word/document.xml", "<w:document><w:p><w:r><w:t>ok</w:t></w:r></w:p></w:document>")
                    z.writestr(part, xml)
                fails, _ = check.scan(Path(tmp), deny=["ion fictiv"])
                self.assertEqual(len(fails), 1, fails)

    def test_docx_entities_decoded_and_embeddings_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.docx"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("word/document.xml",
                           "<w:document><w:p><w:r><w:t>Example &amp; Partners</w:t></w:r></w:p></w:document>")
            self.assertEqual(len(check.scan(Path(tmp), deny=["example & partners"])[0]), 1)
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("word/document.xml", "<w:document/>")
                z.writestr("word/embeddings/sheet1.xlsx", b"PK")
            fails, _ = check.scan(Path(tmp), deny=["x"])
            self.assertTrue(any("embedded" in f for f in fails), fails)

    def test_staged_content_is_scanned_not_the_working_tree(self):
        """Codex review: data staged and then cleaned only in the working tree passed the hook."""
        # why: run from the pre-commit hook, git exports GIT_DIR / GIT_INDEX_FILE (absolute in a linked worktree);
        # inherited, they point this temp repo's `git add` and check.scan_staged at the REAL repository's index.
        clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, clean, clear=True):
            base = Path(tmp)
            git = lambda *a: subprocess.run(["git", "-C", tmp, *a], check=True, capture_output=True)  # noqa: E731
            git("init", "-q")
            write(base, "a.md", f"mail {FAKE_MAIL}")
            write(base, "docs/owner/PLAN.md", "private")
            git("add", "a.md")
            git("add", "-f", "docs/owner/PLAN.md")
            write(base, "legal-profile/context/company.md", "private but no pattern")
            git("add", "-f", "legal-profile/context/company.md")
            write(base, "a.md", "clean now")
            self.assertEqual(check.scan(base, deny=["x"])[0], [])
            fails, _, n = check.scan_staged(base, deny=["x"])
            self.assertEqual(n, 3)
            self.assertEqual(len(fails), 3, fails)
            self.assertTrue(any("docs/owner/PLAN.md" in f for f in fails))

    def test_missing_denylist_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, warns = check.scan(Path(tmp), deny=[])
            self.assertTrue(any("denylist" in w for w in warns))

    def test_load_denylist_ignores_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "d.txt"
            p.write_text("# names\n\nAcme SRL\n", encoding="utf-8")
            self.assertEqual(check.load_denylist(p), ["acme srl"])
            self.assertEqual(check.load_denylist(Path(tmp) / "none.txt"), [])

    def test_repo_itself_is_clean(self):
        fails, _ = check.scan()
        self.assertEqual(fails, [])


if __name__ == "__main__":
    unittest.main()
