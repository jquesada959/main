#!/usr/bin/python3
"""
Merge all *_diff_vs_baseline.csv files and write a combined CSV with unique MAC addresses.
First occurrence of a MAC wins (row preserved). MAC normalization removes non-hex chars
and lowercases for deduping.
"""
import csv
import re
from pathlib import Path
from datetime import datetime

WORKDIR = Path(__file__).parent
PATTERN = "*_diff_vs_baseline.csv"


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


def collect_diff_files():
    return sorted(WORKDIR.glob(PATTERN))


def merge_files(paths):
    seen = set()
    out_rows = []
    out_fieldnames = None
    for p in paths:
        with p.open(newline='') as f:
            reader = csv.DictReader(f)
            if out_fieldnames is None:
                out_fieldnames = list(reader.fieldnames or [])
                # add metadata fields
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
                # attach source metadata
                row['source_file'] = p.name
                # try to extract timestamp-like pattern from filename (YYYYMMDD_HHMMSS)
                import re as _re
                m = _re.search(r'(20\d{6}_\d{6})', p.name)
                row['source_timestamp'] = m.group(1) if m else ''
                out_rows.append(row)
    return out_fieldnames or [], out_rows


def main():
    files = collect_diff_files()
    if not files:
        print("No diff files found.")
        return
    print(f"Found {len(files)} files to process")
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
