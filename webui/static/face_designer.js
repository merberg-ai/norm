(() => {
  const apiBase = (window.NORM_FACE_DESIGNER && window.NORM_FACE_DESIGNER.apiBase) || "/api/plugins/face_designer";
  const packSelect = document.getElementById("packSelect");
  const stateSelect = document.getElementById("stateSelect");
  const previewImg = document.getElementById("previewImg");
  const yamlEditor = document.getElementById("yamlEditor");
  const statusBox = document.getElementById("statusBox");
  const packMeta = document.getElementById("packMeta");
  const duplicateId = document.getElementById("duplicateId");
  const duplicateName = document.getElementById("duplicateName");
  const saveBtn = document.getElementById("saveBtn");

  let packs = [];
  let activePack = null;
  let currentPack = null;

  function log(message, obj) {
    const stamp = new Date().toLocaleTimeString();
    let line = `[${stamp}] ${message}`;
    if (obj !== undefined) line += `\n${JSON.stringify(obj, null, 2)}`;
    statusBox.textContent = `${line}\n\n${statusBox.textContent}`.slice(0, 9000);
  }

  async function fetchJson(url, options = {}) {
    const res = await fetch(url, options);
    const text = await res.text();
    let data;
    try { data = text ? JSON.parse(text) : {}; }
    catch (_err) { data = { ok: false, error: text || res.statusText }; }
    if (!res.ok || data.ok === false) {
      throw new Error(data.error || `${res.status} ${res.statusText}`);
    }
    return data;
  }

  function selectedPackId() {
    return packSelect.value;
  }

  function selectedState() {
    return stateSelect.value || "idle";
  }

  function updatePreview() {
    const pack = selectedPackId();
    const state = selectedState();
    if (!pack) return;
    previewImg.src = `${apiBase}/packs/${encodeURIComponent(pack)}/preview?state=${encodeURIComponent(state)}&_=${Date.now()}`;
  }

  function populateStates(pack) {
    stateSelect.innerHTML = "";
    const states = (pack && pack.states && pack.states.length) ? pack.states : ["idle"];
    for (const state of states) {
      const opt = document.createElement("option");
      opt.value = state;
      opt.textContent = state;
      stateSelect.appendChild(opt);
    }
    if (states.includes("idle")) stateSelect.value = "idle";
  }

  function updateMeta(pack) {
    if (!pack) {
      packMeta.textContent = "No pack selected.";
      return;
    }
    const lock = pack.readonly ? "read-only built-in" : "editable custom pack";
    packMeta.textContent = `${pack.name} · ${pack.renderer} · ${lock} · ${pack.states.length} states`;
    saveBtn.disabled = !!pack.readonly;
    saveBtn.title = pack.readonly ? "Duplicate built-in packs before editing." : "Save this editable face pack.";
  }

  async function loadPacks(preferredId) {
    const data = await fetchJson(`${apiBase}/packs`);
    packs = data.packs || [];
    activePack = data.active_pack;
    packSelect.innerHTML = "";
    for (const pack of packs) {
      const opt = document.createElement("option");
      opt.value = pack.id;
      opt.textContent = `${pack.id}${pack.id === activePack ? " ★" : ""}${pack.readonly ? " 🔒" : ""}`;
      packSelect.appendChild(opt);
    }
    const desired = preferredId || activePack || (packs[0] && packs[0].id);
    if (desired) packSelect.value = desired;
    await loadSelectedPack();
    log("Loaded face packs", { count: packs.length, active_pack: activePack });
  }

  async function loadSelectedPack() {
    const id = selectedPackId();
    if (!id) return;
    const data = await fetchJson(`${apiBase}/packs/${encodeURIComponent(id)}`);
    currentPack = data.pack;
    yamlEditor.value = data.yaml || "";
    populateStates(currentPack);
    updateMeta(currentPack);
    duplicateId.value = currentPack.readonly ? `custom_${currentPack.id}` : `${currentPack.id}_copy`;
    duplicateName.value = currentPack.readonly ? `${currentPack.name} Custom` : `${currentPack.name} Copy`;
    updatePreview();
  }

  async function duplicatePack() {
    const id = selectedPackId();
    const payload = {
      new_id: duplicateId.value.trim(),
      name: duplicateName.value.trim()
    };
    const data = await fetchJson(`${apiBase}/packs/${encodeURIComponent(id)}/duplicate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    log("Duplicated face pack", data.pack);
    await loadPacks(data.pack && data.pack.id);
  }

  async function savePack() {
    const id = selectedPackId();
    const data = await fetchJson(`${apiBase}/packs/${encodeURIComponent(id)}/save`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ yaml: yamlEditor.value })
    });
    yamlEditor.value = data.yaml || yamlEditor.value;
    log("Saved face pack", { pack: data.pack, backup: data.backup });
    await loadPacks(id);
  }

  async function activatePack() {
    const id = selectedPackId();
    const data = await fetchJson(`${apiBase}/packs/${encodeURIComponent(id)}/activate`, { method: "POST" });
    activePack = data.status && data.status.active_pack;
    log("Activated face pack", { active_pack: activePack });
    await loadPacks(activePack || id);
  }

  function wire() {
    packSelect.addEventListener("change", () => loadSelectedPack().catch(err => log(`Pack load failed: ${err.message}`)));
    stateSelect.addEventListener("change", updatePreview);
    document.getElementById("refreshBtn").addEventListener("click", () => loadPacks(selectedPackId()).catch(err => log(`Refresh failed: ${err.message}`)));
    document.getElementById("reloadBtn").addEventListener("click", () => loadSelectedPack().catch(err => log(`Reload failed: ${err.message}`)));
    document.getElementById("duplicateBtn").addEventListener("click", () => duplicatePack().catch(err => log(`Duplicate failed: ${err.message}`)));
    document.getElementById("saveBtn").addEventListener("click", () => savePack().catch(err => log(`Save failed: ${err.message}`)));
    document.getElementById("activateBtn").addEventListener("click", () => activatePack().catch(err => log(`Activate failed: ${err.message}`)));
  }

  wire();
  loadPacks().catch(err => log(`Startup failed: ${err.message}`));
})();
