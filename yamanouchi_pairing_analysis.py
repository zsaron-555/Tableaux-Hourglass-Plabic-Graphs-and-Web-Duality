#!/usr/bin/env python3
"""
yamanouchi_pairing_analysis.py

Analyze a TSV file of (w_word, x_word, final_pairing_value) triples.

Usage
-----
    python3 yamanouchi_pairing_analysis.py path/to/data.tsv

Run from anywhere, on any machine: the input file path is taken from the
command line, nothing is hardcoded. No third-party / Sage dependency is
required -- everything here is plain Python 3 standard library.

What this script does
----------------------
The TSV must have (at least) three columns, identified by header name
(not position):

    w_word               -> "B" in the problem statement
    x_word                -> "C"
    final_pairing_value    -> "H"

For every distinct w_word we look at all x_words paired with it that have
a NONZERO final_pairing_value.

  * Set A = w_words with exactly one such (x_word, value) pair.
  * Set B = the subset of A whose value is exactly 1 or -1.

For every w_word in B we:
  1. Interpret w_word as a Yamanouchi word.
  2. Convert it to a standard Young tableau (SYT).
  3. Transpose that SYT.
  4. Convert the transposed SYT back into a Yamanouchi word.
  5. Check whether that word equals x_word.

We then print the six requested reports.

Yamanouchi word <-> SYT bijection used here
--------------------------------------------
A Yamanouchi (lattice/ballot) word w = w_1 w_2 ... w_n over the alphabet
{1, 2, ...} corresponds to the unique SYT T of shape lambda = content(w)
obtained by placing the label i (for i = 1, ..., n, in increasing order)
at the end of row w_i of T. Reading this back off (recording, for each
label i, which row of T it sits in) recovers w. This is a standard
bijection between Yamanouchi words of content lambda and SYT(lambda), and
is exactly the "interpret as Yamanouchi word / convert to SYT" and
"convert SYT back to Yamanouchi word" operations requested.
"""

import argparse
import csv
import sys
from fractions import Fraction


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------

def parse_word(s):
    """Parse a w_word / x_word cell into a tuple of ints.

    Accepts comma-separated ("1,2,1,1"), whitespace-separated ("1 2 1 1"),
    or a bare run of single digits ("1211").
    """
    s = s.strip()
    if not s:
        return ()
    if ',' in s:
        parts = [p for p in s.split(',') if p.strip() != '']
        return tuple(int(p.strip()) for p in parts)
    if any(ch.isspace() for ch in s):
        return tuple(int(p) for p in s.split())
    # bare run of digits, e.g. "1211" -> (1, 2, 1, 1)
    return tuple(int(ch) for ch in s)


def parse_value(s):
    """Parse the final_pairing_value cell into an exact Fraction."""
    s = s.strip()
    return Fraction(s)


# --------------------------------------------------------------------------
# Yamanouchi word <-> SYT
# --------------------------------------------------------------------------

def yamanouchi_to_syt(word):
    """word: tuple of ints (1-indexed row labels), length n.
    Returns the SYT (list of rows, each a list of ints) built by placing
    i at the end of row word[i-1], for i = 1..n.
    """
    if not word:
        return []
    rows = {}
    for i, r in enumerate(word, start=1):
        rows.setdefault(r, []).append(i)
    max_row = max(rows.keys())
    return [rows.get(r, []) for r in range(1, max_row + 1)]


def syt_to_yamanouchi(T):
    """Inverse of yamanouchi_to_syt: for each label i, record which row
    of T it is in."""
    n = sum(len(row) for row in T)
    pos = {}
    for row_index, row in enumerate(T, start=1):
        for v in row:
            pos[v] = row_index
    return tuple(pos[i] for i in range(1, n + 1))


def transpose_tableau(T):
    """Standard transpose of a Young-diagram-shaped tableau."""
    if not T:
        return []
    max_cols = len(T[0])
    new_T = []
    for j in range(max_cols):
        col = [row[j] for row in T if j < len(row)]
        new_T.append(col)
    return new_T


def word_to_str(word):
    """Render a parsed word tuple back into a compact digit string for
    display / comparison purposes."""
    return ''.join(str(x) for x in word)


def transposed_yamanouchi_of(w_word_tuple):
    """Full pipeline: Yamanouchi word -> SYT -> transpose -> Yamanouchi word."""
    T = yamanouchi_to_syt(w_word_tuple)
    T_transpose = transpose_tableau(T)
    return syt_to_yamanouchi(T_transpose)


# --------------------------------------------------------------------------
# Main analysis
# --------------------------------------------------------------------------

def load_rows(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f, delimiter='\t')
        fieldnames = reader.fieldnames
        if fieldnames is None:
            raise ValueError("Could not read a header row from the TSV file.")

        required = ['w_word', 'x_word', 'final_pairing_value']
        missing = [c for c in required if c not in fieldnames]
        if missing:
            raise ValueError(
                "Missing required column(s): {}. Found columns: {}".format(
                    missing, fieldnames
                )
            )

        rows = []
        for line_num, row in enumerate(reader, start=2):
            w_raw = row['w_word']
            x_raw = row['x_word']
            h_raw = row['final_pairing_value']
            if w_raw is None or x_raw is None or h_raw is None:
                continue
            w_raw = w_raw.strip()
            x_raw = x_raw.strip()
            h_raw = h_raw.strip() if h_raw is not None else ''
            if w_raw == '' or x_raw == '' or h_raw == '':
                continue
            try:
                value = parse_value(h_raw)
            except Exception:
                print(
                    "Warning: could not parse final_pairing_value {!r} on "
                    "line {}; skipping row.".format(h_raw, line_num),
                    file=sys.stderr,
                )
                continue
            rows.append((w_raw, x_raw, value))
    return rows


def group_by_w(rows):
    """Group nonzero-valued (x_word, value) pairs by w_word (original
    string form, first-seen formatting preserved)."""
    groups = {}
    for w_raw, x_raw, value in rows:
        if value == 0:
            continue
        groups.setdefault(w_raw, []).append((x_raw, value))
    return groups


def print_triples(title, triples):
    print(title)
    if not triples:
        print("  (none)")
    else:
        for w, x, v in triples:
            print("  ({}, {}, {})".format(w, x, v))
    print("Total: {}".format(len(triples)))
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Analyze w_word/x_word/final_pairing_value pairings in a TSV file."
    )
    parser.add_argument("tsv_path", help="Path to the input .tsv file")
    args = parser.parse_args()

    rows = load_rows(args.tsv_path)
    groups = group_by_w(rows)

    # A: w_words with exactly one nonzero-valued x_word.
    A = []          # list of (w, x, value)
    multi = []      # list of (w, x, value) for w_words with >1 nonzero x_word
    for w_raw, pairs in groups.items():
        if len(pairs) == 1:
            x_raw, value = pairs[0]
            A.append((w_raw, x_raw, value))
        elif len(pairs) > 1:
            for x_raw, value in pairs:
                multi.append((w_raw, x_raw, value))

    # B: subset of A with value 1 or -1.
    B = [(w, x, v) for (w, x, v) in A if v == 1 or v == -1]
    # A-but-not-B: single nonzero x_word, but value not 1 or -1.
    single_not_pm1 = [(w, x, v) for (w, x, v) in A if not (v == 1 or v == -1)]

    matches = []      # B entries where transposed-Yamanouchi(w) == x
    mismatches = []    # B entries where it does not

    for w_raw, x_raw, value in B:
        w_tuple = parse_word(w_raw)
        x_tuple = parse_word(x_raw)
        predicted = transposed_yamanouchi_of(w_tuple)
        if predicted == x_tuple:
            matches.append((w_raw, x_raw, value))
        else:
            mismatches.append((w_raw, x_raw, value))

    # ---------------- Reports ----------------

    print_triples(
        "1) w_words in B whose transposed-tableau Yamanouchi word MATCHES x_word:",
        matches,
    )

    print_triples(
        "2) w_words in B whose transposed-tableau Yamanouchi word does NOT match x_word:",
        mismatches,
    )

    print_triples(
        "3) w_words with exactly one nonzero-valued x_word (set A):",
        A,
    )

    print_triples(
        "4) w_words with more than one nonzero-valued x_word:",
        multi,
    )

    print_triples(
        "5) w_words with exactly one nonzero-valued x_word, but that value "
        "is not 1 or -1:",
        single_not_pm1,
    )

if __name__ == "__main__":
    main()
