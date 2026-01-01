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
  let t = localStorage.getItem('theme') === 'dark' ? 'light' : 'dark';
  localStorage.setItem('theme', t);
  document.documentElement.dataset.theme = t;
}

document.addEventListener('DOMContentLoaded', () => {
  let t = localStorage.getItem('theme') || 'dark';
  document.documentElement.dataset.theme = t;
  pollScan();
});


/* =========================
   SCAN STATUS + TRIGGER
========================= */
function startScan(){
  fetch('/scan/start')
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

function initReader(scroll){
  console.log("initReader started, restoring to nearest panel =", scroll);

  const header = document.querySelector('.breadcrumb');
  const offset = header ? header.offsetHeight + 6 : 0;

  const panels = Array.from(document.querySelectorAll(".panel"));
  if(!panels.length){
    window.scrollTo(0,0);
    return;
  }

  function findNearestPanel(targetScroll){
    let nearest = panels[0];
    let bestDist = Math.abs(nearest.offsetTop - targetScroll);

    panels.forEach(p => {
      const d = Math.abs(p.offsetTop - targetScroll);
      if(d < bestDist){
        bestDist = d;
        nearest = p;
      }
    });

    return nearest;
  }

  function restore(){
    const targetScroll = scroll || 0;
    const nearest = findNearestPanel(targetScroll);

    const y = Math.max(nearest.offsetTop - offset, 0);
    console.log("Resuming at panel:", nearest, "y=", y);

    window.scrollTo({
      top: y,
      behavior: "auto"
    });
  }

  // Try multiple times because images may change layout
  restore();
  setTimeout(restore, 80);
  setTimeout(restore, 180);
  window.addEventListener("load", restore);
  

  /* -------- Progress Saving -------- */
  let lastSent = -1;
  let saveTimer = null;

  function sendProgress(){
    const ep = document.getElementById('reader').dataset.episode;
    const y = Math.round(window.scrollY);
    if(y === lastSent) return;
    lastSent = y;

    fetch('/progress', {
      method:'POST',
      credentials:'include',
      keepalive:true,
      headers:{'Content-Type':'application/x-www-form-urlencoded'},
      body:`episode=${ep}&scroll=${y}`
    }).catch(()=>{});
  }

  window.addEventListener('scroll', ()=>{
    clearTimeout(saveTimer);
    saveTimer = setTimeout(sendProgress, 300);
  });

  window.addEventListener("beforeunload", sendProgress);
  document.addEventListener("visibilitychange", ()=>{
    if(document.visibilityState === "hidden"){
      sendProgress();
    }
  });

  /* -------- Click Scroll Half-Screen -------- */
  document.body.addEventListener('click', (e)=>{
    let half = window.innerHeight/2;
    if(e.clientY < half) window.scrollBy(0,-half);
    else window.scrollBy(0,half);
  });
}
