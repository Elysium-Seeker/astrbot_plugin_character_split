import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple


ROOT = Path(__file__).resolve().parent
METADATA_FILE = ROOT / "metadata.yaml"
MAIN_FILE = ROOT / "main.py"
README_FILE = ROOT / "README.md"
CHANGELOG_FILE = ROOT / "CHANGELOG.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Release helper for AstrBot plugin: bump version, write changelog, "
            "update README, commit/tag/push."
        )
    )
    parser.add_argument(
        "--level",
        choices=("patch", "minor", "major"),
        default="patch",
        help="SemVer bump level (default: patch).",
    )
    parser.add_argument(
        "--note",
        action="append",
        default=[],
        help="A changelog bullet. Use multiple --note for multiple lines.",
    )
    parser.add_argument(
        "--message",
        default="",
        help="Optional commit message. Default: release: vX.Y.Z",
    )
    parser.add_argument(
        "--no-tag",
        action="store_true",
        help="Skip git tag creation.",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Skip git push.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print planned version and files; do not write or run git.",
    )
    return parser.parse_args()


def parse_semver(text: str) -> Tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", text.strip())
    if not match:
        raise ValueError(f"Invalid version: {text}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def bump_semver(version: str, level: str) -> str:
    major, minor, patch = parse_semver(version)
    if level == "major":
        major += 1
        minor = 0
        patch = 0
    elif level == "minor":
        minor += 1
        patch = 0
    else:
        patch += 1
    return f"v{major}.{minor}.{patch}"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def update_metadata_version(content: str, new_version: str) -> Tuple[str, str]:
    pattern = re.compile(r"^(\s*version:\s*)(v?\d+\.\d+\.\d+)(\s*)$", re.MULTILINE)
    match = pattern.search(content)
    if not match:
        raise RuntimeError("Cannot find version in metadata.yaml")
    old_version = match.group(2)
    replaced = pattern.sub(rf"\g<1>{new_version}\g<3>", content, count=1)
    return replaced, old_version


def update_main_register_version(content: str, semver_no_v: str) -> str:
    pattern = re.compile(r'(@register\([^\n]*,\s*")(\d+\.\d+\.\d+)("\))')
    if not pattern.search(content):
        raise RuntimeError("Cannot find @register version in main.py")
    return pattern.sub(rf"\g<1>{semver_no_v}\g<3>", content, count=1)


def build_changelog_entry(version_with_v: str, notes: List[str], today: str) -> str:
    lines = [f"## {version_with_v} - {today}"]
    for note in notes:
        lines.append(f"- {note}")
    return "\n".join(lines) + "\n\n"


def update_changelog(version_with_v: str, notes: List[str], today: str) -> None:
    if CHANGELOG_FILE.exists():
        current = read_text(CHANGELOG_FILE)
    else:
        current = "# Changelog\n\n"

    if f"## {version_with_v} - {today}" in current:
        return

    entry = build_changelog_entry(version_with_v, notes, today)

    header = "# Changelog\n\n"
    if current.startswith(header):
        updated = header + entry + current[len(header):]
    elif current.startswith("# Changelog"):
        first_break = current.find("\n")
        if first_break == -1:
            updated = current + "\n\n" + entry
        else:
            updated = current[: first_break + 1] + "\n" + entry + current[first_break + 1 :]
    else:
        updated = header + entry + current

    write_text(CHANGELOG_FILE, updated)


def update_readme_recent_updates(content: str, version_with_v: str, notes: List[str], today: str) -> str:
    heading = "## 🆕 最近更新"
    idx = content.find(heading)
    if idx == -1:
        return content

    section_start = idx + len(heading)
    next_heading = content.find("\n## ", section_start)
    section_end = len(content) if next_heading == -1 else next_heading
    section_text = content[section_start:section_end]

    if f"- {version_with_v}" in section_text:
        return content

    entry_lines = [f"- {version_with_v} ({today})"]
    for note in notes:
        entry_lines.append(f"   - {note}")
    entry_block = "\n\n" + "\n".join(entry_lines)

    return content[:section_start] + entry_block + content[section_start:]


def run_git(*args: str) -> None:
    subprocess.run(["git", *args], cwd=ROOT, check=True)


def ensure_notes(notes: List[str]) -> List[str]:
    clean = [n.strip() for n in notes if n and n.strip()]
    if clean:
        return clean
    return ["Routine maintenance and improvement update."]


def main() -> int:
    args = parse_args()
    notes = ensure_notes(args.note)

    metadata_text = read_text(METADATA_FILE)
    metadata_updated, old_version = update_metadata_version(metadata_text, "v0.0.0")
    del metadata_updated

    next_version = bump_semver(old_version, args.level)
    semver_no_v = next_version.lstrip("v")
    today = dt.date.today().isoformat()

    if args.dry_run:
        print(f"old_version={old_version}")
        print(f"next_version={next_version}")
        print(f"notes={notes}")
        return 0

    metadata_text = read_text(METADATA_FILE)
    metadata_text, _ = update_metadata_version(metadata_text, next_version)
    write_text(METADATA_FILE, metadata_text)

    main_text = read_text(MAIN_FILE)
    main_text = update_main_register_version(main_text, semver_no_v)
    write_text(MAIN_FILE, main_text)

    update_changelog(next_version, notes, today)

    readme_text = read_text(README_FILE)
    readme_text = update_readme_recent_updates(readme_text, next_version, notes, today)
    write_text(README_FILE, readme_text)

    files_to_add = [
        "metadata.yaml",
        "main.py",
        "README.md",
        "CHANGELOG.md",
        "update.py",
    ]
    run_git("add", *files_to_add)

    commit_message = args.message.strip() or f"release: {next_version}"
    run_git("commit", "-m", commit_message)

    if not args.no_tag:
        run_git("tag", next_version)

    if not args.no_push:
        run_git("push", "origin", "HEAD")
        if not args.no_tag:
            run_git("push", "origin", next_version)

    print(f"Released {next_version}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"Command failed: {exc}", file=sys.stderr)
        raise SystemExit(exc.returncode)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
