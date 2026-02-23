#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from bs4 import BeautifulSoup
# ---- Filnamn som sync använder ----
SYNC_META_FILE = "_meta.json"                 # per tråd, från fetch_varulvsspel
CHANGED_THREADS_FILE = "_changed_threads.json"  # global, från fetch_varulvsspel (vi lägger till)
# ---- Våra cachefiler ----
VOTES_CACHE_FILE = "_votes_cache.json"        # per tråd: votes per page
VOTES_STATE_FILE = "_votes_state.json"        # per tråd: page -> sha256_cleaned som vi senast parsade
# ---- Regex (din logik) ----
VOTE_START = re.compile(r"\bröst\s*:\s*", re.I)
USER_TAG   = re.compile(r'data-username="@([^"]+)"', re.I)
OLD_VOTE   = re.compile(r"\bröst\s*:\s*(.+)", re.I)
NAME_CHARS = re.compile(r"[A-Za-z0-9_åäöÅÄÖ\- ]+")
def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
def _save_json(path: Path, obj, compact: bool = True):
    tmp = path.with_suffix(path.suffix + ".tmp")
    if compact:
        tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    else:
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
def thread_title_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    t = soup.find("title")
    if not t or not t.text:
        return ""
    s = t.text.strip()
    for p in ("Nekromanti - ", "Varulv - "):
        if s.startswith(p):
            s = s[len(p):]
    s = s.replace("| rollspel.nu", "").strip()
    return s
def pages_in_dir(d: Path) -> List[Tuple[int, Path]]:
    pages = []
    for p in d.glob("page*.html"):
        m = re.match(r"page(\d+)\.html$", p.name)
        if m:
            pages.append((int(m.group(1)), p))
    pages.sort(key=lambda x: x[0])
    return pages
def _split_html_lines(html_fragment: str):
    frag = re.sub(r"<br\s*/?>", "\n", html_fragment, flags=re.I)
    return re.split(r"\n", frag)
def _normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()
def _best_prefix_known(raw: str, known_cf: set):
    parts = raw.split()
    for i in range(len(parts), 0, -1):
        pref = " ".join(parts[:i]).strip()
        if pref and pref.casefold() in known_cf:
            return pref
    return None
def build_known_and_canon(pages: List[Tuple[int, Path]]):
    known_cf = set()
    canon = {}
    for _, page_path in pages:
        html = page_path.read_text(encoding="utf-8", errors="ignore")
        soup = BeautifulSoup(html, "html.parser")
        for post in soup.select("article[data-author]"):
            a = (post.get("data-author") or "").strip()
            if not a:
                continue
            cf = a.casefold()
            known_cf.add(cf)
            canon.setdefault(cf, a)
        for m in USER_TAG.finditer(html):
            u = (m.group(1) or "").lstrip("@").strip()
            if not u:
                continue
            cf = u.casefold()
            known_cf.add(cf)
            canon.setdefault(cf, u)
    return known_cf, canon
def extract_votes_tagmode(html: str, page_num: int):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for post in soup.select('article[data-author]'):
        from_user = (post.get("data-author") or "").strip()
        pid = (post.get("id") or "").replace("js-post-", "").strip()
        t = post.select_one("time.u-dt")
        ts = (t.get("datetime") if t else "") or ""
        for bq in post.select("blockquote"):
            bq.decompose()
        msg = post.select_one(".message-content")
        if not msg or not pid:
            continue
        content_html = msg.decode_contents()
        for line in _split_html_lines(content_html):
            plain = re.sub(r"<[^>]+>", " ", line)
            if not VOTE_START.search(plain):
                continue
            m = USER_TAG.search(line)
            if not m:
                continue
            to_user = (m.group(1) or "").lstrip("@").strip()
            if from_user and to_user:
                out.append({"from": from_user, "to": to_user, "ts": ts, "post": pid, "page": page_num})
    return out
def extract_votes_oldmode(html: str, page_num: int, known_cf: set, canon: dict):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for post in soup.select('article[data-author]'):
        from_user = (post.get("data-author") or "").strip()
        pid = (post.get("id") or "").replace("js-post-", "").strip()
        t = post.select_one("time.u-dt")
        ts = (t.get("datetime") if t else "") or ""
        for bq in post.select("blockquote"):
            bq.decompose()
        msg = post.select_one(".message-content")
        if not msg or not pid:
            continue
        content_html = msg.decode_contents()
        for line in _split_html_lines(content_html):
            plain = re.sub(r"<[^>]+>", " ", line)
            if not VOTE_START.search(plain):
                continue
            m = OLD_VOTE.search(plain)
            if not m:
                continue
            raw = m.group(1) or ""
            raw = _normalize_spaces(raw)
            if not raw:
                continue
            best = _best_prefix_known(raw, known_cf)
            if best:
                to_user = best
            else:
                nm = NAME_CHARS.search(raw)
                if not nm:
                    continue
                to_user = nm.group(0).strip()
            if not to_user:
                continue
            cf = to_user.casefold()
            to_user = canon.get(cf, to_user)
            if from_user and to_user:
                out.append({"from": from_user, "to": to_user, "ts": ts, "post": pid, "page": page_num})
    return out
def _detect_mode(thread_dir: Path, pages: List[Tuple[int, Path]]) -> str:
    # Snabbt: prova tag-mode på första 1-2 sidor
    for page_num, p in pages[:2]:
        html = p.read_text(encoding="utf-8", errors="ignore")
        if extract_votes_tagmode(html, page_num):
            return "tag"
    return "old"
def _sync_page_hash(thread_dir: Path, page_num: int) -> Optional[str]:
    meta = _load_json(thread_dir / SYNC_META_FILE, {"pages": {}})
    return (meta.get("pages", {}).get(str(page_num), {}) or {}).get("sha256_cleaned")
def _compute_players_and_range(votes: List[Dict]) -> Tuple[List[str], Dict]:
    if not votes:
        return [], {"min": None, "max": None}
    players = sorted(set([v["from"] for v in votes] + [v["to"] for v in votes]), key=lambda s: s.lower())
    tss = [v["ts"] for v in votes if v.get("ts")]
    tss.sort()
    return players, {"min": tss[0] if tss else None, "max": tss[-1] if tss else None}
def _flatten_votes(votes_cache: Dict) -> List[Dict]:
    out: List[Dict] = []
    pages = votes_cache.get("pages", {})
    for pnum in sorted((int(k) for k in pages.keys())):
        out.extend(pages[str(pnum)].get("votes", []) or [])
    out.sort(key=lambda v: v.get("ts") or "")
    return out
def update_thread(thread_dir: Path, verbose: bool = True) -> Optional[Dict]:
    pages = pages_in_dir(thread_dir)
    if not pages:
        return None
    slug = thread_dir.name
    # Läs/spara per-tråd cache/state
    votes_cache = _load_json(thread_dir / VOTES_CACHE_FILE, {"version": 1, "mode": None, "pages": {}})
    votes_state = _load_json(thread_dir / VOTES_STATE_FILE, {"version": 1, "page_hash": {}})
    # Trådtitel från page1 (billigt)
    html1 = pages[0][1].read_text(encoding="utf-8", errors="ignore")
    title = thread_title_from_html(html1) or slug
    # Mode låses per tråd
    mode = votes_cache.get("mode")
    if not mode:
        mode = _detect_mode(thread_dir, pages)
        votes_cache["mode"] = mode
    known_cf = None
    canon = None
    reparsed = 0
    for page_num, page_path in pages:
        h = _sync_page_hash(thread_dir, page_num)
        # Fallback om meta saknas: mtime (inte perfekt, men funkar)
        if not h:
            h = f"mtime:{int(page_path.stat().st_mtime)}"
        prev = votes_state.get("page_hash", {}).get(str(page_num))
        if prev == h and str(page_num) in votes_cache.get("pages", {}):
            continue  # sidan är redan parsat för denna version
        html = page_path.read_text(encoding="utf-8", errors="ignore")
        if mode == "tag":
            votes = extract_votes_tagmode(html, page_num)
        else:
            if known_cf is None or canon is None:
                known_cf, canon = build_known_and_canon(pages)
            votes = extract_votes_oldmode(html, page_num, known_cf, canon)
        votes_cache.setdefault("pages", {})[str(page_num)] = {"votes": votes}
        votes_state.setdefault("page_hash", {})[str(page_num)] = h
        reparsed += 1
    # Spara bara om något ändrats
    if reparsed > 0:
        _save_json(thread_dir / VOTES_CACHE_FILE, votes_cache, compact=False)
        _save_json(thread_dir / VOTES_STATE_FILE, votes_state, compact=False)
    all_votes = _flatten_votes(votes_cache)
    players, rng = _compute_players_and_range(all_votes)
    if verbose:
        if reparsed:
            print(f"  {slug}: reparsat {reparsed} sidor (tot {len(pages)}) -> {len(all_votes)} röster")
        else:
            print(f"  {slug}: inga ändringar -> {len(all_votes)} röster")
    return {
        "slug": slug,
        "name": title,
        "players": players,
        "range": rng,
        "votes": all_votes,
        "mode": mode,
    }
def load_existing_archive(path: Path) -> Dict:
    # Strukturen måste vara: {"threads":[...], "bySlug":{...}}
    return _load_json(path, {"threads": [], "bySlug": {}})
def rebuild_threads_list(by_slug: Dict[str, Dict]) -> List[Dict]:
    threads = [{"slug": slug, "name": obj.get("name", slug)} for slug, obj in by_slug.items()]
    threads.sort(key=lambda x: x["name"].lower())
    return threads
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data", help="Var trådmapparna ligger (default: data)")
    ap.add_argument("--out", default="archive.json", help="Vart archive.json ska skrivas (default: archive.json)")
    ap.add_argument("--changed-file", default="", help="Fil med ändrade slugs (default: data/_changed_threads.json)")
    ap.add_argument("--all", action="store_true", help="Bygg alla trådar (ignorera changed-lista)")
    ap.add_argument("--quiet", action="store_true", help="Mindre utskrift")
    args = ap.parse_args()
    data_dir = Path(args.data)
    out_path = Path(args.out)
    if not data_dir.exists():
        raise SystemExit(f"Saknar data-dir: {data_dir}")
    changed_path = Path(args.changed_file) if args.changed_file else (data_dir / CHANGED_THREADS_FILE)
    # --- changed-lista: KRÄV korrekt fil om vi inte kör --all ---
    if not args.all:
        if not changed_path.exists():
            raise SystemExit(
                f"Saknar changed-fil: {changed_path}\n"
                f"Kör fetch_varulvsspel.py först (med samma --output som --data), eller kör build_archive.py --all."
            )
        try:
            obj = json.loads(changed_path.read_text(encoding="utf-8"))
        except Exception as e:
            raise SystemExit(f"Kunde inte läsa {changed_path} som JSON: {e}")
        raw = obj.get("slugs")
        if raw is None:
            raise SystemExit(f"{changed_path} saknar nyckeln 'slugs'.")
        if not isinstance(raw, list):
            raise SystemExit(f"{changed_path} har 'slugs' men det är inte en lista.")
        changed_slugs = [str(s) for s in raw]
        # EARLY EXIT: 0 ändrade -> gör absolut ingenting
        if len(changed_slugs) == 0:
            if not args.quiet:
                print("Kaptenen: 0 ändrade trådar enligt _changed_threads.json -> hoppar över build.")
            return
    else:
        changed_slugs = None  # signal: bygg allt
    # Läs gammalt archive.json om det finns (så vi bara patchar)
    archive = load_existing_archive(out_path)
    by_slug = archive.get("bySlug", {}) if isinstance(archive.get("bySlug"), dict) else {}
    # Bestäm vilka trådar vi ska uppdatera
    if changed_slugs is not None:
        target_dirs = [data_dir / s for s in changed_slugs if (data_dir / s).is_dir()]
        mode = "changed-only"
    else:
        target_dirs = [p for p in data_dir.iterdir() if p.is_dir() and not p.name.startswith("_")]
        mode = "all"
    if not args.quiet:
        print(f"Kaptenen: bygger archive.json ({mode}), mål-trådar: {len(target_dirs)}")
    updated = 0
    for td in sorted(target_dirs, key=lambda p: p.name):
        info = update_thread(td, verbose=not args.quiet)
        if not info:
            continue
        by_slug[info["slug"]] = info
        updated += 1
    archive["bySlug"] = by_slug
    archive["threads"] = rebuild_threads_list(by_slug)
    archive["builtAt"] = int(time.time())
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _save_json(out_path, archive, compact=True)
    if not args.quiet:
        print(f"✅ Skrev {out_path} (uppdaterade {updated} trådar, totalt {len(archive['threads'])})")
if __name__ == "__main__":
    main()
