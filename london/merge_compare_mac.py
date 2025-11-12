#!/usr/bin/python3
"""
merge_compare_mac.py

- Compares MAC addresses in --compare CSVs (or *_LON.DAYTIME.csv) against --baseline CSVs (or *_LON.BASE.csv),
  writing *_diff_vs_baseline.csv for each compare file.
- Then merges all *_diff_vs_baseline.csv files into a single deduplicated CSV with source metadata.
"""
import csv
import argparse
import re
from pathlib import Path
from datetime import datetime
import glob

WORKDIR = Path(__file__).parent

# --- MAC normalization and helpers ---
def normalize_mac(mac: str) -> str:
    if not mac:
        return ""
    return re.sub(r'[^0-9a-fA-F]', '', mac).lower()

def find_mac_field(fieldnames):
    lower = [f.lower() for f in (fieldnames or [])]
    if 'mac address' in lower:
        return fieldnames[lower.index('mac address')]
    for i, f in enumerate(lower):
        if 'mac' in f:
            return fieldnames[i]
    return None

# --- Step 1: Compare and write *_diff_vs_baseline.csv ---
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

# --- Step 2: Merge all *_diff_vs_baseline.csv files ---
def collect_diff_files():
    return sorted(WORKDIR.glob('*_diff_vs_baseline.csv'))

def merge_files(paths):
    seen = set()
    out_rows = []
    out_fieldnames = None
    for p in paths:
        with p.open(newline='') as f:
            reader = csv.DictReader(f)
            if out_fieldnames is None:
                out_fieldnames = list(reader.fieldnames or [])
                out_fieldnames.extend(['source_file', 'source_timestamp'])
            mac_field = find_mac_field(reader.fieldnames)
            if not mac_field:
                print(f"Skipping {p}: no mac field")
                continue
            for row in reader:
                mac = normalize_mac(row.get(mac_field, ''))
                if not mac:
                    continue
                if mac in seen:
                    continue
                seen.add(mac)
                row['source_file'] = p.name
                m = re.search(r'(20\d{6}_\d{6})', p.name)
                row['source_timestamp'] = m.group(1) if m else ''
                out_rows.append(row)
    return out_fieldnames or [], out_rows

def main():
    parser = argparse.ArgumentParser(description='Compare MACs to baseline and merge unique diffs')
    parser.add_argument('--baseline', nargs='*', metavar='BASE', help='Baseline CSVs (default *_LON.BASE.csv)')
    parser.add_argument('--compare', nargs='*', metavar='FILE', help='Compare CSVs (default *_LON.DAYTIME.csv)')
    args = parser.parse_args()

    # Step 1: Compare
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

    # Step 2: Merge
    files = collect_diff_files()
    if not files:
        print("No diff files found.")
        return
    print(f"\nFound {len(files)} diff files to merge")
    fieldnames, rows = merge_files(files)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path = WORKDIR / f"combined_unique_macs_{timestamp}.csv"
    with out_path.open('w', newline='') as outf:
        writer = csv.DictWriter(outf, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    print(f"Wrote {len(rows)} unique MAC rows to {out_path}")

if __name__ == '__main__':
    main()
