
function toggleTheme(){
  document.body.classList.toggle('dark');
  document.body.classList.toggle('light');
}

function initReader(ep){
  window.addEventListener('scroll', ()=>{
    fetch('/bookmark', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        episode:ep,
        scroll:window.scrollY,
        completed:(window.innerHeight + window.scrollY >= document.body.offsetHeight - 5)
      })
    });
  });

  document.addEventListener('click', e=>{
    const half = window.innerHeight / 2;
    window.scrollBy(0, e.clientY < half ? -half : half);
  });
}
