#!/usr/bin/env python3
"""
MPPE Diário Oficial — bulk name search.

Usage:
    python3 mppe_diario_search.py "Ana Joêmia Marques da Rocha" [--months 12] [--workers 4]
                                    [--out relatorio.json] [--start YYYY-MM-DD] [--end YYYY-MM-DD]

Pipeline:
    1. Map year/month folder IDs via Headless Delivery
    2. List all document editions in the date window
    3. Download PDFs in parallel (4 workers default)
    4. Extract text with PyPDF2 (delete PDF after extraction)
    5. Search with diacritic-insensitive, case-insensitive regex
    6. Write JSON to --out

Verified 2026-06-20 against portal.mppe.mp.br.
"""
import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.request
import gzip
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
BASE = "https://portal.mppe.mp.br"
ROOT_FOLDER_ID = 57418

# Try PyPDF2 from the Hermes venv shim
try:
    from PyPDF2 import PdfReader
except ImportError:
    py_user = "/Users/chlima/.hermes/home/Library/Python/3.9/lib/python/site-packages"
    if Path(py_user).exists():
        sys.path.insert(0, py_user)
        from PyPDF2 import PdfReader
    else:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "PyPDF2"], check=False)
        from PyPDF2 import PdfReader


def fetch_json(url: str) -> dict:
    """GET JSON, handling gzip manually (urllib 3.9 doesn't auto-decompress)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding", "").lower() == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw)


def fetch_all_years() -> list:
    data = fetch_json(f"{BASE}/o/headless-delivery/v1.0/document-folders/{ROOT_FOLDER_ID}"
                      f"/document-folders?sort=dateCreated%3Adesc&pageSize=50")
    return [{"id": it["id"], "label": it["name"], "date_created": it["dateCreated"]}
            for it in data.get("items", [])]


def fetch_all_months(year_id: int) -> list:
    data = fetch_json(f"{BASE}/o/headless-delivery/v1.0/document-folders/{year_id}"
                      f"/document-folders?sort=dateCreated%3Adasc&pageSize=20")
    return [{"id": it["id"], "label": it["name"], "date_created": it["dateCreated"]}
            for it in data.get("items", [])]


def fetch_all_docs(month_id: int) -> list:
    out, page = [], 1
    while True:
        data = fetch_json(f"{BASE}/o/headless-delivery/v1.0/document-folders/{month_id}"
                          f"/documents?sort=dateCreated%3Adesc&pageSize=50&page={page}")
        out.extend(data.get("items", []))
        if page >= data.get("lastPage", 1):
            break
        page += 1
        time.sleep(0.2)
    return out


def norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn").lower()


def build_pattern_ladder(name: str) -> list:
    """Generate a name-specific pattern ladder from a full name input.
    Returns list of NORMALIZED patterns, most specific first.
    """
    parts = name.strip().split()
    if len(parts) < 2:
        return [norm(re.escape(name))]
    pats = [
        r"\b" + r"\s+".join(re.escape(p) for p in parts) + r"\b",
        r"\b" + r"\s+".join(re.escape(p) for p in parts[1:]) + r"\b",
        r"\b" + re.escape(parts[0]) + r"\s+" + re.escape(parts[1]) + r"\b",
    ]
    if len(parts) >= 3:
        pats.append(r"\b" + re.escape(parts[0]) + r"\s+j\.?\s+"
                    + r"\s+".join(re.escape(p) for p in parts[2:]) + r"\b")
    return [norm(p) for p in pats]


def fetch_pdf(item, work: Path):
    uuid = item["externalReferenceCode"]
    cache = work / f"{uuid}.pdf"
    if cache.exists() and cache.stat().st_size > 1000:
        return cache
    url = item.get("contentUrl") or ""
    if not url.startswith("http"):
        url = BASE + url
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        if len(data) < 1000:
            return None
        cache.write_bytes(data)
        return cache
    except Exception as e:
        sys.stderr.write(f"  fetch error {uuid[:8]}: {e}\n")
        return None


def extract_text(pdf_path: Path, cache_dir: Path) -> str:
    cache = cache_dir / (pdf_path.stem + ".txt")
    if cache.exists():
        return cache.read_text(errors="replace")
    reader = PdfReader(str(pdf_path))
    chunks = []
    for p in reader.pages:
        try:
            chunks.append(p.extract_text() or "")
        except Exception:
            chunks.append("")
    text = "\n".join(chunks)
    cache.write_text(text, errors="replace")
    try:
        pdf_path.unlink()
    except Exception:
        pass
    return text


def process_one(item, patterns_norm, work: Path, cache_dir: Path):
    pdf = fetch_pdf(item, work)
    if not pdf:
        return None
    text = extract_text(pdf, cache_dir)
    nt = norm(text)
    hits = []
    seen = set()
    for pat in patterns_norm:
        for m in re.finditer(pat, nt):
            if m.start() in seen:
                continue
            seen.add(m.start())
            ctx_s = max(0, m.start() - 250)
            ctx_e = min(len(text), m.start() + len(m.group()) + 250)
            hits.append({
                "offset": m.start(),
                "matched": m.group(),
                "context": text[ctx_s:ctx_e].strip(),
            })
    if not hits:
        return None
    return {
        "item": {
            "uuid": item["externalReferenceCode"],
            "id": item.get("id"),
            "title": item.get("title"),
            "date_created": item.get("dateCreated"),
            "size_in_bytes": item.get("sizeInBytes"),
            "content_url": item.get("contentUrl"),
        },
        "match_count": len(hits),
        "hits": hits,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", help='Full name to search, e.g. "Ana Joêmia Marques da Rocha"')
    ap.add_argument("--months", type=int, default=12, help="Window in months back from today (default 12)")
    ap.add_argument("--start", help="Override start date YYYY-MM-DD")
    ap.add_argument("--end", help="Override end date YYYY-MM-DD (default today)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--work", default="/tmp/mppe-investigation/work",
                    help="Working dir for PDFs + text cache")
    ap.add_argument("--out", default=None, help="Output JSON path")
    args = ap.parse_args()

    if args.end:
        end = datetime.strptime(args.end, "%Y-%m-%d").date()
    else:
        end = datetime.now().date()
    if args.start:
        start = datetime.strptime(args.start, "%Y-%m-%d").date()
    else:
        start = end - timedelta(days=30 * args.months)

    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    cache_dir = work / "text"
    cache_dir.mkdir(exist_ok=True)

    print(f"[{datetime.now():%H:%M:%S}] Searching '{args.name}' in {start} -> {end} "
          f"(workers={args.workers})", flush=True)

    years = fetch_all_years()
    months = []
    for y in years:
        try:
            ms = fetch_all_months(y["id"])
        except Exception as e:
            sys.stderr.write(f"  months err {y['label']}: {e}\n")
            continue
        for m in ms:
            m["year"] = y["label"]
            months.append(m)
    print(f"[{datetime.now():%H:%M:%S}] {len(years)} years, {len(months)} months", flush=True)

    pdfs = []
    seen_uuids = set()
    for m in months:
        try:
            items = fetch_all_docs(m["id"])
        except Exception as e:
            sys.stderr.write(f"  docs err {m['label']}: {e}\n")
            continue
        for it in items:
            uuid = it.get("externalReferenceCode") or ""
            dc = (it.get("dateCreated") or "")[:10]
            if not dc or dc < str(start) or dc > str(end):
                continue
            if uuid in seen_uuids:
                continue
            seen_uuids.add(uuid)
            pdfs.append({**it, "month": m["label"], "year": m["year"]})
    print(f"[{datetime.now():%H:%M:%S}] {len(pdfs)} editions in window", flush=True)

    patterns_norm = build_pattern_ladder(args.name)
    print(f"[{datetime.now():%H:%M:%S}] Pattern ladder: {patterns_norm}", flush=True)

    results = []
    done = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(process_one, it, patterns_norm, work, cache_dir): it for it in pdfs}
        for fut in as_completed(futures):
            done += 1
            r = fut.result()
            if r:
                results.append(r)
            if done % 20 == 0 or r:
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                print(f"[{datetime.now():%H:%M:%S}] ({done}/{len(pdfs)}) "
                      f"matches={len(results)} rate={rate:.1f} PDFs/s", flush=True)

    results.sort(key=lambda r: r["item"].get("date_created") or "")

    summary = {
        "name": args.name,
        "start": str(start),
        "end": str(end),
        "editions_total": len(pdfs),
        "editions_with_match": len(results),
        "total_occurrences": sum(r["match_count"] for r in results),
        "generated_at": datetime.now().isoformat(),
        "results": results,
    }

    if args.out:
        out_path = Path(args.out)
    else:
        slug = norm(args.name).replace(" ", "_")
        out_path = work.parent / f"matches_{slug}.json"
    with out_path.open("w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\nDone. {len(results)} editions matched "
          f"({summary['total_occurrences']} occurrences). Saved to: {out_path}")


if __name__ == "__main__":
    main()
