import re, json, argparse
from pathlib import Path
from bs4 import BeautifulSoup
VOTE_START = re.compile(r"\bröst\s*:\s*", re.I)
USER_TAG   = re.compile(r'data-username="@([^"]+)"', re.I)
OLD_VOTE   = re.compile(r"\bröst\s*:\s*(.+)", re.I)
NAME_CHARS = re.compile(r"[A-Za-z0-9_åäöÅÄÖ\- ]+")
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
def pages_in_dir(d: Path):
    pages = []
    for p in d.glob("page*.html"):
        m = re.match(r"page(\d+)\.html$", p.name)
        if m:
            pages.append((int(m.group(1)), p))
    pages.sort(key=lambda x: x[0])
    return pages
def _split_html_lines(html_fragment: str):
    # Gör <br> till \n innan split, för mer stabil rad-detektering
    frag = re.sub(r"<br\s*/?>", "\n", html_fragment, flags=re.I)
    return re.split(r"\n", frag)
def extract_votes_from_html(html: str, page_num: int):
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
        content_html = msg.decode_contents()  # viktig: bara innehållet, inte wrapper-taggen
        for line in _split_html_lines(content_html):
            if not VOTE_START.search(line):
                continue
            m = USER_TAG.search(line)
            if not m:
                continue
            to_user = (m.group(1) or "").lstrip("@").strip()
            if from_user and to_user:
                out.append({"from": from_user, "to": to_user, "ts": ts, "post": pid, "page": page_num})
    return out
def _normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()
def _best_prefix_known(raw: str, known_cf: set):
    parts = raw.split()
    for i in range(len(parts), 0, -1):
        pref = " ".join(parts[:i]).strip()
        if pref and pref.casefold() in known_cf:
            return pref
    return None
def build_known_and_canon(pages):
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
        # plocka även alla taggar i HTML (även om personen aldrig postade)
        for m in USER_TAG.finditer(html):
            u = (m.group(1) or "").lstrip("@").strip()
            if not u:
                continue
            cf = u.casefold()
            known_cf.add(cf)
            canon.setdefault(cf, u)
    return known_cf, canon
def extract_votes_from_html_old(html: str, page_num: int, known_cf: set, canon: dict):
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
            if not VOTE_START.search(line):
                continue
            m = OLD_VOTE.search(line)
            if not m:
                continue
            raw = m.group(1) or ""
            raw = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
            raw = _normalize_spaces(raw)
            if not raw:
                continue
            best = _best_prefix_known(raw, known_cf)
            if best:
                to_user = best
            else:
                # search() istället för match(), så "@Namn", "(Namn)" etc fångas
                nm = NAME_CHARS.search(raw)
                if not nm:
                    continue
                to_user = nm.group(0).strip()
            if not to_user:
                continue
            # Canonical casing om vi råkar känna igen personen
            cf = to_user.casefold()
            to_user = canon.get(cf, to_user)
            if from_user and to_user:
                out.append({"from": from_user, "to": to_user, "ts": ts, "post": pid, "page": page_num})
    return out
def build_archive(data_dir: Path):
    threads = []
    by_slug = {}
    for td in sorted([p for p in data_dir.iterdir() if p.is_dir()]):
        slug = td.name
        pages = pages_in_dir(td)
        if not pages:
            continue
        html1 = pages[0][1].read_text(encoding="utf-8", errors="ignore")
        name = thread_title_from_html(html1) or slug
        votes = []
        votes_tag_found = True
        for page_num, page_path in pages:
            print("Läser:", page_path)
            html = page_path.read_text(encoding="utf-8", errors="ignore")
            votes.extend(extract_votes_from_html(html, page_num))
        # Viktigt: vi blandar inte lägen. Old-läge endast om 0 röster i hela tråden.
        if not votes:
            print("Hittade 0 röster med tagg-läge, testar gammalt läge...")
            votes_tag_found = False
            known_cf, canon = build_known_and_canon(pages)
            for page_num, page_path in pages:
                print("Läser:", page_path)
                html = page_path.read_text(encoding="utf-8", errors="ignore")
                votes.extend(extract_votes_from_html_old(html, page_num, known_cf, canon))
        print("Hittade", len(votes), "röster")
        # ISO-datetime (u-dt datetime) sorterar bra som sträng. Tomma ts hamnar först.
        votes.sort(key=lambda v: v.get("ts") or "")
        if votes:
            players = sorted(
                set([v["from"] for v in votes] + [v["to"] for v in votes]),
                key=lambda s: s.lower()
            )
            tss = [v["ts"] for v in votes if v.get("ts")]
            rng = {"min": tss[0] if tss else None, "max": tss[-1] if tss else None}
        else:
            players, rng = [], {"min": None, "max": None}
        threads.append({"slug": slug, "name": name})
        by_slug[slug] = {
            "slug": slug,
            "name": name,
            "players": players,
            "range": rng,
            "votes": votes,
            "mode": "tag" if votes_tag_found else "old",
        }
    threads.sort(key=lambda x: x["name"].lower())
    return {"threads": threads, "bySlug": by_slug}
def render_html(archive_obj: dict) -> str:
    # kompakt JSON: snabbare laddning, mindre fil
    data_json = json.dumps(archive_obj, ensure_ascii=False, separators=(",", ":"))
    return f"""<!doctype html>
<html lang="sv">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Varulv Rösträknare (Arkiv)</title>
<style>
body{{font-family:Arial,sans-serif;margin:2em;background:#f9f9f9;color:#333}}
label,button,select,input{{margin:8px 10px 8px 0}}
select,button,input{{padding:6px}}
#timeSlider{{padding:0;}}
table{{border-collapse:collapse;width:100%;margin-top:12px;background:#fff;border:1px solid #ccc}}
th,td{{padding:8px 10px;border:1px solid #ccc;text-align:center;vertical-align:top}}
th{{background:#3c8dbc;color:#fff;cursor:pointer}}
.summary{{font-weight:bold;font-size:18px;margin:12px 0}}
.sliderRow{{display:flex;align-items:center;gap:10px;margin:8px 0}}
.votesHeader{{display:flex;align-items:baseline;gap:10px;margin-top:18px}}
.playerLabel{{font-size:12px;opacity:.75}}
#playerFilter{{font-size:12px;padding:4px}}
#voteTable td:last-child,#voteTable th:last-child{{padding-right:18px}}
.small{{font-size:12px;opacity:.8}}
</style>
</head>
<body>
<div id="pageTitle"><h1>🐺 Varulv Rösträknare (Arkiv)</h1></div>
<label for="threadSelect">Välj tråd:</label>
<select id="threadSelect"></select>
<button id="exportBtn">Exportera CSV</button>
<div class="small" id="sourceLine"></div>
<br>
<label><input type="radio" name="voteView" value="latest" checked> Endast senaste röst</label>
<label><input type="radio" name="voteView" value="all"> Alla röster</label>
<br>
<button id="animateBtn" type="button">Animera röster</button>
<label>Hastighet:
  <input type="number" id="liveDelayInput" value="200" min="0" style="width:60px"> ms
</label>
<br>
<div class="sliderRow">
  <label for="timeSlider">Visa röster fram till:</label>
  <input type="range" id="timeSlider" min="0" max="100" value="100">
  <span id="sliderTimeLabel">–</span>
</div>
<div class="summary" id="summary"></div>
<canvas id="chart" width="520" height="225"></canvas>
<div class="votesHeader">
  <h2 style="margin:0">Röster</h2>
  <label class="playerLabel" for="playerFilter">Filter per spelare</label>
  <select id="playerFilter"></select>
</div>
<table id="voteTable">
  <thead>
    <tr>
      <th data-sort="from">Röstgivare</th>
      <th>Röst</th>
      <th data-sort="ts">Tidpunkt</th>
      <th>Riskerar att åka ut</th>
      <th>Därefter</th>
    </tr>
  </thead>
  <tbody></tbody>
</table>
<script id="ARCHIVE_DATA" type="application/json">{data_json}</script>
<script>
const A=JSON.parse(document.getElementById("ARCHIVE_DATA").textContent);
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const els={{
  th:$("#threadSelect"), exp:$("#exportBtn"), src:$("#sourceLine"),
  view:$$('input[name="voteView"]'), animBtn:$("#animateBtn"), delay:$("#liveDelayInput"),
  slider:$("#timeSlider"), sliderLbl:$("#sliderTimeLabel"), summary:$("#summary"),
  tbody:$("#voteTable tbody"), fp:$("#playerFilter"), ths:$$('#voteTable thead th'),
  cv:$("#chart")
}};
const st={{slug:"", votes:[], players:[], colors:{{}}, fp:"", sort:"", anim:false, animTimer:null, pct:100, lim:null, range:{{min:null,max:null}}}};
const curView=()=>els.view.find(r=>r.checked)?.value||"latest";
const fmt=t=>t?new Date(t).toLocaleString("sv-SE",{{dateStyle:"short",timeStyle:"short"}}):"–";
const enc=s=>String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
const mkColors=names=>{{const u=[...new Set(names)].sort((a,b)=>a.localeCompare(b,"sv"));const m={{}};u.forEach((n,i)=>m[n]=`hsl(${{Math.round(i*360/u.length)}},70%,60%)`);return m;}};
const getLatest=vs=>{{const m={{}};vs.slice().sort((a,b)=>+new Date(a.ts)-+new Date(b.ts)).forEach(v=>m[v.from]=v);return Object.values(m);}};
const urlp=()=>new URLSearchParams(location.search);
function readURL(){{
  const p=urlp();
  const view=p.get("view")==="all"?"all":"latest";
  const delay=parseInt(p.get("delay")||"200",10);
  const slider=parseInt(p.get("slider")||"100",10);
  return {{
    thread:p.get("thread")||"",
    view, delay:isNaN(delay)?200:delay,
    slider:isNaN(slider)?100:slider,
    fp:p.get("fp")||"",
    sort:p.get("sort")||""
  }};
}}
function applyURL(){{
  const p=urlp();
  if(st.slug) p.set("thread",st.slug); else p.delete("thread");
  p.set("view",curView());
  p.set("delay",String(parseInt(els.delay.value||"200",10)||200));
  p.set("slider",String(st.pct));
  if(st.fp) p.set("fp",st.fp); else p.delete("fp");
  if(st.sort) p.set("sort",st.sort); else p.delete("sort");
  history.replaceState(null,"",`${{location.pathname}}?${{p.toString()}}`);
}}
function fillThreads(){{
  els.th.innerHTML='<option value="">Välj...</option>';
  A.threads.forEach(t=>{{
    const o=document.createElement("option");
    o.value=t.slug;
    o.textContent=t.name;
    els.th.appendChild(o);
  }});
}}
function loadThread(slug, skipURL){{
  if(st.animTimer){{ clearTimeout(st.animTimer); st.animTimer=null; st.anim=false; }}
  const j=A.bySlug[slug];
  if(!j) return;
  st.slug=slug;
  st.votes=(j.votes||[]).map(v=>({{...v}}));
  st.players=(j.players&&j.players.length)?j.players:[...new Set(st.votes.flatMap(v=>[v.from,v.to]))];
  st.colors=mkColors(st.players);
  const ts=st.votes.map(v=>+new Date(v.ts)).filter(x=>!isNaN(x)).sort((a,b)=>a-b);
  st.range={{min:ts[0]?new Date(ts[0]):null,max:ts[ts.length-1]?new Date(ts[ts.length-1]):null}};
  els.th.value=st.slug;
  els.src.innerHTML=st.slug?`Källa: <a target="_blank" href="https://www.rollspel.nu/threads/${{st.slug}}/">https://www.rollspel.nu/threads/${{enc(st.slug)}}/</a>`:"";
  els.fp.innerHTML='<option value="">Alla</option>';
  st.players.slice().sort((a,b)=>a.localeCompare(b,"sv")).forEach(n=>{{
    const o=document.createElement("option");
    o.value=n; o.textContent=n;
    o.style.color=st.colors[n]||"#000";
    o.style.fontWeight="bold";
    els.fp.appendChild(o);
  }});
  onSlider(true);
  render();
  if(!skipURL) applyURL();
}}
function subset(){{
  let vs=st.votes;
  if(st.lim) vs=vs.filter(v=>+new Date(v.ts)<=+st.lim);
  if(curView()==="latest") vs=getLatest(vs);
  if(st.fp) vs=vs.filter(v=>v.from===st.fp); // filter är på röstgivare
  return vs;
}}
function bars(entries){{
  const ctx=els.cv.getContext("2d"), W=els.cv.width, H=els.cv.height;
  ctx.clearRect(0,0,W,H);
  const pad=10,left=160;
  const lab=entries.map(e=>e[0]), dat=entries.map(e=>e[1]);
  const mx=Math.max(1,...dat);
  ctx.font="18px Arial";
  lab.forEach((name,i)=>{{
    const barH=Math.max(12,Math.floor((H-2*pad)/Math.max(1,lab.length))-2);
    const y=pad+i*(barH+2);
    const w=Math.floor((W-left-pad-10)*dat[i]/mx);
    const c=st.colors[name]||"#999";
    const val=""+dat[i];
    const tw=ctx.measureText(val).width;
    ctx.fillStyle=c; ctx.fillText(name,pad,y+barH-2);
    ctx.fillStyle=c; ctx.fillRect(left,y,w,barH);
    ctx.fillStyle="#fff";
    ctx.fillText(val,Math.max(left+4,left+w-tw-4),y+barH-2);
  }});
}}
function sortApply(){{
  if(!st.sort) return;
  const rows=$$("#voteTable tbody tr");
  const asc=!st.sort.endsWith("-desc");
  const k=st.sort.split("-")[0];
  rows.sort((a,b)=>{{
    if(k==="from") {{
      const A=a.children[0].textContent.trim(), B=b.children[0].textContent.trim();
      return asc?A.localeCompare(B,"sv"):B.localeCompare(A,"sv");
    }}
    const A=a.dataset.ts||"", B=b.dataset.ts||"";
    return asc?A.localeCompare(B):B.localeCompare(A);
  }});
  els.tbody.innerHTML=""; rows.forEach(r=>els.tbody.appendChild(r));
}}
function render(vsOverride=null){{
  const vs = vsOverride ?? subset();
  if(!vs.length){{
    els.summary.textContent="Inga röster att visa.";
    els.tbody.innerHTML="";
    els.cv.getContext("2d").clearRect(0,0,els.cv.width,els.cv.height);
    return;
  }}
  const cnt={{}}, first={{}};
  vs.slice().sort((a,b)=>+new Date(a.ts)-+new Date(b.ts)).forEach(v=>{{
    cnt[v.to]=(cnt[v.to]||0)+1;
    if(!first[v.to]||+new Date(v.ts)<+new Date(first[v.to])) first[v.to]=v.ts;
  }});
  const ord=Object.entries(cnt).sort((a,b)=>b[1]-a[1]||(+new Date(first[a[0]])-+new Date(first[b[0]])));
  const [danger,dCnt]=ord[0]||["Ingen",0];
  const last=vs.reduce((acc,v)=>!acc||+new Date(v.ts)>+new Date(acc)?v.ts:acc,null);
  els.summary.textContent=`⚠️ Risk för utröstning: ${{danger}} (${{dCnt}} röster, sedan ${{fmt(first[danger])}}). Senast röst lagd ${{fmt(last)}}.`;
  els.tbody.innerHTML="";
  const hist={{}}, run={{}}, GC=n=>st.colors[n]||"#000";
  vs.slice().sort((a,b)=>+new Date(a.ts)-+new Date(b.ts)).forEach(v=>{{
    run[v.to]=(run[v.to]||0)+1;
    const stand=Object.entries(run).sort((x,y)=>y[1]-x[1]);
    const leader=stand[0]?`${{stand[0][0]}} (${{stand[0][1]}})`:"–";
    const runner=stand[1]?`${{stand[1][0]}} (${{stand[1][1]}})`:"–";
    hist[v.from]=hist[v.from]||[];
    if(hist[v.from][hist[v.from].length-1]!==v.to) hist[v.from].push(v.to);
    const chain=hist[v.from].map((n,i,a)=>{{
      const c=GC(n), safe=enc(n);
      if(i===a.length-1){{
        const href=`https://www.rollspel.nu/threads/${{st.slug}}/post-${{v.post}}`;
        return `<a target="_blank" href="${{href}}" style="color:${{c}};font-weight:bold">${{safe}}</a>`;
      }}
      return `<span style="color:${{c}}">${{safe}}</span>`;
    }}).join(" → ");
    const tr=document.createElement("tr");
    tr.dataset.from=v.from;
    tr.dataset.ts=v.ts||"";
    tr.innerHTML=`<td style="color:${{GC(v.from)}};font-weight:bold">${{enc(v.from)}}</td><td>${{chain}}</td><td>${{fmt(v.ts)}}</td><td>${{leader}}</td><td>${{runner}}</td>`;
    els.tbody.appendChild(tr);
  }});
  sortApply();
  bars(ord);
}}
function onSlider(skipURL){{
  if(st.animTimer){{clearTimeout(st.animTimer);st.animTimer=null;st.anim=false;}}
  st.pct=parseInt(els.slider.value||"100",10);
  if(!st.range.min||!st.range.max){{ st.lim=null; els.sliderLbl.textContent="–"; if(!skipURL){{ render(); applyURL(); }} return; }}
  const min=+st.range.min, max=+st.range.max;
  st.lim=new Date(min+(max-min)*st.pct/100);
  els.sliderLbl.textContent=fmt(st.lim);
  if(skipURL) return;
  render();
  applyURL();
}}
function play(){{
  if(st.animTimer) {{ clearTimeout(st.animTimer); st.animTimer = null; }}
  st.anim = true;
  const d = parseInt(els.delay.value||"200",10);
  const lim = st.lim;
  const all = (A.bySlug[st.slug].votes||[])
    .filter(v => !lim || +new Date(v.ts) <= +lim)
    .sort((a,b)=>+new Date(a.ts)-+new Date(b.ts));
  let i = 0;
  (function step(){{
    if(i > all.length){{
      st.anim = false;
      st.animTimer = null;
      return;
    }}
    const sub = all.slice(0,i);
    let show = (curView()==="all") ? sub : getLatest(sub);
    if(st.fp) show = show.filter(v => v.from === st.fp);
    render(show);
    i++;
    st.animTimer = setTimeout(step, d); // NEW: spara id
  }})();
}}
function exportCSV(){{
  const rows=subset();
  const csv=["Röstgivare,Röst,Tidpunkt,Post,Page"];
  rows.forEach(v=>csv.push(`"${{v.from}}","${{v.to}}","${{v.ts}}","${{v.post}}","${{v.page}}"`));
  const a=document.createElement("a");
  a.href=URL.createObjectURL(new Blob([csv.join("\\n")],{{type:"text/csv"}}));
  a.download="rostdata.csv";
  a.click();
}}
document.addEventListener("DOMContentLoaded", ()=>{{
  fillThreads();
  const init=readURL();
  els.delay.value=String(init.delay||200);
  els.slider.value=String(init.slider||100);
  st.fp=init.fp||"";
  st.sort=init.sort||"";
  const rv=els.view.find(r=>r.value===init.view);
  if(rv) rv.checked=true;
  els.th.addEventListener("change",()=>{{ const s=els.th.value||""; if(s) loadThread(s,false); }});
  els.exp.addEventListener("click",exportCSV);
  els.view.forEach(r=>r.addEventListener("change",()=>{{ if(st.animTimer){{clearTimeout(st.animTimer);st.animTimer=null;st.anim=false;}} render(); applyURL(); }}));
  els.animBtn.addEventListener("click", () => {{ if(!st.slug) return; play(); }});
  els.delay.addEventListener("input",applyURL);
  els.slider.addEventListener("input",()=>onSlider(false));
  els.fp.addEventListener("change",()=>{{ st.fp=els.fp.value||""; render(); applyURL(); }});
  els.ths.forEach(th=>{{
    const k=th.dataset.sort; if(!k) return;
    th.addEventListener("click",()=>{{
      const cur=st.sort||`${{k}}-asc`;
      const desc=cur.startsWith(k) && cur.endsWith("-asc");
      st.sort=`${{k}}-${{desc?"desc":"asc"}}`;
      render(); applyURL();
    }});
  }});
  if(init.thread && A.bySlug[init.thread]){{
    loadThread(init.thread,true);
    els.fp.value=st.fp||"";
    onSlider(true);
    render();
    applyURL();
  }} else {{
    applyURL();
  }}
}});
</script>
</body>
</html>
"""
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir", nargs="?", default="data", help="Default: data/")
    ap.add_argument("-o", "--out", default="index.html", help="Output HTML (default: index.html)")
    args = ap.parse_args()
    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        raise SystemExit(f"Saknar mapp: {data_dir}")
    archive = build_archive(data_dir)
    html = render_html(archive)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"✅ Skrev {args.out} (trådar: {len(archive['threads'])})")
if __name__ == "__main__":
    main()
