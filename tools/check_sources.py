"""Health check toàn bộ URLs trong sources/*.json.

Phát hiện:
    OK       URL còn live, content giống bản đã crawl
    STALE    URL còn live nhưng content đã thay đổi → KB lỗi thời
    DEAD     URL trả 404/5xx
    REDIRECT URL chuyển hướng → bạn nên cập nhật sources/*.json

Usage:
    python tools/check_sources.py                       # chỉ report
    python tools/check_sources.py --topic kubernetes    # 1 topic
    python tools/check_sources.py --auto-update         # tự re-ingest stale
    python tools/check_sources.py --json                # output JSON cho cron

Best-effort: lỗi network, timeout hoặc parse được report là DEAD/UNKNOWN, không fatal.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Cho phép chạy `python tools/check_sources.py` từ project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import httpx  # noqa: E402

from crawler.fetch_data import DEFAULT_HEADERS, _build_doc_id, _is_url  # noqa: E402
from processor.cleaner import clean_document  # noqa: E402

SOURCES_DIR = Path("sources")
DATA_RAW_DIR = Path("data/raw")
TIMEOUT = 15.0


# ANSI colors cho terminal report
class C:
    OK = "\033[92m"
    WARN = "\033[93m"
    ERR = "\033[91m"
    DIM = "\033[90m"
    RESET = "\033[0m"


@dataclass(slots=True)
class CheckResult:
    location: str
    topic: str
    title: str
    status: str  # OK | STALE | DEAD | REDIRECT | UNKNOWN
    detail: str = ""
    final_url: str | None = None  # cho REDIRECT
    http_status: int | None = None
    diff_chars: int | None = None  # số ký tự khác nhau khi STALE


@dataclass(slots=True)
class Summary:
    total: int = 0
    ok: int = 0
    stale: int = 0
    dead: int = 0
    redirect: int = 0
    unknown: int = 0
    results: list[CheckResult] = field(default_factory=list)


def _content_hash(text: str) -> str:
    """Hash content để so sánh. Normalize whitespace để bỏ qua thay đổi cosmetic."""
    normalized = " ".join(text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _read_stored_raw(doc_id: str) -> dict | None:
    """Đọc raw payload đã lưu (.json.gz preferred, fallback .json)."""
    gz = DATA_RAW_DIR / f"{doc_id}.json.gz"
    if gz.exists():
        with gzip.open(gz, "rt", encoding="utf-8") as f:
            return json.load(f)
    plain = DATA_RAW_DIR / f"{doc_id}.json"
    if plain.exists():
        return json.loads(plain.read_text(encoding="utf-8"))
    return None


def _check_one(spec: dict[str, Any]) -> CheckResult:
    location = spec["location"]
    topic = spec.get("topic", "general")
    title = spec.get("title", location)
    doc_id = _build_doc_id(location, topic)

    if not _is_url(location):
        # Local file - check tồn tại + hash
        path = Path(location)
        if not path.exists():
            return CheckResult(location, topic, title, "DEAD", "File không tồn tại")
        return CheckResult(location, topic, title, "OK", "Local file")

    # URL: HEAD trước để check status nhanh, GET nếu cần content diff
    try:
        with httpx.Client(
            follow_redirects=False, timeout=TIMEOUT, headers=DEFAULT_HEADERS
        ) as client:
            head = client.head(location)
    except Exception as exc:
        return CheckResult(location, topic, title, "UNKNOWN", f"Network: {exc}")

    if head.status_code in (301, 302, 307, 308):
        final = head.headers.get("location", "")
        return CheckResult(
            location, topic, title, "REDIRECT",
            f"→ {final}", final_url=final, http_status=head.status_code,
        )
    if head.status_code >= 400:
        return CheckResult(
            location, topic, title, "DEAD",
            f"HTTP {head.status_code}", http_status=head.status_code,
        )

    # Live URL → so sánh content với bản đã lưu
    stored = _read_stored_raw(doc_id)
    if stored is None:
        return CheckResult(
            location, topic, title, "OK",
            "URL live (chưa từng ingest)", http_status=head.status_code,
        )

    try:
        with httpx.Client(
            follow_redirects=True, timeout=TIMEOUT, headers=DEFAULT_HEADERS
        ) as client:
            resp = client.get(location)
    except Exception as exc:
        return CheckResult(location, topic, title, "UNKNOWN", f"GET fail: {exc}")

    # Compare cleaned content (fair so sánh - HTML wrapper thường hay đổi không cần care)
    new_clean = clean_document(
        {**stored, "content": resp.text},
        content_type=resp.headers.get("content-type", ""),
    )
    old_clean = clean_document(stored, content_type="")

    if not new_clean or not old_clean:
        return CheckResult(
            location, topic, title, "UNKNOWN",
            "Không clean được nội dung",
            http_status=head.status_code,
        )

    new_hash = _content_hash(new_clean["content"])
    old_hash = _content_hash(old_clean["content"])

    if new_hash == old_hash:
        return CheckResult(
            location, topic, title, "OK",
            "Không đổi", http_status=head.status_code,
        )

    diff = abs(len(new_clean["content"]) - len(old_clean["content"]))
    return CheckResult(
        location, topic, title, "STALE",
        f"Content thay đổi (~{diff} ký tự khác)",
        http_status=head.status_code,
        diff_chars=diff,
    )


def _icon(status: str) -> str:
    return {
        "OK": f"{C.OK}✓{C.RESET}",
        "STALE": f"{C.WARN}⚠{C.RESET}",
        "DEAD": f"{C.ERR}✗{C.RESET}",
        "REDIRECT": f"{C.WARN}↪{C.RESET}",
        "UNKNOWN": f"{C.DIM}?{C.RESET}",
    }.get(status, "·")


def _print_result(r: CheckResult) -> None:
    loc = r.location[:80]
    extra = f" {C.DIM}[{r.detail}]{C.RESET}" if r.detail else ""
    print(f"{_icon(r.status)} {loc:<80}{extra}")


def load_sources(topic: str | None = None) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    if topic:
        path = SOURCES_DIR / f"{topic}.json"
        if not path.exists():
            print(f"Không tìm thấy topic: {path}", file=sys.stderr)
            sys.exit(1)
        sources.extend(json.loads(path.read_text(encoding="utf-8")))
    else:
        for path in sorted(SOURCES_DIR.glob("*.json")):
            try:
                items = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(items, list):
                    sources.extend(items)
            except json.JSONDecodeError:
                pass
    return sources


def check_sources(topic: str | None = None) -> Summary:
    sources = load_sources(topic)
    summary = Summary(total=len(sources))
    print(f"Kiểm tra {len(sources)} URLs...\n")
    for spec in sources:
        result = _check_one(spec)
        summary.results.append(result)
        _print_result(result)

        if result.status == "OK":
            summary.ok += 1
        elif result.status == "STALE":
            summary.stale += 1
        elif result.status == "DEAD":
            summary.dead += 1
        elif result.status == "REDIRECT":
            summary.redirect += 1
        else:
            summary.unknown += 1
    return summary


def _print_summary(s: Summary) -> None:
    print()
    print(f"{C.OK}OK:        {s.ok}{C.RESET}")
    print(f"{C.WARN}STALE:     {s.stale}{C.RESET} (content đã thay đổi)")
    print(f"{C.ERR}DEAD:      {s.dead}{C.RESET} (404/5xx)")
    print(f"{C.WARN}REDIRECT:  {s.redirect}{C.RESET} (URL chuyển hướng)")
    print(f"{C.DIM}UNKNOWN:   {s.unknown}{C.RESET} (không check được)")
    print(f"TOTAL:     {s.total}")


def auto_update(stale_results: list[CheckResult]) -> None:
    """Re-ingest những URLs có status STALE."""
    if not stale_results:
        print("Không có URL stale nào cần update.")
        return

    print(f"\n{C.WARN}Re-ingesting {len(stale_results)} stale URLs...{C.RESET}\n")
    sources_to_update = [
        {"location": r.location, "topic": r.topic, "title": r.title, "source": "website"}
        for r in stale_results
    ]
    from crawler.fetch_data import crawl_sources
    from processor.chunker import process_documents
    from processor.embedder import embed_and_store

    documents = crawl_sources(sources_to_update)
    if not documents:
        print("Không có document nào re-crawl thành công.")
        return
    chunks = process_documents(documents)
    embed_and_store(chunks)
    print(f"\n{C.OK}Đã re-ingest {len(documents)} docs, {len(chunks)} chunks.{C.RESET}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Health check sources/*.json")
    parser.add_argument("--topic", help="Chỉ check 1 topic (vd: kubernetes)")
    parser.add_argument(
        "--auto-update", action="store_true",
        help="Tự re-ingest STALE URLs vào ChromaDB",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output dạng JSON (dùng cho cron / pipeline)",
    )
    args = parser.parse_args()

    summary = check_sources(topic=args.topic)

    if args.json:
        print(json.dumps({
            "total": summary.total,
            "ok": summary.ok,
            "stale": summary.stale,
            "dead": summary.dead,
            "redirect": summary.redirect,
            "unknown": summary.unknown,
            "results": [
                {
                    "location": r.location,
                    "topic": r.topic,
                    "title": r.title,
                    "status": r.status,
                    "detail": r.detail,
                    "final_url": r.final_url,
                    "http_status": r.http_status,
                    "diff_chars": r.diff_chars,
                }
                for r in summary.results
            ],
        }, ensure_ascii=False, indent=2))
        return

    _print_summary(summary)

    if args.auto_update:
        stale = [r for r in summary.results if r.status == "STALE"]
        auto_update(stale)

    # Exit code != 0 nếu có DEAD links (CI-friendly)
    if summary.dead > 0:
        sys.exit(2)


if __name__ == "__main__":
    main()
