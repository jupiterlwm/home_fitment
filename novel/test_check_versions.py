import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from check_versions import check_folder, main


class CheckVersionsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)

    def write(self, name, content):
        path = self.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_numeric_order_and_text_summary(self):
        self.write("report_v10.txt", b"a\nnew\nextra\n")
        self.write("report_v2.txt", b"a\nold\n")
        self.write("report_v1.txt", b"a\n")
        self.write("unrelated.txt", b"ignored")
        report = check_folder(self.folder)
        self.assertEqual(report["scanned_files"], 4)
        group = report["groups"][0]
        self.assertEqual(group["versions"], ["1", "2", "10"])
        comparison = group["comparisons"][1]
        self.assertEqual((comparison["added_lines"], comparison["removed_lines"]), (2, 1))
        self.assertEqual(comparison["changes"], [{
            "operation": "replace", "old_start": 2, "old_count": 1,
            "new_start": 2, "new_count": 2,
        }])

    def test_older_lines_missing_from_latest_are_flagged(self):
        self.write("story_v1.txt", "保留\n被删掉\n".encode())
        self.write("story_v2.txt", "保留\n新增\n".encode())
        self.write("story_v3.txt", "保留\n新增\n结尾\n".encode())
        group = check_folder(self.folder)["groups"][0]
        self.assertEqual(group["latest"], "story_v3.txt")
        self.assertEqual(group["missing_from_latest"],
                         [{"file": "story_v1.txt", "lines": [{"line": 2, "text": "被删掉"}]}])

    def test_no_warning_when_latest_contains_everything(self):
        self.write("story_v1.txt", b"a\n")
        self.write("story_v2.txt", b"a\nb\n")
        self.assertEqual(check_folder(self.folder)["groups"][0]["missing_from_latest"], [])

    def test_dotted_versions_markers_and_identical_content(self):
        for version in ("1.10", "1.2"):
            self.write(f"story-version-{version}.txt", b"same")
        self.assertEqual(check_folder(self.folder)["groups"][0]["versions"], ["1.2", "1.10"])
        self.assertTrue(check_folder(self.folder)["groups"][0]["comparisons"][0]["identical"])

    def test_recursion_keeps_directories_separate(self):
        self.write("one/story_v1.txt", b"one")
        self.write("two/story_v2.txt", b"two")
        self.assertEqual(check_folder(self.folder)["groups"], [])
        self.assertEqual(check_folder(self.folder, recursive=True)["groups"], [])
        self.write("one/story_v2.txt", b"changed")
        self.assertEqual(check_folder(self.folder, recursive=True)["groups"][0]["name"],
                         "one/story.txt")

    def test_binary_and_non_utf8(self):
        self.write("data_v1.bin", b"\x00\x01")
        self.write("data_v2.bin", b"\x00\x02")
        self.assertEqual(check_folder(self.folder)["groups"][0]["comparisons"][0]["kind"],
                         "byte-level")
        self.write("text_v1.txt", "旧文本".encode("gb18030"))
        self.write("text_v2.txt", "新文本".encode("gb18030"))
        group = check_folder(self.folder)["groups"][1]
        self.assertEqual(group["comparisons"][0]["kind"], "byte-level")
        (self.folder / "data_v1.bin").unlink()
        (self.folder / "data_v2.bin").unlink()
        comparison = check_folder(self.folder, encoding="gb18030")["groups"][0]["comparisons"][0]
        self.assertEqual(comparison["kind"], "text")

    def test_line_endings_and_utf16(self):
        self.write("story_v1.txt", b"hello\r\n")
        self.write("story_v2.txt", "hello\n".encode("utf-16"))
        comparison = check_folder(self.folder)["groups"][0]["comparisons"][0]
        self.assertFalse(comparison["identical"])
        self.assertEqual(comparison["changes"], [])
        self.assertEqual(comparison["similarity_percent"], 100)

    def test_missing_folder_and_bad_encoding_are_errors(self):
        with self.assertRaises(NotADirectoryError):
            check_folder(self.folder / "missing")
        self.write("a_v1.txt", b"old")
        self.write("a_v2.txt", b"new")
        with self.assertRaises(LookupError):
            check_folder(self.folder, encoding="not-a-real-encoding")

    def test_cli_json_and_error_exit(self):
        self.write("稿件_v1.txt", b"old")
        self.write("稿件_v2.txt", b"new")
        with patch("sys.argv", ["check_versions", str(self.folder), "--json"]):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(), 0)
        self.assertEqual(len(json.loads(output.getvalue())["groups"]), 1)
        with patch("sys.argv", ["check_versions", str(self.folder / "missing")]):
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(main(), 2)
        self.assertIn("Error:", errors.getvalue())

    def test_english_names_and_symlinks_are_skipped(self):
        self.write("chapter_1.txt", b"first chapter")
        self.write("chapter_2.txt", b"second chapter")
        target = self.write("report_v1.txt", b"same")
        (self.folder / "report_v2.txt").symlink_to(target)
        groups = check_folder(self.folder)["groups"]
        self.assertEqual(groups, [])

    def test_han_substring_anywhere_size_order(self):
        self.write("xx长夜明灯_draft.txt", b"longer content")
        self.write("final_长夜明灯zz.txt", b"short")
        group = check_folder(self.folder)["groups"][0]
        self.assertEqual(group["order"], "size_ascending")
        self.assertEqual(group["comparisons"][0]["old"], "final_长夜明灯zz.txt")
        self.assertEqual(group["comparisons"][0]["new"], "xx长夜明灯_draft.txt")
        self.assertEqual(group["shared_substrings"], ["长夜明灯"])
        self.assertEqual(group["comparisons"][0]["byte_delta"], 9)

    def test_non_han_characters_do_not_match_or_join_han_runs(self):
        for name in (
            "draft_lantern.txt", "lantern_final.txt",
            "长夜A明灯_初稿.txt", "修订_长夜A明灯.txt",
            "长夜1234明灯_初稿.txt", "修订_长夜1234明灯.txt",
            "长夜-明灯_初稿.txt", "修订_长夜-明灯.txt",
            "かなカナ_初稿.txt", "修订_かなカナ.txt",
        ):
            self.write(name, b"same")
        self.assertEqual(check_folder(self.folder)["groups"], [])

    def test_traditional_and_extension_han(self):
        for title in ("長夜明燈", "\U00020000山河夢"):
            self.write(f"{title}_初稿.txt", b"old")
            self.write(f"修訂_{title}.txt", b"new text")
        groups = check_folder(self.folder)["groups"]
        self.assertEqual(len(groups), 2)
        self.assertEqual(
            {substring for group in groups for substring in group["shared_substrings"]},
            {"長夜明燈", "\U00020000山河夢"},
        )

    def test_substring_threshold_extension_directory_and_size_ties(self):
        self.write("长夜明灯_left.txt", b"same")
        self.write("right_长夜明灯.txt", b"same")
        self.write("长夜明灯_other.md", b"same")
        self.write("child/长夜明灯_extra.txt", b"same")
        self.write("长夜明_short.txt", b"same")
        groups = check_folder(self.folder, recursive=True)["groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["comparisons"][0]["old"], "right_长夜明灯.txt")
        self.assertEqual(groups[0]["comparisons"][0]["new"], "长夜明灯_left.txt")
        self.assertEqual(check_folder(self.folder, min_substring=12)["groups"], [])
        with self.assertRaises(ValueError):
            check_folder(self.folder, min_substring=0)

    def test_transitive_groups_and_explicit_group_priority(self):
        self.write("长夜明灯_first.txt", b"a")
        self.write("长夜明灯_山河故人.txt", b"ab")
        self.write("last_山河故人.txt", b"abc")
        self.write("长夜明灯_v1.txt", b"many more bytes")
        self.write("长夜明灯_v2.txt", b"small")
        groups = check_folder(self.folder)["groups"]
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0]["match_type"], "explicit_version")
        self.assertEqual(groups[0]["versions"], ["1", "2"])
        self.assertEqual(len(groups[1]["comparisons"]), 2)

    def test_unversioned_file_matches_single_explicit_revision(self):
        self.write("长夜明灯_v1.txt", b"original")
        self.write("revised_长夜明灯.txt", b"revised story")
        group = check_folder(self.folder)["groups"][0]
        self.assertEqual(group["match_type"], "substring")
        self.assertEqual(group["comparisons"][0]["old"], "长夜明灯_v1.txt")

    def test_cli_substring_option_and_invalid_threshold(self):
        self.write("长夜明_one.txt", b"one")
        self.write("two_长夜明.txt", b"two")
        with patch("sys.argv", ["check_versions", str(self.folder), "--min-substring", "3"]):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(), 0)
        self.assertIn("Han filename substring match (heuristic)", output.getvalue())
        with patch("sys.argv", ["check_versions", str(self.folder), "--min-substring", "0"]):
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(main(), 2)
        self.assertIn("at least 1", errors.getvalue())

    def test_substring_real_cli_json_and_read_only(self):
        first = self.write("draft_长夜明灯.txt", b"short\n")
        second = self.write("长夜明灯_final.txt", b"short\nnew ending\n")
        command = [sys.executable, str(Path(__file__).with_name("check_versions.py")),
                   str(self.folder), "--json"]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        group = json.loads(result.stdout)["groups"][0]
        self.assertEqual(group["match_type"], "substring")
        self.assertEqual(group["order"], "size_ascending")
        self.assertEqual(group["comparisons"][0]["old"], first.name)
        self.assertEqual(group["comparisons"][0]["new"], second.name)
        self.assertEqual(group["comparisons"][0]["added_lines"], 1)
        self.assertEqual(first.read_bytes(), b"short\n")
        self.assertEqual(second.read_bytes(), b"short\nnew ending\n")

    def test_punctuation_only_and_short_matches_are_ignored(self):
        self.write("one____alpha.txt", b"one")
        self.write("two____beta.txt", b"two")
        self.assertEqual(check_folder(self.folder)["groups"], [])

    def test_empty_files_insertion_and_deletion(self):
        self.write("a_v1.txt", b"")
        self.write("a_v2.txt", b"new\n")
        self.write("a_v3.txt", b"")
        comparisons = check_folder(self.folder)["groups"][0]["comparisons"]
        self.assertEqual(comparisons[0]["changes"], [{
            "operation": "insert", "old_start": None, "old_count": 0,
            "new_start": 1, "new_count": 1,
        }])
        self.assertEqual(comparisons[1]["changes"], [{
            "operation": "delete", "old_start": 1, "old_count": 1,
            "new_start": None, "new_count": 0,
        }])

    def test_read_error_is_explicit(self):
        self.write("a_v1.txt", b"old")
        self.write("a_v2.txt", b"new")
        with patch("sys.argv", ["check_versions", str(self.folder)]):
            with patch.object(Path, "read_bytes", side_effect=PermissionError("Access denied")):
                with contextlib.redirect_stderr(io.StringIO()) as errors:
                    self.assertEqual(main(), 2)
        self.assertIn("Access denied", errors.getvalue())

    def test_real_cli_and_sources_unchanged(self):
        old = self.write("report_v1.txt", b"a\nold\n")
        new = self.write("report_v2.txt", b"a\nnew\n")
        command = [sys.executable, str(Path(__file__).with_name("check_versions.py")),
                   str(self.folder)]
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        self.assertIn("Lines: +1 / -1", result.stdout)
        result = subprocess.run(command + ["--json"], capture_output=True, text=True, check=True)
        self.assertFalse(json.loads(result.stdout)["groups"][0]["comparisons"][0]["identical"])
        self.assertEqual(old.read_bytes(), b"a\nold\n")
        self.assertEqual(new.read_bytes(), b"a\nnew\n")


if __name__ == "__main__":
    unittest.main()
