#!/usr/bin/env python3
"""Read the version field from __version__.py."""
import argparse
import re
import sys
from pathlib import Path


def read_version(text: str) -> str:
    match = re.search(r"^version\s*=\s*['\"]([^'\"]+)['\"]", text, re.MULTILINE)
    if not match:
        raise ValueError("version not found in __version__.py")
    return match.group(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path, help="Path to __version__.py")
    args = parser.parse_args()

    if not args.path.is_file():
        print(f"Missing {args.path}", file=sys.stderr)
        sys.exit(1)

    try:
        version = read_version(args.path.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)

    print(version)


if __name__ == "__main__":
    main()
