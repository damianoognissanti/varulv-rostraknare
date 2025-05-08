document.addEventListener("DOMContentLoaded", async () => {
    window.isAnimating = false;
    const select = document.getElementById("threadSelect");
    try {
        const res = await fetch("data/threads.json");
        const threads = await res.json();
        threads.forEach(t => {
            const opt = document.createElement("option");
            opt.value = t.slug;
            opt.textContent = t.name;
            select.appendChild(opt);
        });

        const urlThread = getThreadFromURL();
        if (urlThread && threads.some(t => t.slug === urlThread)) {
            select.value = urlThread;
            loadSelected();
        }

    } catch {
        select.innerHTML = '<option>Inga trådar hittades</option>';
    }

    document.getElementById("timeSlider").addEventListener("input", function () {
        const percent = parseInt(this.value, 10);
        const { minTime, maxTime } = window.timeSliderRange || {};
        if (!minTime || !maxTime) return;

        const timeSpan = maxTime - minTime;
        const limitTime = new Date(minTime.getTime() + (timeSpan * percent / 100));
        document.getElementById("sliderTimeLabel").textContent =
            limitTime.toLocaleString("sv-SE", {
                dateStyle: "short",
                timeStyle: "short"
            });
        window.sliderTimeLimit = limitTime;

        const thread = document.getElementById("threadSelect").value;
        if (!thread || !window.allVotes) return;

        if (document.getElementById("liveModeToggle").checked) {
            playVoteAnimation(); // 🔁 starta animation mot nya tidpunkten
        } else {
            const filteredVotes = window.allVotes.filter(v => {
                return !window.sliderTimeLimit || new Date(v.timestamp) <= window.sliderTimeLimit;
            });

            const mode = document.querySelector('input[name="voteView"]:checked').value;
            const subset = mode === "all"
                ? filteredVotes
                : getLatestVotes(filteredVotes);

            renderVotes(subset, thread);
        }
    });

    document.getElementById("liveModeToggle").addEventListener("change", function () {
        if (this.checked) {
            playVoteAnimation();
        }
    });

});

async function loadSelected() {
    const thread = document.getElementById("threadSelect").value;
    if (!thread) return;
    const showLiveVotes = document.getElementById("liveModeToggle")?.checked;
    let liveVotesTime = parseInt(document.getElementById("liveDelayInput")?.value || "30", 10);
    if (isNaN(liveVotesTime)) liveVotesTime = 30;
    document.getElementById("timeSlider").value = 100;
    document.getElementById("sliderTimeLabel").textContent = "–";
    window.sliderTimeLimit = null;
    const timeLimit = window.sliderTimeLimit || null;

    const votes = [];
    window.allVotes = votes; // för full CSV-export

    for (let page = 1; page < 100; page++) {
        try {
            const res = await fetch(`data/${encodeURIComponent(thread)}/page${page}.html`);
            if (!res.ok) break;
            const text = await res.text();
            const parser = new DOMParser();
            const doc = parser.parseFromString(text, "text/html");

            doc.querySelectorAll("article[data-author]").forEach(post => {
                const user = post.getAttribute("data-author");
                const postId = post.id?.replace("js-post-", "");
                const timestamp = post.querySelector("time")?.getAttribute("datetime") || "";
                post.querySelectorAll("blockquote").forEach(bq => bq.remove());
                const content = post.querySelector(".message-content")?.innerHTML || "";
                content.split('\n').forEach(line => {
                    const match = line.match(/Röst:.*<a [^>]*>@([^<]+)<\/a>/i);
                    if (match && postId) {
                        const voteTime = new Date(timestamp);
                        votes.push({ from: user, to: match[1].trim(), postId, timestamp });
                    }
                });
            });
            if(showLiveVotes){
                await new Promise(resolve => setTimeout(resolve, liveVotesTime)); // liten paus för UI
            }
            const newUrl = new URL(window.location);
            newUrl.searchParams.set("thread", thread);
            history.replaceState(null, "", newUrl.toString());
        } catch (e) {
                console.error(`Fel vid hämtning av sida ${page} för ${thread}:`, e);
                break;
        }
    }

    displayVotes(votes, thread);
}

function getVoteSubset() {
    const mode = document.querySelector('input[name="voteView"]:checked')?.value || "latest";
    if (!window.allVotes) return [];
    return mode === "all" ? window.allVotes : getLatestVotes(window.allVotes);
}

function toggleVoteView() {
    const mode = document.querySelector('input[name="voteView"]:checked').value;
    const thread = document.getElementById("threadSelect").value;
    if (!window.allVotes || !thread) return;

    const votesToShow = mode === "all" ? window.allVotes : getLatestVotes(window.allVotes);
    renderVotes(votesToShow, thread);
}

function getLatestVotes(votes) {
        const sortedVotes = [...votes].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
        const latest = {};
        sortedVotes.forEach(v => latest[v.from] = v);
        return Object.values(latest);
}

function displayVotes(votes, thread) {
    window.allVotes = votes;

    //sätt slider-intervall från alla röster, inte filtrerade
    const timestamps = votes.map(v => new Date(v.timestamp)).sort((a, b) => a - b);
    window.timeSliderRange = {
        minTime: timestamps[0],
        maxTime: timestamps[timestamps.length - 1]
    };
    toggleVoteView(); // initial vy
}

function renderVotes(votes, thread) {
    const counts = {};
    const firstVoteTime = {};
    votes.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

    votes.forEach(v => {
        counts[v.to] = (counts[v.to] || 0) + 1;
        if (!firstVoteTime[v.to] || new Date(v.timestamp) < new Date(firstVoteTime[v.to])) {
            firstVoteTime[v.to] = v.timestamp;
        }
    });

    const sorted = Object.entries(counts).sort((a, b) => {
        if (b[1] !== a[1]) return b[1] - a[1];
        return new Date(firstVoteTime[a[0]]) < new Date(firstVoteTime[b[0]]) ? -1 : 1;
    });

    const [mostVoted, mostVotes] = sorted[0] || ['Ingen', 0];
    const riskTime = firstVoteTime[mostVoted];
    const riskDateStr = riskTime
        ? new Date(riskTime).toLocaleString("sv-SE", { dateStyle: "short", timeStyle: "short" })
        : "okänd tid";

    const latestVoteTime = votes.reduce((acc, v) => {
            return !acc || new Date(v.timestamp) > new Date(acc) ? v.timestamp : acc;
    }, null);

    const updateDateStr = latestVoteTime
        ? new Date(latestVoteTime).toLocaleString("sv-SE", { dateStyle: "short", timeStyle: "short" })
        : "okänd tid";

    document.getElementById("summary").textContent =
        `⚠️ Risk för utröstning: ${mostVoted} (${mostVotes} röster, sedan ${riskDateStr}). Senast röst lagd ${updateDateStr}.`;

    const tableBody = document.querySelector("#voteTable tbody");
    tableBody.innerHTML = '';
    const playerSet = new Set();
    const runningVotes = {};
    const voteRows = [];

    votes.forEach(({ from, to, postId, timestamp }) => {
        runningVotes[to] = (runningVotes[to] || 0) + 1;

        // Hitta vem som leder just nu
        const sorted = Object.entries(runningVotes).sort((a, b) => {
            const diff = b[1] - a[1];
            if (diff !== 0) return diff;

            // Tiebreaker: vem fick första rösten först?
            const timeA = votes.find(v => v.to === a[0])?.timestamp;
            const timeB = votes.find(v => v.to === b[0])?.timestamp;
            return new Date(timeA) - new Date(timeB);
        });
        const currentLeader = sorted[0]?.[0] || "–";

        playerSet.add(from);
        const row = document.createElement("tr");
        row.setAttribute("data-from", from);
        row.innerHTML = `
                <td>${from}</td>
                <td><a href="https://www.rollspel.nu/threads/${thread}/post-${postId}" target="_blank">${to}</a></td>
                <td>${new Date(timestamp).toLocaleString("sv-SE")}</td>
                <td>${currentLeader} (${runningVotes[currentLeader]})</td>`;
        voteRows.push(row);
    });
    voteRows.forEach(row => tableBody.appendChild(row)); 

    const playerFilter = document.getElementById("playerFilter");
    playerFilter.innerHTML = '<option value="">Alla</option>';
    [...playerSet].sort().forEach(p => {
        playerFilter.innerHTML += `<option value="${p}">${p}</option>`;
    });

    filterVotes();
    showChart(counts);
}

function showChart(counts) {
    const labels = Object.keys(counts);
    const data = Object.values(counts);

    if (!window.voteChart) {
        const ctx = document.getElementById("chart").getContext("2d");
        window.voteChart = new Chart(ctx, {
            type: "bar",
            data: {
                labels,
                datasets: [{
                    label: "Antal röster",
                    data,
                    backgroundColor: "#3c8dbc"
                }]
            },
            options: {
                animation: { duration: 300 },
                responsive: true,
                scales: {
                    y: { beginAtZero: true },
                    x: { ticks: { font: { size: 22 } } }
                }
            }
        });
    } else {
        // 🧠 Uppdatera befintligt diagram:
        window.voteChart.data.labels = labels;
        window.voteChart.data.datasets[0].data = data;
        window.voteChart.update();
    }
}

function filterVotes() {
    const selectedOptions = Array.from(document.getElementById("playerFilter").selectedOptions);
    const selected = selectedOptions.map(opt => opt.value).filter(Boolean); // ta bort tomma strängar
    const rows = document.querySelectorAll("#voteTable tbody tr");

    rows.forEach(row => {
        const from = row.getAttribute("data-from");
        row.style.display = selected.length === 0 || selected.includes(from) ? "" : "none";
    });
}

function exportCSV() {
    const rows = window.allVotes || [];
    const csv = ["Röstgivare,Röst,Tidpunkt"];
    rows.forEach(v => {
        csv.push(`"${v.from}","${v.to}","${v.timestamp}"`);
    });
    const blob = new Blob([csv.join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "rostdata.csv";
    a.click();
}

function sortTable(columnIndex) {
    const tbody = document.querySelector("#voteTable tbody");
    const rows = Array.from(tbody.querySelectorAll("tr"));
    const ascending = tbody.getAttribute("data-sort") !== `${columnIndex}-asc`;

    rows.sort((a, b) => {
        const aText = a.children[columnIndex].textContent.trim();
        const bText = b.children[columnIndex].textContent.trim();
        return ascending
            ? aText.localeCompare(bText, 'sv')
            : bText.localeCompare(aText, 'sv');
    });

    tbody.innerHTML = '';
    rows.forEach(row => tbody.appendChild(row));
    tbody.setAttribute("data-sort", `${columnIndex}-${ascending ? "asc" : "desc"}`);
}

function getThreadFromURL() {
    const params = new URLSearchParams(window.location.search);
    return params.get("thread") || "";
}

function playVoteAnimation() {
    if (window.isAnimating) return; // förhindra att flera animationer kör samtidigt
    window.isAnimating = true;

    const thread = document.getElementById("threadSelect").value;
    const delay = parseInt(document.getElementById("liveDelayInput").value, 10);
    const limitTime = window.sliderTimeLimit || null;

    const votes = (window.allVotes || []).filter(v =>
        !limitTime || new Date(v.timestamp) <= limitTime
    );

    let i = 0;
    function animateStep() {
        if (i > votes.length) {
            window.isAnimating = false;
            return;
        }
        const subset = votes.slice(0, i);
        const viewInput = document.querySelector('input[name="voteView"]:checked');
        const mode = viewInput ? viewInput.value : "latest";
        renderVotes(mode === "all" ? subset : getLatestVotes(subset), thread);
        i++;
        setTimeout(animateStep, delay);
    }
    animateStep();
}
