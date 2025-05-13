// app.js – komplett version 2025‑05‑13
// ------------------------------------------------------------
// Huvudfunktioner
//   • Alla UI‑tillstånd ↔︎ URL‑parametrar (sort, filter, slider, live…)
//   • Slider‑fix + live‑animation även vid sidladdning
//   • Filtrering och sortering bibehålls vid varje omrendering
// ------------------------------------------------------------

//---------------------------------------------------------------------
// 1. Globalt tillstånd + bootstrap
//---------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", async () => {
    /* ----------------------------------------------------------
     * Global state – synkas med URL så vyn kan delas som länk
     * --------------------------------------------------------*/
    window.state = {
        // dynamiskt från data
        threads: null,
        pages: 0,
        allVotes: [],
        playerColors: {},
        allPlayerCount: 0,
        // UI‑synkade värden
        slug: null,
        name: null,
        sliderPercent: 100,   // 0–100
        sliderTimeLimit: null,
        live: false,
        sort: "",            // "<col>-<asc|desc>"
        filterPlayers: [],
        // interna flaggor / objekt
        timeSliderRange: null,
        voteChart: null,
        isAnimating: false,
        elements: {},
        initialSettings: null
    };

    /* ----------------------------------------------------------
     * DOM‑cache (engångs‑uppslag)
     * --------------------------------------------------------*/
    const els = {
        pageTitle: document.getElementById("pageTitle"),
        threadSelect: document.getElementById("threadSelect"),
        timeSlider: document.getElementById("timeSlider"),
        sliderTimeLabel: document.getElementById("sliderTimeLabel"),
        liveToggle: document.getElementById("liveModeToggle"),
        delayInput: document.getElementById("liveDelayInput"),
        summary: document.getElementById("summary"),
        voteTableBody: document.querySelector("#voteTable tbody"),
        playerFilter: document.getElementById("playerFilter"),
        viewInputs: document.querySelectorAll('input[name="voteView"]')
    };
    window.state.elements = els;

    /* ----------------------------------------------------------
     * Init från URL‑query
     * --------------------------------------------------------*/
    const init = getInitialSettingsFromURL();
    window.state.initialSettings = init;
    window.state.sort = init.sort;
    window.state.filterPlayers = init.filter;
    window.state.sliderPercent = isNaN(init.slider) ? 100 : init.slider;
    window.state.live = init.live;

    // förifyll UI
    els.timeSlider.value = window.state.sliderPercent;
    els.liveToggle.checked = init.live;
    const selView = [...els.viewInputs].find(r => r.value === init.view);
    if (selView) selView.checked = true;
    if (!isNaN(init.delay)) els.delayInput.value = init.delay;

    /* ----------------------------------------------------------
     * Hämta trådar + autoladda om query innehåller thread
     * --------------------------------------------------------*/
    try {
        const res = await fetch("data/threads.json");
        const threads = await res.json();
        window.state.threads = threads;
        threads.forEach(t => {
            const o=document.createElement("option");
            o.value=t.slug; o.textContent=t.name; els.threadSelect.appendChild(o);
        });
        if (init.thread) {
            const t=threads.find(x=>x.slug===init.thread);
            if (t) {
                els.threadSelect.value=t.slug;
                Object.assign(window.state,{slug:t.slug,name:t.name,pages:t.pages});
                await loadSelected();
            }
        }
    } catch(e){ console.error(e); els.threadSelect.innerHTML='<option>Fel vid hämtning</option>'; }

    /* ----------------------------------------------------------
     * Event‑lyssnare (UI → state → URL → render)
     * --------------------------------------------------------*/
    els.threadSelect.addEventListener("change",()=>{
        const slug=els.threadSelect.value;
        const t=window.state.threads.find(x=>x.slug===slug);
        if(!t) return;
        Object.assign(window.state,{slug:t.slug,name:t.name,pages:t.pages});
        updateURLParams();
        loadSelected();
    });

    els.timeSlider.addEventListener("input", handleSliderInput);

    els.liveToggle.addEventListener("change",()=>{
        window.state.live=els.liveToggle.checked;
        updateURLParams();
        if(window.state.live) playVoteAnimation();
    });

    els.delayInput.addEventListener("input", updateURLParams);

    els.viewInputs.forEach(r=>r.addEventListener("change",()=>{
        updateURLParams();
        renderCurrentView();
    }));

    els.playerFilter.addEventListener("change",()=>{
        window.state.filterPlayers=[...els.playerFilter.selectedOptions].map(o=>o.value).filter(Boolean);
        updateURLParams();
        renderCurrentView();
    });
});

//---------------------------------------------------------------------
// 2. URL‑hjälpare
//---------------------------------------------------------------------
function getInitialSettingsFromURL(){
    const p=new URLSearchParams(window.location.search);
    return {
        thread:p.get("thread")||"",
        view:p.get("view")==="all"?"all":"latest",
        delay:parseInt(p.get("delay"),10)||200,
        sort:p.get("sort")||"",
        filter:p.get("filter")?p.get("filter").split(",").map(decodeURIComponent):[],
        slider:parseInt(p.get("slider"),10),
        live:p.get("live")==="1"
    };
}

function updateURLParams(){
    const p=new URLSearchParams(window.location.search);
    const st=window.state;
    const getView=()=>[...st.elements.viewInputs].find(r=>r.checked)?.value||"latest";

    if(st.slug) p.set("thread",st.slug);
    p.set("view",getView());
    p.set("delay",st.elements.delayInput.value);
    p.set("slider",st.sliderPercent);
    p.set("live",st.live?"1":"0");
    if(st.sort) p.set("sort",st.sort); else p.delete("sort");
    if(st.filterPlayers.length) p.set("filter",st.filterPlayers.map(encodeURIComponent).join(",")); else p.delete("filter");

    history.replaceState(null,"",`${window.location.pathname}?${p.toString()}`);
}

//---------------------------------------------------------------------
// 3. Tråd‑hämtning och röst‑parsning
//---------------------------------------------------------------------
async function loadSelected(){
    const {slug,pages,name}=window.state;
    if(!slug) return;

    const els=window.state.elements;
    els.pageTitle.innerHTML=`<h1>🐺 ${name}</h1>`;
    window.state.isAnimating=false;

    const live=window.state.live;
    const delay=parseInt(els.delayInput.value,10)||200;

    // array av fabriker så vi kan köra sekventiellt
    const factories=[];
    for(let p=1;p<=pages;p++) factories.push(()=>fetchPage(slug,p));
    const pagesHtml=await Promise.all(factories.map(fn=>fn()));
    const valid=pagesHtml.filter(Boolean);
    if(!valid.length){console.warn("Inga sidor"); return;}

    const votes=parseVotesFromPages(valid,slug);
    window.state.allVotes=votes;

    const ts=votes.map(v=>new Date(v.timestamp)).sort((a,b)=>a-b);
    window.state.timeSliderRange={minTime:ts[0],maxTime:ts[ts.length-1]};

    const players=[...new Set(votes.flatMap(v=>[v.from,v.to]))];
    window.state.playerColors=computePlayerColors(players);
    window.state.allPlayerCount=players.length;

    displayVotes(votes,slug);
    updateURLParams();
}

async function fetchPage(thread,page){
    const res=await fetch(`data/${encodeURIComponent(thread)}/page${page}.html`);
    if(!res.ok) return null;
    return{page,text:await res.text()};
}

function parseVotesFromPages(pages,thread){
    const votes=[];
    pages.forEach(({text})=>{
        const doc=new DOMParser().parseFromString(text,"text/html");
        doc.querySelectorAll("article[data-author]").forEach(post=>{
            const user=post.getAttribute("data-author");
            const postId=post.id?.replace("js-post-","");
            const ts=post.querySelector("time")?.getAttribute("datetime")||"";
            post.querySelectorAll("blockquote").forEach(bq=>bq.remove());
            const content=post.querySelector(".message-content")?.innerHTML||"";
            content.split("\n").forEach(line=>{
                const m=line.match(/Röst:.*<a [^>]*>@([^<]+)<\/a>/i);
                if(m&&postId) votes.push({from:user,to:m[1].trim(),postId,timestamp:ts});
            });
        });
    });
    return votes;
}

//---------------------------------------------------------------------
// 4. Slider & live‑animation
//---------------------------------------------------------------------
function handleSliderInput(){
    const pct=parseInt(this.value,10);
    window.state.sliderPercent=pct;
    const {minTime,maxTime}=window.state.timeSliderRange||{};
    if(!minTime||!maxTime){updateURLParams();return;}

    const limit=new Date(minTime.getTime()+ (maxTime-minTime)*pct/100);
    window.state.sliderTimeLimit=limit;
    window.state.elements.sliderTimeLabel.textContent=limit.toLocaleString("sv-SE",{dateStyle:"short",timeStyle:"short"});

    if(window.state.live){ playVoteAnimation(); } else { renderCurrentView(); }
    updateURLParams();
}

function playVoteAnimation(){
    if(window.state.isAnimating) return;
    window.state.isAnimating=true;
    const {delayInput}=window.state.elements;
    const delay=parseInt(delayInput.value,10)||200;
    const limit=window.state.sliderTimeLimit;
    const all=window.state.allVotes.filter(v=>!limit||new Date(v.timestamp)<=limit);
    let i=0;
    (function step(){
        if(i>all.length){window.state.isAnimating=false;return;}
        const subset=all.slice(0,i);
        const mode=getCurrentVoteView();
        renderVotes(mode==="all"?subset:getLatestVotes(subset),window.state.slug);
        i++; setTimeout(step,delay);
    })();
}

//---------------------------------------------------------------------
// 5. Rendering helpers
//---------------------------------------------------------------------
function getCurrentVoteView(){
    return [...window.state.elements.viewInputs].find(r=>r.checked)?.value||"latest";
}

function getLatestVotes(votes){
    const latest={};
    [...votes].sort((a,b)=>new Date(a.timestamp)-new Date(b.timestamp)).forEach(v=>latest[v.from]=v);
    return Object.values(latest);
}

function renderCurrentView(){
    const limit=window.state.sliderTimeLimit;
    let vs=window.state.allVotes;
    if(limit) vs=vs.filter(v=>new Date(v.timestamp)<=limit);
    const mode=getCurrentVoteView();
    const subset=mode==="all"?vs:getLatestVotes(vs);
    renderVotes(subset,window.state.slug);
}

function displayVotes(votes,thread){
    // slider‑label måste uppdateras innan första rendern
    handleSliderInput.call(window.state.elements.timeSlider);
    renderCurrentView();
}

//---------------------------------------------------------------------
// 6. Tabell / summary / diagram
//---------------------------------------------------------------------
function renderVotes(votes,thread){
    const counts={},first={};
    votes.sort((a,b)=>new Date(a.timestamp)-new Date(b.timestamp));
    votes.forEach(v=>{ counts[v.to]=(counts[v.to]||0)+1; if(!first[v.to]||new Date(v.timestamp)<new Date(first[v.to])) first[v.to]=v.timestamp; });

    // Summary
    const orderedCnt=Object.entries(counts).sort((a,b)=>b[1]-a[1]||new Date(first[a[0]])-new Date(first[b[0]]));
    const [danger,dCnt]=orderedCnt[0]||["Ingen",0];
    const riskStr=first[danger]?new Date(first[danger]).toLocaleString("sv-SE",{dateStyle:"short",timeStyle:"short"}):"okänd tid";
    const lastTS=votes.reduce((acc,v)=>(!acc||new Date(v.timestamp)>new Date(acc))?v.timestamp:acc,null);
    const lastStr=lastTS?new Date(lastTS).toLocaleString("sv-SE",{dateStyle:"short",timeStyle:"short"}):"okänd tid";
    window.state.elements.summary.textContent=`⚠️ Risk för utröstning: ${danger} (${dCnt} röster, sedan ${riskStr}). Senast röst lagd ${lastStr}.`;

    // Tabell
    const tbody=window.state.elements.voteTableBody; tbody.innerHTML="";
    const playerSet=new Set();
    const running={};
    const voteHist={};
    const rows=[];

    const getColor=n=>window.state.playerColors[n]||"#000";

    votes.forEach(({from,to,postId,timestamp})=>{
        running[to]=(running[to]||0)+1;
        const standing=Object.entries(running).sort((a,b)=>b[1]-a[1]||new Date(first[a[0]])-new Date(first[b[0]]));
        const leaderDisp=standing[0]?`${standing[0][0]} (${standing[0][1]})`:`–`;
        const runnerDisp=standing[1]?`${standing[1][0]} (${standing[1][1]})`:`–`;

        playerSet.add(from);
        voteHist[from]=voteHist[from]||[];
        if(voteHist[from][voteHist[from].length-1]!==to) voteHist[from].push(to);
        const chain=voteHist[from].map((n,i,arr)=>{
            const c=getColor(n); const safe=n.replace(/</g,"&lt;").replace(/>/g,"&gt;");
            return i===arr.length-1?`<a href="https://www.rollspel.nu/threads/${thread}/post-${postId}" target="_blank" style="color:${c};font-weight:bold">${safe}</a>`:`<span style="color:${c}">${safe}</span>`;
        }).join(" → ");

        const tr=document.createElement("tr"); tr.dataset.from=from;
        tr.innerHTML=`<td style="color:${getColor(from)};font-weight:bold">${from}</td><td>${chain}</td><td>${new Date(timestamp).toLocaleString("sv-SE")}</td><td>${leaderDisp}</td><td>${runnerDisp}</td>`;
        rows.push(tr);
    });
    rows.forEach(r=>tbody.appendChild(r));

    // Spelar‑filter bygga om men behåll val
    const sel=window.state.elements.playerFilter; const current=window.state.filterPlayers;
    sel.innerHTML='<option value="">Alla</option>';
    [...playerSet].sort((a,b)=>a.localeCompare(b,'sv')).forEach(p=>{
        const opt=document.createElement("option"); opt.value=p; opt.textContent=p; opt.style.color=window.state.playerColors[p]||"#000"; opt.style.fontWeight="bold"; if(current.includes(p)) opt.selected=true; sel.appendChild(opt);
    });

    // Använd befintligt filter‑urval
    filterVotes();

    // Använd sortering om satt
    if(window.state.sort){ const [idx,dir]=window.state.sort.split("-"); sortTable(parseInt(idx,10),dir); }

    // Diagram
    showChart(orderedCnt);
}

function filterVotes(){
    const sel=window.state.filterPlayers;
    [...document.querySelectorAll("#voteTable tbody tr")].forEach(r=>{
        r.style.display=!sel.length||sel.includes(r.dataset.from)?"":"none";
    });
}

function sortTable(colIndex,direction){
    const tbody=document.querySelector("#voteTable tbody"); const rows=[...tbody.rows];
    const asc=direction?direction==="asc":(tbody.dataset.sort!==`${colIndex}-asc`);
    rows.sort((a,b)=>{
        const at=a.children[colIndex].textContent.trim();
        const bt=b.children[colIndex].textContent.trim();
        return asc?at.localeCompare(bt,'sv'):bt.localeCompare(at,'sv');
    });
    tbody.innerHTML=""; rows.forEach(r=>tbody.appendChild(r));
    tbody.dataset.sort=`${colIndex}-${asc?"asc":"desc"}`;
    window.state.sort=tbody.dataset.sort; updateURLParams();
}

function computePlayerColors(players){
    const map={}; players.forEach((p,i)=>map[p]=`hsl(${(i*360/players.length).toFixed(0)},70%,60%)`); return map;
}

//---------------------------------------------------------------------
// 7. Diagram (Chart.js)
//---------------------------------------------------------------------
function showChart(entries){
    const labels=entries.map(([n])=>n);
    const data=entries.map(([,c])=>c);
    const bg=labels.map(l=>window.state.playerColors[l]||"#000");

    if(!window.state.voteChart){
        const ctx=document.getElementById("chart").getContext("2d");
        window.state.voteChart=new Chart(ctx,{type:"bar",data:{labels,datasets:[{label:"Antal röster",data,backgroundColor:bg}]},options:{responsive:true,indexAxis:'y',animation:{duration:300},scales:{x:{beginAtZero:true,max:window.state.allPlayerCount||undefined,ticks:{stepSize:1}},y:{ticks:{font:{size:22}}}}}});
    }else{
        const ch=window.state.voteChart;
        Object.assign(ch.data,{labels}); ch.data.datasets[0].data=data; ch.data.datasets[0].backgroundColor=bg; ch.update();
    }
}

//---------------------------------------------------------------------
// 8. Export CSV 
//---------------------------------------------------------------------
function exportCSV(){
        const rows=window.state.allVotes||[];
        const csv=["Röstgivare,Röst,Tidpunkt"];
        rows.forEach(v=>csv.push(`"${v.from}","${v.to}","${v.timestamp}"`));
        const blob=new Blob([csv.join("\n")],{type:"text/csv"});
        const url=URL.createObjectURL(blob);
        const a=document.createElement("a");
        a.href=url;
        a.download="rostdata.csv";
        a.click();
}
