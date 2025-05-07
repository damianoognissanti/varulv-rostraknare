document.addEventListener("DOMContentLoaded", async () => {
  const select = document.getElementById("threadSelect");
  try {
    const res = await fetch("data/threads.json");
    const threads = await res.json();
    threads.forEach(t => {
      const opt = document.createElement("option");
      opt.value = t;
      opt.textContent = t;
      select.appendChild(opt);
    });
  } catch {
    select.innerHTML = '<option>Inga trådar hittades</option>';
  }
});

async function loadSelected() {
  const thread = document.getElementById("threadSelect").value;
  if (!thread) return;

  const votes = [];
  for (let page = 1; page < 100; page++) {
    try {
      const res = await fetch(`data/${thread}/page${page}.html`);
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
          console.log(line);
          const match = line.match(/Röst:\s*(?:<a [^>]*>@([^<]+)<\/a>)/i);
          if (match && postId) {
            votes.push({ from: user, to: match[1].trim(), postId, timestamp });
          }
        });
      });
    } catch { break; }
  }

  window.allVotes = votes; // för full CSV-export
  displayVotes(votes, thread);
}

function displayVotes(votes, thread) {
  const latestVotes = {};
  votes.forEach(v => latestVotes[v.from] = v);

  const counts = {};
  const firstVoteTime = {};
  Object.values(latestVotes).forEach(v => {
    counts[v.to] = (counts[v.to] || 0) + 1;
    if (!firstVoteTime[v.to] || v.timestamp < firstVoteTime[v.to]) {
      firstVoteTime[v.to] = v.timestamp;
    }
  });

  const sorted = Object.entries(counts).sort((a, b) => {
    if (b[1] !== a[1]) return b[1] - a[1];
    return firstVoteTime[a[0]] < firstVoteTime[b[0]] ? -1 : 1;
  });

  const [mostVoted, mostVotes] = sorted[0] || ['Ingen', 0];
  document.getElementById("summary").textContent =
    `⚠️ Risk för utröstning: ${mostVoted} (${mostVotes} röster)`;

  const tableBody = document.querySelector("#voteTable tbody");
  tableBody.innerHTML = '';
  const playerSet = new Set();
  Object.values(latestVotes).forEach(({ from, to, postId, timestamp }) => {
    playerSet.add(from);
    const row = document.createElement("tr");
    row.setAttribute("data-from", from);
    row.innerHTML = `
      <td>${from}</td>
      <td><a href="https://www.rollspel.nu/threads/${thread}/post-${postId}" target="_blank">${to}</a></td>
      <td>${new Date(timestamp).toLocaleString("sv-SE")}</td>`;
    tableBody.appendChild(row);
  });

  const playerFilter = document.getElementById("playerFilter");
  playerFilter.innerHTML = '<option value="">Alla</option>';
  [...playerSet].sort().forEach(p => {
    playerFilter.innerHTML += `<option value="${p}">${p}</option>`;
  });

  playerFilter.onchange = filterVotes;

  showChart(counts);
  window.currentVotes = Object.values(latestVotes);
}

function showChart(counts) {
  const ctx = document.getElementById("chart").getContext("2d");
  if (window.voteChart) window.voteChart.destroy();
  window.voteChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: Object.keys(counts),
      datasets: [{
        label: "Antal röster",
        data: Object.values(counts),
        backgroundColor: "#3c8dbc"
      }]
    }
  });
}

function filterVotes() {
  const selectedOptions = Array.from(document.getElementById("playerFilter").selectedOptions);
  const selected = selectedOptions.map(opt => opt.value);
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
