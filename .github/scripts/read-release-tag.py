#!/usr/bin/env python3
"""Build the release tag string from __version__.py."""
import argparse
import re
import sys
from pathlib import Path


def read_field(text: str, field: str) -> str:
    match = re.search(rf"^{field}\s*=\s*['\"]([^'\"]+)['\"]", text, re.MULTILINE)
    if not match:
        raise ValueError(f"{field} not found in __version__.py")
    return match.group(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path, help="Path to __version__.py")
    args = parser.parse_args()

    if not args.path.is_file():
        print(f"Missing {args.path}", file=sys.stderr)
        sys.exit(1)

    text = args.path.read_text(encoding="utf-8")
    try:
        version = read_field(text, "version")
        branch = read_field(text, "version_branch")
        build = read_field(text, "version_build")
    except ValueError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)

    print(f"v{version}-{branch}.{build}")


if __name__ == "__main__":
    main()
