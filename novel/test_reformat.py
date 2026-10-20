import tempfile
import unittest
from pathlib import Path

from reformat import INDENT, main, reflow
import sys
from unittest.mock import patch


class ReflowTests(unittest.TestCase):
    def test_hard_wrapped_lines_are_merged_and_indented(self):
        text = "标题\n\n黄昏时分,林来到了\n河边的村庄。\n桥上挂着灯。\n\n\n第二段。\n"
        self.assertEqual(
            reflow(text),
            f"标题\n\n{INDENT}黄昏时分,林来到了河边的村庄。\n\n{INDENT}桥上挂着灯。\n\n{INDENT}第二段。\n",
        )

    def test_lines_ending_with_sentence_punctuation_stay_separate_paragraphs(self):
        self.assertEqual(reflow("标题\n\n句一。\n句二!\n“句三。”\n"),
                         f"标题\n\n{INDENT}句一。\n\n{INDENT}句二!\n\n{INDENT}“句三。”\n")

    def test_english_lines_get_a_space(self):
        self.assertEqual(reflow("Title\n\nAt dusk\nLin came.\n"), f"Title\n\n{INDENT}At dusk Lin came.\n")

    def test_existing_indent_is_not_doubled_and_crlf_handled(self):
        self.assertEqual(reflow("标题\r\n\r\n\u3000\u3000正文\r\n"), f"标题\n\n{INDENT}正文\n")

    def test_idempotent_and_empty(self):
        once = reflow("标题\n\n甲\n乙。\n")
        self.assertEqual(reflow(once), once)
        self.assertEqual(reflow("\n\n"), "")

    def test_single_paragraph_is_not_treated_as_title(self):
        self.assertEqual(reflow("只有一段\n接着\n"), f"{INDENT}只有一段接着\n")


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "a.txt"
        self.path.write_text("标题\n\n甲\n乙。\n", encoding="utf-8")

    def test_default_does_not_modify_file(self):
        with patch.object(sys, "argv", ["reformat.py", str(self.path)]):
            self.assertEqual(main(), 0)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "标题\n\n甲\n乙。\n")

    def test_write_overwrites_file(self):
        with patch.object(sys, "argv", ["reformat.py", str(self.path), "--write"]):
            self.assertEqual(main(), 0)
        self.assertEqual(self.path.read_text(encoding="utf-8"), f"标题\n\n{INDENT}甲乙。\n")

    def test_missing_file_exit_code(self):
        with patch.object(sys, "argv", ["reformat.py", str(self.path.with_name("none.txt"))]):
            self.assertEqual(main(), 2)


if __name__ == "__main__":
    unittest.main()
