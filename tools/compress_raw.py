"""Nén các file data/raw/*.json thành .json.gz để tiết kiệm dung lượng.

Usage:
    python tools/compress_raw.py            # nén, giữ lại file .json gốc
    python tools/compress_raw.py --delete   # nén xong xóa file .json gốc
"""
from __future__ import annotations

import argparse
import gzip
import shutil
from pathlib import Path

RAW_DIR = Path("data/raw")


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def main() -> None:
    parser = argparse.ArgumentParser(description="Nén raw JSON files")
    parser.add_argument("--delete", action="store_true", help="Xóa file .json sau khi nén thành công")
    args = parser.parse_args()

    if not RAW_DIR.exists():
        print(f"Không có thư mục {RAW_DIR}, bỏ qua.")
        return

    files = sorted(RAW_DIR.glob("*.json"))
    if not files:
        print("Không có file .json nào cần nén.")
        return

    total_before = 0
    total_after = 0
    converted = 0
    for src in files:
        gz_path = src.with_suffix(".json.gz")

        if gz_path.exists():
            # Đã nén rồi - chỉ xóa file gốc nếu --delete
            if args.delete:
                src.unlink()
                print(f"[CLEAN] xóa {src.name} (.gz đã có)")
            else:
                print(f"[SKIP]  {gz_path.name} đã tồn tại")
            continue

        size_before = src.stat().st_size
        with src.open("rb") as f_in, gzip.open(gz_path, "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)
        size_after = gz_path.stat().st_size

        total_before += size_before
        total_after += size_after
        converted += 1

        ratio = (1 - size_after / size_before) * 100 if size_before else 0
        print(f"[OK]    {src.name} → {gz_path.name}  ({human_size(size_before)} → {human_size(size_after)}, -{ratio:.0f}%)")

        if args.delete:
            src.unlink()

    if converted:
        print()
        print(f"Tổng: nén {converted} file")
        print(f"  Trước: {human_size(total_before)}")
        print(f"  Sau:   {human_size(total_after)}")
        if total_before:
            saved = (1 - total_after / total_before) * 100
            print(f"  Tiết kiệm: {saved:.0f}% ({human_size(total_before - total_after)})")
        if not args.delete:
            print()
            print("Chạy lại với --delete để xóa file .json gốc sau khi xác nhận file .gz OK.")


if __name__ == "__main__":
    main()
