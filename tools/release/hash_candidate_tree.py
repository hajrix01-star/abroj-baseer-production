#!/usr/bin/env python3
"""Create a reproducible SHA-256 receipt for a frozen candidate tree."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


METHOD = (
    "sha256 of UTF-8 concatenation of sorted "
    "relative-posix-path|file-sha256|byte-length\\n records; "
    "excluding __pycache__ directories and .pyc files"
)


def build_receipt(root: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    records: list[dict[str, object]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or path.suffix.lower() == ".pyc":
            continue
        content = path.read_bytes()
        records.append(
            {
                "path": relative.as_posix(),
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
            }
        )

    records.sort(key=lambda item: str(item["path"]))
    canonical = "".join(
        f'{record["path"]}|{record["sha256"]}|{record["bytes"]}\n'
        for record in records
    ).encode("utf-8")
    return {
        "schema": "baseer-candidate-tree-receipt/v1",
        "method": METHOD,
        "root_name": root.name,
        "file_count": len(records),
        "tree_sha256": hashlib.sha256(canonical).hexdigest(),
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    receipt = build_receipt(args.root)
    rendered = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
