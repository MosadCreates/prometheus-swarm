"""Convert research/patch_log.jsonl (JSONL) to JSON array for paper submission and ChromaDB ingestion.

Usage:
    python research/convert_jsonl_to_json.py [--input research/patch_log.jsonl] [--output research/patch_log.json]
"""

import argparse
import json
import sys
from pathlib import Path


def convert(input_path: str, output_path: str) -> None:
    """Read JSONL file, convert to JSON array, write output."""
    input_file = Path(input_path)
    if not input_file.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    entries = []
    with open(input_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    output_file = Path(output_path)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)

    print(f"Converted {len(entries)} entries from {input_path} → {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert patch_log.jsonl to JSON array")
    parser.add_argument(
        "--input",
        default="research/patch_log.jsonl",
        help="Path to input JSONL file",
    )
    parser.add_argument(
        "--output",
        default="research/patch_log.json",
        help="Path to output JSON file",
    )
    args = parser.parse_args()
    convert(args.input, args.output)
