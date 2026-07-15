#!/usr/bin/env python3
"""Analyze pairing TSV data against Yamanouchi-word transpose duality.

Usage:
    python analyze_pairings_yamanouchi.py
    python analyze_pairings_yamanouchi.py /path/to/another_file.tsv

By default, the script looks for All_Pairings_0710.tsv in the same folder as
this script, then in the folder where you run the command.

The script groups rows by w_word and looks at x_words whose
final_pairing_value is nonzero. For w_words with exactly one such x_word and
pairing value +/-1, it checks whether x_word is the Yamanouchi word obtained
from transposing the standard Young tableau associated to w_word.
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path


DEFAULT_TSV_NAME = "All_Pairings_0710.tsv"


def find_input_path(argv: list[str]) -> Path | None:
    """Return the TSV path from argv, or auto-detect the default TSV file."""
    if len(argv) > 2:
        return None

    if len(argv) == 2:
        return Path(argv[1]).expanduser()

    script_dir_path = Path(__file__).resolve().parent / DEFAULT_TSV_NAME
    if script_dir_path.exists():
        return script_dir_path

    current_dir_path = Path.cwd() / DEFAULT_TSV_NAME
    if current_dir_path.exists():
        return current_dir_path

    return None


def parse_pairing_value(raw: str) -> Decimal | None:
    """Return a numeric value, or None for blank/non-numeric values."""
    value = raw.strip()
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def transpose_yamanouchi_word(word: str) -> str:
    """Convert a Yamanouchi word to SYT, transpose it, and convert back.

    Interpreting a Yamanouchi word as a standard Young tableau means entry i
    is placed in row word[i], with entries in each row ordered left to right.
    Transposing swaps row and column, so the new row of entry i is the column
    occupied by i in the original tableau. That column is exactly the number
    of times word[i] has appeared up to and including position i.

    This returns a compact digit string, matching the format of this TSV. If a
    transposed row index exceeds 9, use tuple/list output instead for clarity.
    """
    seen: dict[str, int] = defaultdict(int)
    transposed_letters: list[str] = []

    for letter in word.strip():
        if letter.isspace():
            continue
        seen[letter] += 1
        column = seen[letter]
        if column > 9:
            raise ValueError(
                f"Transposed row index {column} is not representable as one digit "
                f"for word {word!r}."
            )
        transposed_letters.append(str(column))

    return "".join(transposed_letters)


def main() -> int:
    input_path = find_input_path(sys.argv)
    if input_path is None:
        print("Usage: python analyze_pairings_yamanouchi.py [path/to/file.tsv]", file=sys.stderr)
        print(
            f"If no path is given, place {DEFAULT_TSV_NAME} next to this script "
            "or run the command from the folder containing that file.",
            file=sys.stderr,
        )
        return 2

    if not input_path.exists():
        print(f"File not found: {input_path}", file=sys.stderr)
        return 2

    all_w_words: set[str] = set()
    nonzero_by_w: dict[str, dict[str, set[Decimal]]] = defaultdict(lambda: defaultdict(set))
    duplicate_nonzero_rows = 0

    with input_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        required = {"w_word", "x_word", "final_pairing_value"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            print(f"Missing required column(s): {', '.join(sorted(missing))}", file=sys.stderr)
            return 2

        for row in reader:
            w_word = row["w_word"].strip()
            x_word = row["x_word"].strip()
            all_w_words.add(w_word)

            value = parse_pairing_value(row["final_pairing_value"])
            if value is not None and value != 0:
                if nonzero_by_w[w_word][x_word]:
                    duplicate_nonzero_rows += 1
                nonzero_by_w[w_word][x_word].add(value)

    matching_pairs: list[tuple[str, str, Decimal]] = []
    mismatching_pairs: list[tuple[str, str, Decimal, str]] = []
    more_than_one_nonzero_x: list[str] = []
    one_nonzero_x_value_not_pm_one: list[tuple[str, str, tuple[Decimal, ...]]] = []
    no_nonzero_x: list[str] = []

    pm_one = {Decimal(1), Decimal(-1)}

    for w_word in sorted(all_w_words):
        nonzero_xs = nonzero_by_w.get(w_word, {})

        if len(nonzero_xs) == 0:
            no_nonzero_x.append(w_word)
            continue

        if len(nonzero_xs) > 1:
            more_than_one_nonzero_x.append(w_word)
            continue

        x_word, values = next(iter(nonzero_xs.items()))
        sorted_values = tuple(sorted(values))

        if len(values) != 1 or next(iter(values)) not in pm_one:
            one_nonzero_x_value_not_pm_one.append((w_word, x_word, sorted_values))
            continue

        value = next(iter(values))
        transposed_word = transpose_yamanouchi_word(w_word)
        if transposed_word == x_word:
            matching_pairs.append((w_word, x_word, value))
        else:
            mismatching_pairs.append((w_word, x_word, value, transposed_word))

    true_w_words = {w for w, _x, _v in matching_pairs}
    not_true_count = len(all_w_words) - len(true_w_words)

    print("Matching w_words and x_words")
    print("w_word\tx_word\tfinal_pairing_value")
    for w_word, x_word, value in matching_pairs:
        print(f"{w_word}\t{x_word}\t{value}")
    print()
    print(f"Total matching pairs: {len(matching_pairs)}")
    print(f"Total w_words for which this is not true: {not_true_count}")
    print()

    print("Other requested totals")
    print(
        "Total w_words with more than one x_word having nonzero final_pairing_value: "
        f"{len(more_than_one_nonzero_x)}"
    )
    print(
        "Total w_words with exactly one nonzero x_word but pairing value not +/-1: "
        f"{len(one_nonzero_x_value_not_pm_one)}"
    )
    print()

    print("Mismatches among w_words with exactly one nonzero x_word and value +/-1")
    print("w_word\tx_word\tfinal_pairing_value\ttranspose_yamanouchi_word")
    for w_word, x_word, value, transposed_word in mismatching_pairs:
        print(f"{w_word}\t{x_word}\t{value}\t{transposed_word}")
    print()
    print(
        "Number of w_words with exactly one nonzero +/-1 pairing whose x_word does not "
        f"match the transposed-tableau Yamanouchi word: {len(mismatching_pairs)}"
    )
    print()

    print("Audit")
    print(f"Total distinct w_words: {len(all_w_words)}")
    print(f"Total w_words with no nonzero x_word: {len(no_nonzero_x)}")
    print("w_words with no nonzero x_word")
    for w_word in no_nonzero_x:
        print(w_word)
    print(f"Duplicate nonzero rows for the same (w_word, x_word): {duplicate_nonzero_rows}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
