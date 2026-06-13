#!/usr/bin/env python3
"""Patch __version__.py for a public YunaBot release."""
import argparse
import re
import sys
from pathlib import Path


FIELDS = {
    "version": r"^version\s*=\s*['\"][^'\"]*['\"]",
    "version_branch": r"^version_branch\s*=\s*['\"][^'\"]*['\"]",
    "version_build": r"^version_build\s*=\s*['\"][^'\"]*['\"]",
    "version_date": r"^version_date\s*=\s*['\"][^'\"]*['\"]",
}


def patch_field(text: str, field: str, value: str) -> str:
    replacement = f"{field} = '{value}'"
    new_text, count = re.subn(
        FIELDS[field],
        replacement,
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise ValueError(f"Could not patch {field}")
    return new_text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("target_dir", type=Path, help="Directory containing __version__.py")
    parser.add_argument("--version", required=True, help="e.g. 7.0.1")
    parser.add_argument("--build", required=True, help="e.g. 1")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--branch", required=True, help="e.g. candy or lily")
    args = parser.parse_args()

    path = args.target_dir / "__version__.py"
    if not path.is_file():
        print(f"Missing {path}", file=sys.stderr)
        sys.exit(1)

    text = path.read_text(encoding="utf-8")
    try:
        text = patch_field(text, "version", args.version)
        text = patch_field(text, "version_branch", args.branch)
        text = patch_field(text, "version_build", args.build)
        text = patch_field(text, "version_date", args.date)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)

    path.write_text(text, encoding="utf-8")
    release = f"v{args.version}-{args.branch}.{args.build}"
    print(f"Patched __version__.py -> {release} ({args.date})")


if __name__ == "__main__":
    main()
