document.addEventListener("DOMContentLoaded",async()=>{
    /* --------------------------------------------------------------
     * Global application state
     * --------------------------------------------------------------*/
    window.state={
        playerColors:{},
        isAnimating:false,
        threads:null,
        pages:0,
        name:null,
        slug:null,
        allVotes:[],
        sliderTimeLimit:null,
        voteChart:null,
        allPlayerCount:0,
        timeSliderRange:null,
        elements:{}
    };

    /* --------------------------------------------------------------
     * Cache DOM elements once and reference them through window.state
     * --------------------------------------------------------------*/
    const els={
        pageTitle:document.getElementById("pageTitle"),
        threadSelect:document.getElementById("threadSelect"),
        timeSlider:document.getElementById("timeSlider"),
        sliderTimeLabel:document.getElementById("sliderTimeLabel"),
        liveToggle:document.getElementById("liveModeToggle"),
        delayInput:document.getElementById("liveDelayInput"),
        summary:document.getElementById("summary"),
        voteTableBody:document.querySelector("#voteTable tbody"),
        playerFilter:document.getElementById("playerFilter"),
        viewInputs:document.querySelectorAll('input[name="voteView"]')
    };
    window.state.elements=els;

    /* --------------------------------------------------------------
     * Initialise settings from URL
     * --------------------------------------------------------------*/
    const settings=getInitialSettingsFromURL();
    const selectedViewInput=Array.from(els.viewInputs).find(r=>r.value===settings.view);
    if(selectedViewInput) selectedViewInput.checked=true;
    if(!isNaN(settings.delay)) els.delayInput.value=settings.delay;

    /* --------------------------------------------------------------
     * Load list of threads and populate <select>
     * --------------------------------------------------------------*/
    try{
        const res=await fetch("data/threads.json");
        const threads=await res.json();
        window.state.threads=threads;
        threads.forEach(t=>{
            const opt=document.createElement("option");
            opt.value=t.slug;
            opt.textContent=t.name;
            els.threadSelect.appendChild(opt);
        });
        if(settings.thread){
            const threadObj=threads.find(t=>t.slug===settings.thread);
            if(threadObj){
                els.threadSelect.value=threadObj.slug;
                window.state.pages=threadObj.pages;
                window.state.name=threadObj.name;
                window.state.slug=threadObj.slug;
                loadSelected();
            }
        }
    }catch{
        els.threadSelect.innerHTML='<option>Inga trådar hittades</option>';
    }

    /* --------------------------------------------------------------
     * UI event listeners
     * --------------------------------------------------------------*/
    els.threadSelect.addEventListener("change",()=>{
        const slug=els.threadSelect.value;
        const threadObj=window.state.threads.find(t=>t.slug===slug);
        if(!threadObj) return;
        window.state.pages=threadObj.pages;
        window.state.name=threadObj.name;
        window.state.slug=threadObj.slug;
        updateURLParams();
        loadSelected();
    });

    els.delayInput.addEventListener("input",updateURLParams);

    els.viewInputs.forEach(r=>r.addEventListener("change",toggleVoteView));

    els.playerFilter.addEventListener("change",filterVotes);

    els.timeSlider.addEventListener("input",handleSliderInput);

    els.liveToggle.addEventListener("change",()=>{
        if(els.liveToggle.checked) playVoteAnimation();
    });
});

/* =====================================================================
 * Slider handler
 * ===================================================================*/
function handleSliderInput(){
    const percent=parseInt(this.value,10);
    const {minTime,maxTime}=window.state.timeSliderRange||{};
    if(!minTime||!maxTime) return;
    const timeSpan=maxTime-minTime;
    const limitTime=new Date(minTime.getTime()+timeSpan*percent/100);
    window.state.elements.sliderTimeLabel.textContent=limitTime.toLocaleString("sv-SE",{dateStyle:"short",timeStyle:"short"});
    window.state.sliderTimeLimit=limitTime;
    const thread=window.state.slug;
    if(!thread||!window.state.allVotes) return;
    if(window.state.elements.liveToggle.checked){
        playVoteAnimation();
    }else{
        const filteredVotes=window.state.allVotes.filter(v=>!window.state.sliderTimeLimit||new Date(v.timestamp)<=window.state.sliderTimeLimit);
        const mode=getCurrentVoteView();
        const subset=mode==="all"?filteredVotes:getLatestVotes(filteredVotes);
        renderVotes(subset,thread);
    }
}

/* =====================================================================
 * Load selected thread and parse votes
 * ===================================================================*/
async function loadSelected(){
    const thread=window.state.slug;
    if(!thread) return;
    const els=window.state.elements;
    els.pageTitle.innerHTML=`<h1>🐺 ${window.state.name}</h1>`
    els.timeSlider.value=100;
    els.sliderTimeLabel.textContent="–";
    window.state.sliderTimeLimit=null;
    const showLiveVotes=els.liveToggle.checked;
    let liveVotesTime=parseInt(els.delayInput.value||"200",10);
    if(isNaN(liveVotesTime)) liveVotesTime=200;
    const votes=[];
    window.state.allVotes=votes;
    const fetchPage=async page=>{
        const res=await fetch(`data/${encodeURIComponent(thread)}/page${page}.html`);
        if(!res.ok) return null;
        return{page,text:await res.text()};
    };
    const pagePromises=[];
    for(let page=1;page<=window.state.pages;page++) pagePromises.push(fetchPage(page));
    const results=showLiveVotes?await simulateLiveFetches(pagePromises,liveVotesTime):await Promise.all(pagePromises);
    const validPages=results.filter(Boolean);
    if(validPages.length===0){
        console.warn("Inga sidor kunde laddas.");
        return;
    }
    validPages.forEach(({text})=>{
        const doc=new DOMParser().parseFromString(text,"text/html");
        doc.querySelectorAll("article[data-author]").forEach(post=>{
            const user=post.getAttribute("data-author");
            const postId=post.id?.replace("js-post-","");
            const timestamp=post.querySelector("time")?.getAttribute("datetime")||"";
            post.querySelectorAll("blockquote").forEach(bq=>bq.remove());
            const content=post.querySelector(".message-content")?.innerHTML||"";
            content.split('\n').forEach(line=>{
                const match=line.match(/Röst:.*<a [^>]*>@([^<]+)<\/a>/i);
                if(match&&postId){
                    votes.push({from:user,to:match[1].trim(),postId,timestamp});
                }
            });
        });
    });
    const allPlayers=[...new Set(votes.flatMap(v=>[v.from,v.to]))];
    window.state.playerColors=computePlayerColors(allPlayers);
    window.state.allPlayerCount=allPlayers.length;
    updateURLParams();
    displayVotes(votes,thread);
}

/* =====================================================================
 * Render votes table, summary banner and chart
 * ===================================================================*/
function renderVotes(votes,thread){
    const counts={},firstVoteTime={};
    const getColor=name=>counts[name]?window.state.playerColors?.[name]:"#000";
    votes.sort((a,b)=>new Date(a.timestamp)-new Date(b.timestamp));
    votes.forEach(v=>{
        counts[v.to]=(counts[v.to]||0)+1;
        if(!firstVoteTime[v.to]||new Date(v.timestamp)<new Date(firstVoteTime[v.to])) firstVoteTime[v.to]=v.timestamp;
    });
    const sorted=Object.entries(counts).sort((a,b)=>{
        if(b[1]!==a[1]) return b[1]-a[1];
        return new Date(firstVoteTime[a[0]])-new Date(firstVoteTime[b[0]]);
    });
    const [mostVoted,mostVotes]=sorted[0]||["Ingen",0];
    const riskTime=firstVoteTime[mostVoted];
    const riskDateStr=riskTime?new Date(riskTime).toLocaleString("sv-SE",{dateStyle:"short",timeStyle:"short"}):"okänd tid";
    const latestVoteTime=votes.reduce((acc,v)=>!acc||new Date(v.timestamp)>new Date(acc)?v.timestamp:acc,null);
    const updateDateStr=latestVoteTime?new Date(latestVoteTime).toLocaleString("sv-SE",{dateStyle:"short",timeStyle:"short"}):"okänd tid";
    window.state.elements.summary.textContent=`⚠️ Risk för utröstning: ${mostVoted} (${mostVotes} röster, sedan ${riskDateStr}). Senast röst lagd ${updateDateStr}.`;

    /* ------------------------ table ---------------------------*/
    const tableBody=window.state.elements.voteTableBody;
    tableBody.innerHTML="";
    const playerSet=new Set();
    const runningVotes={};
    const voteRows=[];
    const voteHistory={};

    votes.forEach(({from,to,postId,timestamp})=>{
        runningVotes[to]=(runningVotes[to]||0)+1;
        const standing=Object.entries(runningVotes).sort((a,b)=>{
            const diff=b[1]-a[1];
            if(diff!==0) return diff;
            return new Date(firstVoteTime[a[0]])-new Date(firstVoteTime[b[0]]);
        });
        const leader=standing[0]?.[0]||"–";
        const leaderCnt=standing[0]?.[1];
        const leaderDisp=leaderCnt!=null?`${leader} (${leaderCnt})`:leader;
        const runner=standing[1]?.[0]||"–";
        const runnerCnt=standing[1]?.[1];
        const runnerDisp=runnerCnt!=null?`${runner} (${runnerCnt})`:runner;
        playerSet.add(from);
        if(!voteHistory[from]) voteHistory[from]=[];
        const lastVote=voteHistory[from][voteHistory[from].length-1];
        if(lastVote!==to) voteHistory[from].push(to);
        const voteChain=voteHistory[from].map((name,i,arr)=>{
            const color=getColor(name);
            const safe=name.replace(/</g,"&lt;").replace(/>/g,"&gt;");
            if(i===arr.length-1){
                return `<a href="https://www.rollspel.nu/threads/${thread}/post-${postId}" target="_blank" style="color:${color};font-weight:bold">${safe}</a>`;
            }
            return `<span style="color:${color}">${safe}</span>`;
        }).join(" → ");
        const row=document.createElement("tr");
        row.dataset.from=from;
        row.innerHTML=`<td style="color:${getColor(from)};font-weight:bold">${from}</td><td title="Senaste röst: ${new Date(timestamp).toLocaleString()}">${voteChain}</td><td>${new Date(timestamp).toLocaleString("sv-SE")}</td><td>${leaderDisp}</td><td>${runnerDisp}</td>`;
        voteRows.push(row);
    });
    voteRows.forEach(r=>tableBody.appendChild(r));

    /* ------------------------ player filter -------------------*/
    const filterSelect=window.state.elements.playerFilter;
    filterSelect.innerHTML='<option value="">Alla</option>';
    [...playerSet].sort((a,b)=>a.localeCompare(b,'sv')).forEach(p=>{
        const c=window.state.playerColors?.[p]||"#000";
        filterSelect.innerHTML+=`<option value="${p}" style="color:${c};font-weight:bold">${p}</option>`;
    });

    filterVotes();
    showChart(sorted);
}

/* =====================================================================
 * Helper functions
 * ===================================================================*/
function filterVotes(){
    const selected=Array.from(window.state.elements.playerFilter.selectedOptions).map(opt=>opt.value).filter(Boolean);
    document.querySelectorAll("#voteTable tbody tr").forEach(row=>{
        row.style.display=selected.length===0||selected.includes(row.dataset.from)?"":"none";
    });
}

function getCurrentVoteView(){
    const r=Array.from(window.state.elements.viewInputs).find(el=>el.checked);
    return r?.value||"latest";
}

function toggleVoteView(){
    const mode=getCurrentVoteView();
    const thread=window.state.slug;
    if(!thread) return;
    const votesToShow=mode==="all"?window.state.allVotes:getLatestVotes(window.state.allVotes);
    updateURLParams();
    renderVotes(votesToShow,thread);
}

function getLatestVotes(votes){
    const sorted=[...votes].sort((a,b)=>new Date(a.timestamp)-new Date(b.timestamp));
    const latest={};
    sorted.forEach(v=>latest[v.from]=v);
    return Object.values(latest);
}

function displayVotes(votes,thread){
    window.state.allVotes=votes;
    const timestamps=votes.map(v=>new Date(v.timestamp)).sort((a,b)=>a-b);
    window.state.timeSliderRange={minTime:timestamps[0],maxTime:timestamps[timestamps.length-1]};
    toggleVoteView();
}

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

function sortTable(columnIndex){
    const tbody=document.querySelector("#voteTable tbody");
    const rows=Array.from(tbody.rows);
    const ascending=tbody.dataset.sort!==`${columnIndex}-asc`;
    rows.sort((a,b)=>{
        const at=a.children[columnIndex].textContent.trim();
        const bt=b.children[columnIndex].textContent.trim();
        return ascending?at.localeCompare(bt,'sv'):bt.localeCompare(at,'sv');
    });
    tbody.innerHTML="";
    rows.forEach(r=>tbody.appendChild(r));
    tbody.dataset.sort=`${columnIndex}-${ascending?"asc":"desc"}`;
}

function getInitialSettingsFromURL(){
    const p=new URLSearchParams(window.location.search);
    return{thread:p.get("thread")||"",view:p.get("view")==="all"?"all":"latest",delay:parseInt(p.get("delay"),10)||200};
}

function updateURLParams(){
    const params=new URLSearchParams(window.location.search);
    params.set("view",getCurrentVoteView());
    params.set("delay",window.state.elements.delayInput.value);
    if(window.state.slug) params.set("thread",window.state.slug);
    history.replaceState(null,"",`${window.location.pathname}?${params.toString()}`);
}

function playVoteAnimation(){
    if(window.state.isAnimating) return;
    window.state.isAnimating=true;
    const els=window.state.elements;
    const thread=window.state.slug;
    const delay=parseInt(els.delayInput.value,10)||200;
    const limit=window.state.sliderTimeLimit;
    const votes=(window.state.allVotes||[]).filter(v=>!limit||new Date(v.timestamp)<=limit);
    let i=0;
    (function step(){
        if(i>votes.length){window.state.isAnimating=false;return;}
        const subset=votes.slice(0,i);
        const mode=getCurrentVoteView();
        renderVotes(mode==="all"?subset:getLatestVotes(subset),thread);
        i++;
        setTimeout(step,delay);
    })();
}

function computePlayerColors(players){
    const map={};
    players.forEach((p,i)=>map[p]=`hsl(${(i*360/players.length).toFixed(0)},70%,60%)`);
    return map;
}

function showChart(sortedEntries){
    const labels=sortedEntries.map(([name])=>name);
    const data=sortedEntries.map(([_,count])=>count);
    const backgroundColors=labels.map(l=>window.state.playerColors?.[l]||"#000");
    if(!window.state.voteChart){
        const ctx=document.getElementById("chart").getContext("2d");
        window.state.voteChart=new Chart(ctx, {
            type:"bar",
            data: {
                labels, 
                datasets: [{
                    label:"Antal röster",
                    data,
                    backgroundColor:backgroundColors
                }]
            },
            options: {
                animation:{duration:300},
                responsive:true,
                indexAxis:'y',
                scales: {
                    y:{
                        ticks:{
                            font:{
                                size:22
                            }
                        }
                    },
                    x:{
                        beginAtZero:true,
                        max:window.state.allPlayerCount||undefined,
                        ticks:{stepSize:1}
                    }
                }
            }
         });
    } else {
        window.state.voteChart.data.labels=labels;
        window.state.voteChart.data.datasets[0].data=data;
        window.state.voteChart.data.datasets[0].backgroundColor=backgroundColors;
        window.state.voteChart.update();
    }
}
