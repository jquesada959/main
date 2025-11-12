#!/usr/bin/python3
"""
compare_mac_baseline.py

Usage:
  python3 compare_mac_baseline.py [--baseline b1.csv b2.csv] [--compare file1.csv file2.csv ...]

Defaults are the filenames you provided. For each comparison file the script will create
<original_filename>_diff_vs_baseline.csv containing only rows whose MAC address is not
present in the combined baseline.

Matching is done by MAC address only (normalized). The script preserves all columns
from the original CSVs.
"""

import csv
import argparse
import re
from pathlib import Path
import sys
import glob


def normalize_mac(mac: str) -> str:
    if not mac:
        return ""
    # remove non-hex characters and lowercase
    cleaned = re.sub(r'[^0-9a-fA-F]', '', mac).lower()
    return cleaned


def find_mac_field(fieldnames):
    # prefer exact 'mac address', otherwise first field containing 'mac'
    lower_fields = [f.lower() for f in fieldnames]
    if 'mac address' in lower_fields:
        return fieldnames[lower_fields.index('mac address')]
    for i, f in enumerate(lower_fields):
        if 'mac' in f:
            return fieldnames[i]
    return None


def load_macs_from_csv(path: Path):
    macs = set()
    if not path.is_file():
        print(f"Warning: baseline file {path} not found, skipping.")
        return macs
    with path.open(newline='') as f:
        reader = csv.DictReader(f)
        mac_field = find_mac_field(reader.fieldnames or [])
        if not mac_field:
            print(f"Warning: no MAC column found in {path}, skipping.")
            return macs
        for row in reader:
            mac_raw = row.get(mac_field, '')
            mac = normalize_mac(mac_raw)
            if mac:
                macs.add(mac)
    return macs


def compare_file(path: Path, baseline_macs: set):
    if not path.is_file():
        print(f"Compare file {path} not found, skipping.")
        return None, 0, 0
    with path.open(newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        mac_field = find_mac_field(fieldnames)
        if not mac_field:
            print(f"No MAC field found in {path}. Skipping.")
            return None, 0, 0
        rows = list(reader)

    diff_rows = []
    for row in rows:
        mac_raw = row.get(mac_field, '')
        mac = normalize_mac(mac_raw)
        if not mac:
            continue
        if mac not in baseline_macs:
            diff_rows.append(row)

    out_path = path.with_name(path.stem + '_diff_vs_baseline' + path.suffix)
    if diff_rows:
        with out_path.open('w', newline='') as outf:
            writer = csv.DictWriter(outf, fieldnames=fieldnames)
            writer.writeheader()
            for r in diff_rows:
                writer.writerow(r)
        print(f"Wrote {len(diff_rows)} differing rows to {out_path}")
    else:
        print(f"No differing MACs found in {path}")
    return out_path, len(rows), len(diff_rows)


def main():
    parser = argparse.ArgumentParser(description='Compare MAC addresses against baseline CSVs')
    parser.add_argument('--baseline', nargs='*', metavar='BASE',
                        help='Baseline CSV files matching *_LON.BASE.csv')
    parser.add_argument('--compare', nargs='*', metavar='FILE',
                        help='Comparison CSV files matching *_LON.DAYTIME.csv')
    args = parser.parse_args()

    # If no baseline/compare provided, glob for files
    if not args.baseline:
        args.baseline = sorted(glob.glob('interfaces_and_mac_*_LON.BASE.csv'))
    if not args.compare:
        args.compare = sorted(glob.glob('interfaces_and_mac_*_LON.DAYTIME.csv'))

    baseline_paths = [Path(p) for p in args.baseline]
    compare_paths = [Path(p) for p in args.compare]

    baseline_macs = set()
    for bp in baseline_paths:
        macs = load_macs_from_csv(bp)
        print(f"Loaded {len(macs)} MACs from baseline {bp}")
        baseline_macs.update(macs)

    print(f"Total baseline MACs: {len(baseline_macs)}")

    summary = []
    for cp in compare_paths:
        out_path, total_rows, diff_count = compare_file(cp, baseline_macs)
        summary.append((cp, total_rows, diff_count, out_path))

    print('\nSummary:')
    for cp, total, diff, out in summary:
        print(f"{cp}: {diff} new MAC(s) out of {total} rows -> {out}")


if __name__ == '__main__':
    main()
