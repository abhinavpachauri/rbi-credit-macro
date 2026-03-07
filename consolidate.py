"""
RBI SIBC Consolidator
=====================
Merges all monthly SIBC Excel files into a single consolidated_long.csv.

Usage:
    python consolidate.py                   # scans current directory
    python consolidate.py --input-dir DIR   # scans a specific directory
    python consolidate.py file1.xlsx file2.xlsx ...  # explicit files

Picks up both RBI filename conventions:
    SIBC{DDMMYYYY}.xlsx        e.g. SIBC27022026.xlsx
    PR####SIBC{DDMMYY}.xlsx    e.g. PR2019SIBC300126.xlsx

Output: consolidated/consolidated_long.csv
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from parser import parse_file


def collect_files(input_dir: Path, explicit_files: list[Path]) -> list[Path]:
    if explicit_files:
        return sorted(explicit_files)
    seen = set()
    files = []
    for pattern in ("SIBC*.xlsx", "*SIBC*.xlsx"):
        for f in input_dir.glob(pattern):
            if f not in seen:
                seen.add(f)
                files.append(f)
    return sorted(files)


def consolidate(files: list[Path]) -> pd.DataFrame:
    """Parse all files and return a single deduplicated long-format DataFrame."""
    all_long = []

    for path in files:
        print(f"  Processing {path.name} ...", end=" ", flush=True)
        try:
            results = parse_file(path)
            for key, df in results.items():
                if key.endswith("_long") and not df.empty:
                    all_long.append(df)
            print("OK")
        except Exception as exc:
            print(f"ERROR: {exc}")

    if not all_long:
        print("[WARN] No data was parsed.")
        return pd.DataFrame()

    df = pd.concat(all_long, ignore_index=True)

    # Each file carries historical dates. Keep the most recently published
    # value for any (statement, code, date) overlap so later corrections win.
    df = (
        df
        .sort_values("report_date", ascending=False)
        .drop_duplicates(subset=["statement", "code", "sector", "date"], keep="first")
        .sort_values(["statement", "code", "date"])
        .reset_index(drop=True)
    )
    return df


def main():
    parser = argparse.ArgumentParser(description="Consolidate RBI SIBC Excel files")
    parser.add_argument("files", nargs="*", type=Path, help="Explicit xlsx files to process")
    parser.add_argument("--input-dir", type=Path, default=Path("."),
                        help="Directory to scan for SIBC*.xlsx files (default: .)")
    args = parser.parse_args()

    files = collect_files(args.input_dir, args.files)
    if not files:
        print(f"No SIBC*.xlsx files found in {args.input_dir}")
        sys.exit(1)

    print(f"\nFound {len(files)} file(s):")
    for f in files:
        print(f"  {f.name}")
    print()

    df = consolidate(files)
    if df.empty:
        sys.exit(1)

    out_path = Path("consolidated") / "consolidated_long.csv"
    out_path.parent.mkdir(exist_ok=True)
    df.to_csv(out_path, index=False)

    print(f"\nSaved: {out_path}  ({len(df)} rows)")
    print(f"  Date range : {df.date.min()} → {df.date.max()}")
    print(f"  Sectors    : {df.code.nunique()} unique codes")
    print(f"  Statements : {df.statement.unique().tolist()}")


if __name__ == "__main__":
    main()
