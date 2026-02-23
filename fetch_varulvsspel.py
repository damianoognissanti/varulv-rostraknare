#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_varulvsspel.py  (Kaptenens snåla sync)
Mål:
- Synka lokala trådbackuper mot rollspel.nu (Varulvsspel) med minsta möjliga trafik.
- Använd forumlistan som "change detector" (time[data-timestamp]) så vi skippar trådar som inte ändrats.
- För trådar som ändrats: ladda bara det som behövs:
    * om nya sidor tillkommit: hämta om lokala sista sidan X och hämta X+1..Y
    * om inga nya sidor: conditional GET av pageX (ETag/Last-Modified om möjligt), annars hash av rensad HTML
- Skriv ut lista över ändrade trådar till: data/_changed_threads.json
- Vid --limit-threads N: hämta bara så många forumlist-sidor som behövs (20 trådar per sida ungefär).
  Ex: --limit-threads 5 -> bara första forum-sidan.
Krav:
  pip install requests beautifulsoup4 urllib3
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
# ----------------------------
# Konfig
# ----------------------------
BASE_URL = "https://www.rollspel.nu"
FORUM_PATH = "/forums/varulvsspel.81/"
OUTPUT_DIR_DEFAULT = "data"
USER_AGENT = "VarulvScraperBot/2.1 (damogn på forumet)"
DEFAULT_DELAY = 1.25     # sekunder
DEFAULT_TIMEOUT = 30     # sekunder
# Antal trådar per forumsida (XenForo brukar ligga runt 20)
THREADS_PER_FORUM_PAGE = 20
# Fil för att tala om för build_archive.py vilka trådar som ändrats
CHANGED_THREADS_FILENAME = "_changed_threads.json"
# ----------------------------
# HTML-rensning (för stabil hash)
# ----------------------------
_CLEAN_PATTERNS = [
    re.compile(r'data-csrf="[^"]+"'),
    re.compile(r'name="_xfToken"\s+value="[^"]+"'),
    re.compile(r"csrf:\s*'[^']+'"),
    re.compile(r"\bnow:\s*\d+\b"),
    re.compile(r'data-lb-trigger="[^"]*?_xfUid[^"]*"'),
    re.compile(r'data-lb-id="[^"]*?_xfUid[^"]*"'),
    re.compile(r'js-lbImage-_xfUid[^"\s>]*'),
    re.compile(r'_xfUid-\d+-\d+'),
    # Tidsstämplar kan variera i vissa block
    re.compile(r'data-timestamp="\d+"'),
]
def clean_html(text: str) -> str:
    out_lines: List[str] = []
    for line in text.splitlines():
        for pat in _CLEAN_PATTERNS:
            line = pat.sub("", line)
        out_lines.append(line.strip())
    return "\n".join(out_lines)
def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
# ----------------------------
# Datamodell
# ----------------------------
@dataclass
class ThreadFromForumList:
    slug_id: str
    title: str
    base_url: str
    latest_ts: int
    last_page_hint: int
# ----------------------------
# HTTP-session med retries
# ----------------------------
def build_session() -> requests.Session:
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "sv-SE,sv;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
    })
    retry = Retry(
        total=6,
        connect=6,
        read=6,
        backoff_factor=1.2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    return sess
def polite_sleep(delay: float) -> None:
    if delay and delay > 0:
        time.sleep(delay)
def fetch_html(
    sess: requests.Session,
    url: str,
    timeout: int,
    delay: float,
    conditional_headers: Optional[Dict[str, str]] = None,
) -> Tuple[int, Optional[str], Dict[str, str]]:
    """
    Returnerar: (status_code, html_or_None, hdrs)
    Vid 304 => html_or_None=None.
    """
    headers = {}
    if conditional_headers:
        headers.update(conditional_headers)
    res = sess.get(url, headers=headers, timeout=timeout)
    polite_sleep(delay)
    hdrs: Dict[str, str] = {}
    for k in ["ETag", "Last-Modified"]:
        if k in res.headers:
            hdrs[k] = res.headers[k]
    if res.status_code == 304:
        return 304, None, hdrs
    if res.status_code != 200:
        return res.status_code, None, hdrs
    res.encoding = res.encoding or "utf-8"
    return 200, res.text, hdrs
# ----------------------------
# Parse: forumlistan
# ----------------------------
def parse_forum_last_page_number(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    inp = soup.select_one("input.js-pageJumpPage")
    if inp and inp.has_attr("max"):
        try:
            return int(inp["max"])
        except ValueError:
            pass
    last = soup.select_one("a.pageNavSimple-el--last[href]")
    if last:
        m = re.search(r"/page-(\d+)", last["href"])
        if m:
            return int(m.group(1))
    txt = soup.get_text(" ", strip=True)
    m = re.search(r"\b(\d+)\s+of\s+(\d+)\b", txt)
    if m:
        return int(m.group(2))
    return 1
def normalize_thread_slug_id(thread_href: str) -> Optional[str]:
    m = re.search(r"/threads/([^/]+?\.\d+)", thread_href)
    if not m:
        return None
    return m.group(1)
def thread_base_url_from_slug(slug_id: str) -> str:
    return urljoin(BASE_URL, f"/threads/{slug_id}/")
def parse_forum_threads(html: str) -> List[ThreadFromForumList]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[ThreadFromForumList] = []
    for item in soup.select("div.structItem.structItem--thread"):
        # Trådlänk
        title_a = None
        for a in item.select("div.structItem-title a[href]"):
            href = a.get("href", "")
            if "/threads/" in href:
                title_a = a
                break
        if not title_a:
            continue
        href = title_a.get("href", "")
        slug_id = normalize_thread_slug_id(href)
        if not slug_id:
            continue
        title = title_a.get_text(" ", strip=True)
        base_url = thread_base_url_from_slug(slug_id)
        # Latest timestamp (change detector)
        latest_time = item.select_one("time.structItem-latestDate[data-timestamp]")
        if not latest_time:
            latest_time = item.select_one("div.structItem-cell--latest time[data-timestamp]")
        if latest_time and latest_time.has_attr("data-timestamp"):
            try:
                latest_ts = int(latest_time["data-timestamp"])
            except ValueError:
                latest_ts = 0
        else:
            latest_ts = 0  # hellre synka än missa
        # last_page_hint från pageJump (de tre sista siffrorna)
        last_page_hint = 1
        nums: List[int] = []
        for a in item.select("span.structItem-pageJump a"):
            t = a.get_text(strip=True)
            if t.isdigit():
                nums.append(int(t))
        if nums:
            last_page_hint = max(nums)
        out.append(ThreadFromForumList(
            slug_id=slug_id,
            title=title,
            base_url=base_url,
            latest_ts=latest_ts,
            last_page_hint=last_page_hint
        ))
    return out
def crawl_forum(
    sess: requests.Session,
    timeout: int,
    delay: float,
    limit_threads: int = 0
) -> Tuple[int, List[ThreadFromForumList]]:
    """
    Hämtar forumlistan och returnerar (forum_last_page, threads_sorted_by_latest).
    Vid limit_threads: hämtar bara så många forumlist-sidor som behövs.
    """
    first_url = urljoin(BASE_URL, FORUM_PATH)
    status, html, _ = fetch_html(sess, first_url, timeout=timeout, delay=delay)
    if status != 200 or html is None:
        raise RuntimeError(f"Kunde inte hämta forumsidan: {first_url} (status {status})")
    forum_last_page = parse_forum_last_page_number(html)
    if limit_threads and limit_threads > 0:
        pages_needed = max(1, math.ceil(limit_threads / THREADS_PER_FORUM_PAGE))
        forum_pages_to_fetch = min(forum_last_page, pages_needed)
    else:
        forum_pages_to_fetch = forum_last_page
    threads: List[ThreadFromForumList] = []
    threads.extend(parse_forum_threads(html))
    for page in range(2, forum_pages_to_fetch + 1):
        url = urljoin(BASE_URL, f"{FORUM_PATH}page-{page}")
        status, html, _ = fetch_html(sess, url, timeout=timeout, delay=delay)
        if status != 200 or html is None:
            print(f"[VARNING] Kunde inte hämta forum page-{page} (status {status}). Fortsätter.", file=sys.stderr)
            continue
        threads.extend(parse_forum_threads(html))
    # Deduplicera (stickies kan dyka upp på flera ställen ibland)
    uniq: Dict[str, ThreadFromForumList] = {}
    for t in threads:
        prev = uniq.get(t.slug_id)
        if not prev or t.latest_ts >= prev.latest_ts:
            uniq[t.slug_id] = t
    threads2 = list(uniq.values())
    threads2.sort(key=lambda t: t.latest_ts, reverse=True)
    if limit_threads and limit_threads > 0:
        threads2 = threads2[:limit_threads]
    return forum_last_page, threads2
# ----------------------------
# Parse: trådnav (om vi behöver verifiera Y)
# ----------------------------
def parse_thread_last_page_number(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    inp = soup.select_one("input.js-pageJumpPage")
    if inp and inp.has_attr("max"):
        try:
            return int(inp["max"])
        except ValueError:
            pass
    last = soup.select_one("a.pageNavSimple-el--last[href]")
    if last:
        m = re.search(r"/page-(\d+)", last["href"])
        if m:
            return int(m.group(1))
    txt = soup.get_text(" ", strip=True)
    m = re.search(r"\b(\d+)\s+of\s+(\d+)\b", txt)
    if m:
        return int(m.group(2))
    return 1
def thread_page_url(base_url: str, page_num: int) -> str:
    if page_num <= 1:
        return base_url
    if not base_url.endswith("/"):
        base_url += "/"
    return urljoin(base_url, f"page-{page_num}")
def verify_thread_identity(html: str, slug_id: str) -> bool:
    if slug_id in html:
        return True
    soup = BeautifulSoup(html, "html.parser")
    canon = soup.select_one("link[rel='canonical'][href]")
    if canon and slug_id in canon["href"]:
        return True
    return False
# ----------------------------
# Lokala filer + index/meta
# ----------------------------
def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)
def list_local_pages(thread_dir: str) -> List[int]:
    nums: List[int] = []
    if not os.path.isdir(thread_dir):
        return nums
    for fn in os.listdir(thread_dir):
        m = re.fullmatch(r"page(\d+)\.html", fn)
        if m:
            nums.append(int(m.group(1)))
    return sorted(nums)
def local_last_page(thread_dir: str) -> int:
    nums = list_local_pages(thread_dir)
    return nums[-1] if nums else 0
def index_path(output_dir: str) -> str:
    return os.path.join(output_dir, "_sync_index.json")
def load_index(output_dir: str) -> Dict:
    p = index_path(output_dir)
    if not os.path.exists(p):
        return {"version": 1, "forum": {}, "threads": {}}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)
def save_index(output_dir: str, idx: Dict) -> None:
    p = index_path(output_dir)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, p)
def thread_meta_path(thread_dir: str) -> str:
    return os.path.join(thread_dir, "_meta.json")
def load_thread_meta(thread_dir: str) -> Dict:
    p = thread_meta_path(thread_dir)
    if not os.path.exists(p):
        return {"version": 1, "pages": {}, "last_known_thread_last_page": None}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)
def save_thread_meta(thread_dir: str, meta: Dict) -> None:
    p = thread_meta_path(thread_dir)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, p)
def write_page(thread_dir: str, page_num: int, html: str) -> str:
    p = os.path.join(thread_dir, f"page{page_num}.html")
    with open(p, "w", encoding="utf-8") as f:
        f.write(html)
    return p
def update_page_meta(meta: Dict, page_num: int, html: str, hdrs: Dict[str, str]) -> None:
    cleaned = clean_html(html)
    entry = meta.setdefault("pages", {}).setdefault(str(page_num), {})
    entry["sha256_cleaned"] = sha256_text(cleaned)
    if "ETag" in hdrs:
        entry["etag"] = hdrs["ETag"]
    if "Last-Modified" in hdrs:
        entry["last_modified"] = hdrs["Last-Modified"]
def conditional_headers_for_page(meta: Dict, page_num: int) -> Dict[str, str]:
    entry = meta.get("pages", {}).get(str(page_num), {})
    headers: Dict[str, str] = {}
    if "etag" in entry:
        headers["If-None-Match"] = entry["etag"]
    if "last_modified" in entry:
        headers["If-Modified-Since"] = entry["last_modified"]
    return headers
def save_changed_threads(output_dir: str, slugs: List[str]) -> None:
    path = os.path.join(output_dir, CHANGED_THREADS_FILENAME)
    obj = {"builtAt": int(time.time()), "slugs": sorted(set(slugs))}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
# ----------------------------
# Kärna: synka en tråd (returnerar True om vi skrev någon sida)
# ----------------------------
def sync_thread(
    sess: requests.Session,
    output_dir: str,
    idx: Dict,
    t: ThreadFromForumList,
    timeout: int,
    delay: float,
) -> bool:
    thread_dir = os.path.join(output_dir, t.slug_id)
    ensure_dir(thread_dir)
    meta = load_thread_meta(thread_dir)
    thread_state = idx.setdefault("threads", {}).setdefault(t.slug_id, {})
    last_seen_latest_ts = thread_state.get("latest_ts", None)
    # Om latest_ts matchar och inte 0 -> helt skip (0 requests mot tråden)
    if last_seen_latest_ts is not None and int(last_seen_latest_ts) == int(t.latest_ts) and t.latest_ts != 0:
        return False
    did_write = False
    X = local_last_page(thread_dir)
    Y = max(1, int(t.last_page_hint))
    # Om ny tråd lokalt: hämta page1..Y
    if X == 0:
        print(f"  [+] Ny tråd lokalt: {t.slug_id}")
        for page in range(1, Y + 1):
            url = thread_page_url(t.base_url, page)
            status, html, hdrs = fetch_html(sess, url, timeout=timeout, delay=delay)
            if status != 200 or html is None:
                print(f"    [VARNING] page{page} status {status}, stoppar tråden.", file=sys.stderr)
                break
            if not verify_thread_identity(html, t.slug_id):
                print(f"    [VARNING] Identitetstest fail {t.slug_id} page{page}, stoppar.", file=sys.stderr)
                break
            write_page(thread_dir, page, html)
            update_page_meta(meta, page, html, hdrs)
            did_write = True
        meta["last_known_thread_last_page"] = Y
        save_thread_meta(thread_dir, meta)
        thread_state["latest_ts"] = t.latest_ts
        thread_state["title"] = t.title
        thread_state["base_url"] = t.base_url
        thread_state["last_page_hint"] = Y
        return did_write
    # Om forumlistan säger Y < X: rör inte lokalt, bara varna och uppdatera index
    if Y < X:
        print(f"  [!] {t.slug_id}: last_page_hint={Y} < lokal X={X}. Jag tar INTE bort lokala sidor.")
        thread_state["latest_ts"] = t.latest_ts
        thread_state["title"] = t.title
        thread_state["base_url"] = t.base_url
        thread_state["last_page_hint"] = Y
        save_thread_meta(thread_dir, meta)
        return False
    # Om nya sidor finns: hämta om X och sedan X+1..Y
    if Y > X:
        print(f"  [>] {t.slug_id}: nya sidor X={X} -> Y={Y}")
        for page in [X] + list(range(X + 1, Y + 1)):
            url = thread_page_url(t.base_url, page)
            status, html, hdrs = fetch_html(sess, url, timeout=timeout, delay=delay)
            if status != 200 or html is None:
                print(f"    [VARNING] page{page} status {status}, stoppar tråden.", file=sys.stderr)
                break
            if not verify_thread_identity(html, t.slug_id):
                print(f"    [VARNING] Identitetstest fail {t.slug_id} page{page}, stoppar.", file=sys.stderr)
                break
            write_page(thread_dir, page, html)
            update_page_meta(meta, page, html, hdrs)
            did_write = True
        meta["last_known_thread_last_page"] = Y
        save_thread_meta(thread_dir, meta)
        thread_state["latest_ts"] = t.latest_ts
        thread_state["title"] = t.title
        thread_state["base_url"] = t.base_url
        thread_state["last_page_hint"] = Y
        return did_write
    # Annars: Y == X -> kolla pageX med conditional fetch
    print(f"  [~] {t.slug_id}: samma sidantal (X=Y={X}) men aktivitet ändrad -> kollar page{X}")
    url = thread_page_url(t.base_url, X)
    cond = conditional_headers_for_page(meta, X)
    status, html, hdrs = fetch_html(sess, url, timeout=timeout, delay=delay, conditional_headers=cond)
    if status == 304:
        # servern säger oförändrad
        meta["last_known_thread_last_page"] = X
        save_thread_meta(thread_dir, meta)
        thread_state["latest_ts"] = t.latest_ts
        thread_state["title"] = t.title
        thread_state["base_url"] = t.base_url
        thread_state["last_page_hint"] = Y
        return False
    if status != 200 or html is None:
        print(f"    [VARNING] page{X} status {status}, skippar tråden.", file=sys.stderr)
        thread_state["latest_ts"] = t.latest_ts
        thread_state["title"] = t.title
        thread_state["base_url"] = t.base_url
        thread_state["last_page_hint"] = Y
        save_thread_meta(thread_dir, meta)
        return False
    if not verify_thread_identity(html, t.slug_id):
        print(f"    [VARNING] Identitetstest fail {t.slug_id} page{X}, stoppar.", file=sys.stderr)
        return False
    cleaned_hash_new = sha256_text(clean_html(html))
    old_entry = meta.get("pages", {}).get(str(X), {})
    cleaned_hash_old = old_entry.get("sha256_cleaned")
    if cleaned_hash_old and cleaned_hash_new == cleaned_hash_old:
        # innehåll samma, men uppdatera headers om de ändrats
        if "ETag" in hdrs:
            old_entry["etag"] = hdrs["ETag"]
        if "Last-Modified" in hdrs:
            old_entry["last_modified"] = hdrs["Last-Modified"]
        meta.setdefault("pages", {})[str(X)] = old_entry
        meta["last_known_thread_last_page"] = X
        save_thread_meta(thread_dir, meta)
        thread_state["latest_ts"] = t.latest_ts
        thread_state["title"] = t.title
        thread_state["base_url"] = t.base_url
        thread_state["last_page_hint"] = Y
        return False
    # Innehåll ändrat: skriv över
    write_page(thread_dir, X, html)
    update_page_meta(meta, X, html, hdrs)
    meta["last_known_thread_last_page"] = X
    save_thread_meta(thread_dir, meta)
    did_write = True
    thread_state["latest_ts"] = t.latest_ts
    thread_state["title"] = t.title
    thread_state["base_url"] = t.base_url
    thread_state["last_page_hint"] = Y
    return did_write
# ----------------------------
# Main
# ----------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Snål sync av rollspel.nu Varulvsspel-forumet.")
    ap.add_argument("--output", default=OUTPUT_DIR_DEFAULT, help="Utdata-mapp (default: data)")
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="Delay mellan requests i sekunder")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="HTTP-timeout i sekunder")
    ap.add_argument("--limit-threads", type=int, default=0, help="Testläge: synka bara N trådar (0=alla)")
    args = ap.parse_args()
    output_dir = args.output
    ensure_dir(output_dir)
    sess = build_session()
    idx = load_index(output_dir)
    print("Kaptenen: läser forumlistan och planerar synk…")
    try:
        forum_last_page, threads = crawl_forum(
            sess=sess,
            timeout=args.timeout,
            delay=args.delay,
            limit_threads=args.limit_threads,
        )
    except Exception as e:
        print(f"[FEL] {e}", file=sys.stderr)
        return 2
    print(f"Kaptenen: forumlistan totalt {forum_last_page} sidor. Trådar i denna körning: {len(threads)}")
    idx.setdefault("forum", {})["last_crawl_unix"] = int(time.time())
    idx["forum"]["forum_last_page"] = forum_last_page
    idx["forum"]["limit_threads"] = int(args.limit_threads or 0)
    changed_slugs: List[str] = []
    for i, t in enumerate(threads, start=1):
        print(f"\n[{i}/{len(threads)}] {t.title}")
        did_write = sync_thread(
            sess=sess,
            output_dir=output_dir,
            idx=idx,
            t=t,
            timeout=args.timeout,
            delay=args.delay,
        )
        if did_write:
            changed_slugs.append(t.slug_id)
        # checkpoint
        if i % 20 == 0:
            save_index(output_dir, idx)
    save_index(output_dir, idx)
    save_changed_threads(output_dir, changed_slugs)
    print(f"\nKaptenen: sync klar. Ändrade trådar: {len(changed_slugs)}")
    print(f"Kaptenen: skrev {os.path.join(output_dir, CHANGED_THREADS_FILENAME)}")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
