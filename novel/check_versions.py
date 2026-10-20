"""Find versioned or Han-substring-matched filenames and summarize differences."""

import argparse
import difflib
import hashlib
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path


VERSION_PATTERN = re.compile(
    r"^(?P<name>.+?)[ _.-]+(?:version|ver|rev|v)[ _.-]*"
    r"(?P<version>\d+(?:\.\d+)*)(?P<extension>(?:\.[^\W\d][\w-]*)*)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class VersionedFile:
    path: Path
    version: str | None

    @property
    def sort_key(self) -> tuple[tuple[int, ...], str]:
        if self.version is None:
            raise ValueError(f"No explicit version in {self.path.name}")
        parts = [int(part) for part in self.version.split(".")]
        while len(parts) > 1 and parts[-1] == 0:
            parts.pop()
        return tuple(parts), self.path.name


def substring_groups(paths: list[Path], folder: Path, minimum: int) -> list[dict]:
    """Connect filenames sharing a minimum-length Han-only substring."""
    buckets: dict[tuple[Path, str], list[Path]] = {}
    for path in paths:
        buckets.setdefault((path.parent, path.suffix.casefold()), []).append(path)
    result = []
    for bucket in buckets.values():
        owners: dict[str, Path] = {}
        neighbors: dict[Path, set[Path]] = {path: set() for path in bucket}
        matches: dict[Path, set[str]] = {path: set() for path in bucket}
        for path in bucket:
            match = VERSION_PATTERN.fullmatch(path.name)
            stem = (match["name"] if match else path.stem).casefold()
            for index in range(len(stem) - minimum + 1):
                substring = stem[index:index + minimum]
                if not all(
                    unicodedata.name(character, "").startswith(
                        ("CJK UNIFIED IDEOGRAPH-", "CJK COMPATIBILITY IDEOGRAPH-")
                    )
                    for character in substring
                ):
                    continue
                owner = owners.setdefault(substring, path)
                if owner != path:
                    neighbors[path].add(owner)
                    neighbors[owner].add(path)
                    matches[path].add(substring)
                    matches[owner].add(substring)

        visited: set[Path] = set()
        for path in bucket:
            if path in visited:
                continue
            pending = [path]
            component = set()
            while pending:
                current = pending.pop()
                if current in visited:
                    continue
                visited.add(current)
                component.add(current)
                pending.extend(neighbors[current] - visited)
            if len(component) < 2:
                continue
            ordered = sorted(component, key=lambda file: (file.stat().st_size, file.name))
            result.append({
                "name": str(min(component).relative_to(folder)),
                "files": [VersionedFile(file, None) for file in ordered],
                "match_type": "substring",
                "order": "size_ascending",
                "shared_substrings": sorted(set().union(*(matches[file] for file in component))),
            })
    return result


def find_versions(
    folder: Path, recursive: bool = False, min_substring: int = 4,
) -> tuple[list[dict], int]:
    """Group versions within each directory; never follow symbolic links."""
    if not folder.is_dir():
        raise NotADirectoryError(f"Folder does not exist or is not a directory: {folder}")
    if min_substring < 1:
        raise ValueError("Minimum substring length must be at least 1.")

    def raise_walk_error(error: OSError) -> None:
        raise error

    groups: dict[tuple[str, str, str], list[VersionedFile]] = {}
    candidates: list[Path] = []
    scanned = 0
    for directory, subdirectories, filenames in os.walk(folder, onerror=raise_walk_error):
        subdirectories.sort()
        for filename in sorted(filenames):
            path = Path(directory) / filename
            if path.is_symlink() or not path.is_file():
                continue
            scanned += 1
            candidates.append(path)
            match = VERSION_PATTERN.fullmatch(filename)
            if match is None:
                continue
            relative_directory = str(path.parent.relative_to(folder))
            key = (relative_directory, match["name"], match["extension"])
            groups.setdefault(key, []).append(VersionedFile(path, match["version"]))
        if not recursive:
            break

    result = []
    explicitly_grouped: set[Path] = set()
    for (directory, name, extension), files in sorted(groups.items()):
        if len(files) < 2:
            continue
        result.append({
            "name": str(Path(directory) / (name + extension)),
            "files": sorted(files, key=lambda file: file.sort_key),
            "match_type": "explicit_version",
            "order": "version_ascending",
            "shared_substrings": [],
        })
        explicitly_grouped.update(file.path for file in files)
    result.extend(substring_groups(
        [path for path in candidates if path not in explicitly_grouped], folder, min_substring,
    ))
    return result, scanned


def decode_text(data: bytes, encoding: str | None) -> str | None:
    if encoding is not None:
        return data.decode(encoding)
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def compare_files(old: Path, new: Path, encoding: str | None = None) -> dict:
    old_bytes, new_bytes = old.read_bytes(), new.read_bytes()
    result = {
        "identical": old_bytes == new_bytes,
        "old_bytes": len(old_bytes),
        "new_bytes": len(new_bytes),
        "byte_delta": len(new_bytes) - len(old_bytes),
        "old_sha256": hashlib.sha256(old_bytes).hexdigest(),
        "new_sha256": hashlib.sha256(new_bytes).hexdigest(),
    }
    if result["identical"]:
        return result

    old_text, new_text = decode_text(old_bytes, encoding), decode_text(new_bytes, encoding)
    if old_text is None or new_text is None:
        result.update({
            "kind": "byte-level",
            "note": "Binary or unsupported text encoding; no line comparison. "
                    "Use --encoding for a known text encoding.",
        })
        return result

    old_lines, new_lines = old_text.splitlines(), new_text.splitlines()
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    added = removed = 0
    changes = []
    for operation, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if operation == "equal":
            continue
        removed += old_end - old_start
        added += new_end - new_start
        changes.append({
            "operation": operation,
            "old_start": old_start + 1 if old_end > old_start else None,
            "old_count": old_end - old_start,
            "new_start": new_start + 1 if new_end > new_start else None,
            "new_count": new_end - new_start,
        })
    result.update({
        "kind": "text",
        "old_lines": len(old_lines),
        "new_lines": len(new_lines),
        "added_lines": added,
        "removed_lines": removed,
        "similarity_percent": round(matcher.ratio() * 100, 2),
        "changes": changes,
        "note": "Line endings or encoding changed; line contents are identical."
                if not changes else "Line-based summary; replacements count as removals and additions.",
    })
    return result


def lines_missing_from_latest(files: list[VersionedFile], encoding: str | None) -> list[dict]:
    """List non-blank lines in older versions that the last (latest) version lacks."""
    if len(files) < 2:
        return []
    latest_text = decode_text(files[-1].path.read_bytes(), encoding)
    if latest_text is None:
        return []
    latest_lines = {line.strip() for line in latest_text.splitlines()}
    result = []
    for file in files[:-1]:
        text = decode_text(file.path.read_bytes(), encoding)
        if text is None:
            continue
        missing = [
            {"line": number, "text": line}
            for number, line in enumerate(text.splitlines(), 1)
            if line.strip() and line.strip() not in latest_lines
        ]
        if missing:
            result.append({"file": file.path.name, "lines": missing})
    return result


def check_folder(
    folder: Path, recursive: bool = False, encoding: str | None = None,
    min_substring: int = 4,
) -> dict:
    folder = folder.expanduser().resolve()
    groups, scanned = find_versions(folder, recursive, min_substring)
    report = {
        "folder": str(folder),
        "recursive": recursive,
        "min_substring": min_substring,
        "scanned_files": scanned,
        "groups": [],
    }
    for group in groups:
        files = group["files"]
        comparisons = []
        for old, new in zip(files, files[1:]):
            comparisons.append({
                "old": str(old.path.relative_to(folder)),
                "new": str(new.path.relative_to(folder)),
                **compare_files(old.path, new.path, encoding),
            })
        report["groups"].append({
            "name": group["name"],
            "versions": [file.version for file in files],
            "match_type": group["match_type"],
            "order": group["order"],
            "shared_substrings": group["shared_substrings"],
            "comparisons": comparisons,
            "latest": files[-1].path.name,
            "missing_from_latest": lines_missing_from_latest(files, encoding),
        })
    return report


def print_report(report: dict) -> None:
    print(f"Folder: {report['folder']}")
    print(f"Scanned files: {report['scanned_files']}")
    print(f"Comparison groups: {len(report['groups'])}")
    if not report["groups"]:
        print("No versioned or substring-matched filename groups found.")
    for group in report["groups"]:
        if group["match_type"] == "explicit_version":
            print(f"\n{group['name']} - versions: {', '.join(group['versions'])}")
        else:
            print(f"\n{group['name']} - Han filename substring match (heuristic)")
            print(f"  Shared substrings: {', '.join(group['shared_substrings'])}")
            print("  Order: smallest to largest; ties by filename. "
                  "Size does not establish revision history.")
        for comparison in group["comparisons"]:
            print(f"  {comparison['old']} -> {comparison['new']}")
            if comparison["identical"]:
                print("    Identical content (byte-for-byte).")
                continue
            print(f"    Size: {comparison['old_bytes']} -> {comparison['new_bytes']} bytes "
                  f"({comparison['byte_delta']:+d})")
            if comparison["kind"] == "text":
                print(f"    Lines: +{comparison['added_lines']} / "
                      f"-{comparison['removed_lines']}; "
                      f"similarity: {comparison['similarity_percent']}%")
                for change in comparison["changes"]:
                    old_range = (f"{change['old_start']} ({change['old_count']} lines)"
                                 if change["old_count"] else "none")
                    new_range = (f"{change['new_start']} ({change['new_count']} lines)"
                                 if change["new_count"] else "none")
                    print(f"    {change['operation']}: old {old_range}; new {new_range}")
            else:
                print(f"    SHA-256: {comparison['old_sha256']} -> {comparison['new_sha256']}")
            print(f"    {comparison['note']}")
        for entry in group["missing_from_latest"]:
            print(f"  WARNING: {entry['file']} has lines not in latest {group['latest']}:")
            for item in entry["lines"]:
                print(f"    line {item['line']}: {item['text']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, help="Folder to scan (read-only)")
    parser.add_argument("--recursive", action="store_true", help="Include subfolders")
    parser.add_argument("--encoding", help="Force a text encoding, e.g. gb18030")
    parser.add_argument("--json", action="store_true", help="Print a machine-readable report")
    parser.add_argument("--min-substring", type=int, default=4,
                        help="Minimum consecutive shared Han characters (default: 4)")
    args = parser.parse_args()
    try:
        report = check_folder(args.folder, args.recursive, args.encoding, args.min_substring)
    except (OSError, UnicodeError, LookupError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
