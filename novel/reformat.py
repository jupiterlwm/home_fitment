#!/usr/bin/env python3
"""重排段落:合并被硬换行拆开的句子(行尾是句末标点的行单独成段),空行分隔段落,
每段首行缩进两个全角空格。

默认只把结果输出到终端;加 --write 才覆盖原文件。
"""

import argparse
import re
import sys
from pathlib import Path

INDENT = "\u3000\u3000"
ASCII_WORD_EDGE = re.compile(r"[A-Za-z0-9]")
SENTENCE_END = tuple("。!?!?…”」』\"')）.")


def join_lines(lines: list[str]) -> list[str]:
    """合并被硬换行拆开的行;以句末标点结尾的行结束当前段落,中文直接相连,
    两侧都是英文/数字时补一个空格。"""
    paragraphs = []
    current = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if current and ASCII_WORD_EDGE.match(current[-1]) and ASCII_WORD_EDGE.match(line[0]):
            current += " "
        current += line
        if current.endswith(SENTENCE_END):
            paragraphs.append(current)
            current = ""
    if current:
        paragraphs.append(current)
    return paragraphs


def reflow(text: str) -> str:
    paragraphs = [
        paragraph
        for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n"))
        for paragraph in join_lines(block.splitlines())
    ]
    # 开头单行且后面还有正文的段落视为标题,不缩进
    output = []
    for index, paragraph in enumerate(paragraphs):
        is_title = index == 0 and len(paragraphs) > 1 and len(paragraph) <= 40
        output.append(paragraph if is_title else INDENT + paragraph)
    return "\n\n".join(output) + "\n" if output else ""


def target_files(paths: list[Path]) -> list[Path]:
    files = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(p for p in path.glob("*.txt") if not p.is_symlink()))
        else:
            files.append(path)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, default=[Path(".")],
                        help="txt 文件或目录(默认当前目录)")
    parser.add_argument("--write", action="store_true", help="覆盖原文件")
    parser.add_argument("--encoding", default="utf-8", help="文件编码(默认 utf-8)")
    args = parser.parse_args()
    try:
        files = target_files(args.paths)
        for path in files:
            original = path.read_text(encoding=args.encoding)
            formatted = reflow(original)
            if args.write:
                if formatted != original:
                    path.write_text(formatted, encoding=args.encoding, newline="\n")
                print(f"{'已重排' if formatted != original else '无变化'}: {path}")
            else:
                print(f"===== {path} =====")
                print(formatted, end="")
    except (OSError, UnicodeError, LookupError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
