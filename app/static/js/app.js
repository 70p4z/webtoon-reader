// --- Global prefix-safe fetch wrapper ---
(function(){
  const realFetch = window.fetch;
  window.fetch = function(input, init){
    if (typeof input === 'string'){
      if (window.SCRIPT_ROOT && input.startsWith('/') && !input.startsWith('//')){
        input = window.SCRIPT_ROOT + input;
      }
    }
    return realFetch(input, init);
  };
})();

/* =========================
   THEME TOGGLE
========================= */
function toggleTheme(){
  let t = localStorage.getItem('theme') === 'light' ? 'dark' : 'light';
  localStorage.setItem('theme', t);
  document.documentElement.dataset.theme = t;
}

document.addEventListener('DOMContentLoaded', () => {
  let t = localStorage.getItem('theme') || 'light';
  localStorage.setItem('theme', t);
  document.documentElement.dataset.theme = t;
  pollScan();

  let o = localStorage.getItem('episodeOrder') || 'desc';
  localStorage.setItem('episodeOrder', o);
});

function applyEpisodeOrder(){
  const list = document.getElementById("episode-list");
  
  if (!list) return;

  const order = localStorage.getItem("episodeOrder") || "asc";

  const cards = Array.from(list.getElementsByClassName("episode-card"));

  cards.sort((a, b) => {
    const na = parseInt(a.dataset.epNumber || 0);
    const nb = parseInt(b.dataset.epNumber || 0);
    return order === "desc" ? nb - na : na - nb;
  });

  // regen the list
  list.innerHTML = "";
  cards.forEach(c => list.appendChild(c));

  const btn = document.getElementById("order-toggle");
  if (btn) {
    btn.textContent = order === "desc" ? "⬆️" : "⬇️";
  }
}

function toggleEpisodeOrder(){
  const cur = localStorage.getItem("episodeOrder") || "asc";
  localStorage.setItem("episodeOrder", cur === "asc" ? "desc" : "asc");
  applyEpisodeOrder();
}

document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("order-toggle");
  if (btn) {
    btn.addEventListener("click", toggleEpisodeOrder);
    applyEpisodeOrder();
  }
});

/* =========================
   SCAN STATUS + TRIGGER
========================= */
function startScanFast(){
  fetch('/scan/start')
    .then(r => r.json())
    .then(() => pollScan())
    .catch(() => alert("Scan failed"));
}
function startScanDeep(){
  fetch('/scan/force')
    .then(r => r.json())
    .then(() => pollScan())
    .catch(() => alert("Scan failed"));
}

function pollScan(){
  fetch('/scan/status')
    .then(r => r.json())
    .then(d => {
      let el = document.getElementById('scan-status');
      if(!el) return;

      if(d.running){
        el.innerText = `Scanning ${d.progress}% • ${d.message}`;
        setTimeout(pollScan, 1000);
      } else {
        el.innerText = '';
      }
    });
}

/* =========================
   SCROLLING + RESUME
========================= */
function initReader(savedIndex){
  console.log("initReader: resume image index =", savedIndex);

  const reader = document.getElementById("reader");
  const panels = Array.from(reader.querySelectorAll(".panel"));
  const header = document.querySelector(".breadcrumb");
  const offset = header ? header.offsetHeight + 6 : 0;

  if (!panels.length) return;

  /* ---------- RESUME ---------- */
  function resume(){
    const idx = Math.max(0, Math.min(savedIndex || 0, panels.length - 1));
    const target = panels[idx];
    const y = Math.max(target.offsetTop - offset, 0);
    window.scrollTo({ top: y, behavior: "auto" });
  }

  // run multiple times to survive image loading/layout shifts
  resume();
  setTimeout(resume, 100);
  setTimeout(resume, 250);
  window.addEventListener("load", resume);

  /* ---------- PROGRESS TRACKING ---------- */
  let lastSent = -1;

  function currentPanelIndex(){
    const y = window.scrollY + offset + 10;

    for (let i = panels.length - 1; i >= 0; i--) {
      if (panels[i].offsetTop <= y) return i;
    }
    return 0;
  }

  function sendProgress(){
    const idx = currentPanelIndex();
    if (idx === lastSent) return;
    lastSent = idx;

    fetch("/progress", {
      method: "POST",
      credentials: "include",
      keepalive: true,
      headers: {"Content-Type":"application/x-www-form-urlencoded"},
      body: `episode=${reader.dataset.episode}&index=${idx}`
    }).catch(()=>{});
  }

  let timer = null;
  window.addEventListener("scroll", ()=>{
    clearTimeout(timer);
    timer = setTimeout(sendProgress, 300);
  });

  document.addEventListener("visibilitychange", ()=>{
    if (document.visibilityState === "hidden") sendProgress();
  });

  window.addEventListener("beforeunload", sendProgress);

  /* ---------- CLICK HALF-SCREEN SCROLL ---------- */
  document.body.addEventListener("click", (e)=>{
    const half = window.innerHeight / 2;
    window.scrollBy(0, e.clientY < half ? -half : half);
  });
}
