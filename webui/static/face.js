async function normFacePost(url) {
  const res = await fetch(url, { method: "POST" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return await res.json();
}

function normRefreshFacePreview(pack, state) {
  const img = document.getElementById("face-preview");
  const activePack = document.getElementById("active-pack");
  const activeState = document.getElementById("active-state");
  const nextPack = pack || (activePack ? activePack.textContent : "norm_default");
  const nextState = state || (activeState ? activeState.textContent : "idle");
  if (activePack && pack) activePack.textContent = pack;
  if (activeState && state) activeState.textContent = state;
  if (img) {
    img.src = `/api/core/face/preview.svg?pack=${encodeURIComponent(nextPack)}&state=${encodeURIComponent(nextState)}&t=${Date.now()}`;
  }
}

document.addEventListener("click", async (event) => {
  const stateBtn = event.target.closest("[data-face-state]");
  const packBtn = event.target.closest("[data-face-pack]");
  try {
    if (stateBtn) {
      const state = stateBtn.getAttribute("data-face-state");
      await normFacePost(`/api/core/face/state/${encodeURIComponent(state)}`);
      normRefreshFacePreview(null, state);
    }
    if (packBtn) {
      const pack = packBtn.getAttribute("data-face-pack");
      await normFacePost(`/api/core/face/pack/${encodeURIComponent(pack)}`);
      normRefreshFacePreview(pack, null);
      window.setTimeout(() => window.location.reload(), 150);
    }
  } catch (err) {
    alert(`Face command failed: ${err.message}`);
  }
});
