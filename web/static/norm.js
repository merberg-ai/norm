async function postJSON(url, data = {}) {
  const res = await fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
  });
  return await res.json();
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val ?? '--';
}

function setPre(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = typeof val === 'string' ? val : JSON.stringify(val, null, 2);
}

async function setFace(mode) { await postJSON('/api/face/state', {mode}); await pollStatus(); }
async function setDisplay(mode) { await postJSON('/api/display/mode', {mode}); await pollStatus(); }
async function blink() { await postJSON('/api/face/blink', {count: 1}); }
async function glitch() { await postJSON('/api/face/glitch', {duration_seconds: .9}); }

async function snapshot() {
  setPre('camera-result', 'capturing snapshot...');
  const r = await postJSON('/api/camera/snapshot', {});
  setPre('camera-result', r);

  const img = document.getElementById('snapshot');
  if (img) {
    img.style.display = 'block';
    img.src = '/api/camera/latest.jpg?cache=' + Date.now();
  }

  const dashImg = document.getElementById('dashboard-snapshot');
  if (dashImg) {
    dashImg.style.display = 'block';
    dashImg.src = '/api/camera/latest.jpg?cache=' + Date.now();
  }

  await refreshCameraStatus();
  await pollStatus();
}

async function refreshCameraStatus() {
  try {
    const s = await (await fetch('/api/camera/status')).json();
    setText('camera-status-text', s.status || (s.exists ? 'ready' : 'missing'));
    setText('camera-device', s.device);
    setPre('camera-result', s);
  } catch (e) {
    setPre('camera-result', 'camera status error: ' + e);
  }
}

async function loadCameraDevices() {
  const r = await (await fetch('/api/camera/devices')).json();
  setPre('camera-result', r);
}

async function loadCameraFormats() {
  const r = await (await fetch('/api/camera/formats')).json();
  setPre('camera-result', r);
}

async function refreshAudioStatus(showRaw = true) {
  try {
    const s = await (await fetch('/api/audio/status')).json();
    setText('audio-input-device', s.input?.device);
    setText('audio-input-status', s.input?.status);
    setText('audio-output-device', s.output?.device);
    setText('audio-output-status', s.output?.status);
    setText('audio-last-recording', s.input?.last_recording || 'none');
    if (showRaw) setPre('audio-result', s);

    const player = document.getElementById('recording-player');
    if (player && s.input?.test_record_exists) {
      player.src = '/api/audio/latest-recording.wav?cache=' + Date.now();
    }
  } catch (e) {
    setPre('audio-result', 'audio status error: ' + e);
  }
}

async function loadAudioDevices() {
  setPre('audio-result', 'collecting audio devices...');
  const r = await (await fetch('/api/audio/devices')).json();
  setPre('audio-result', r);
}

async function recordAudio() {
  setPre('audio-result', 'recording microphone sample...');
  const r = await postJSON('/api/audio/record-test', {});
  showAudio(r);
  await refreshAudioStatus(false);
  await pollStatus();
}

async function playRecording() {
  setPre('audio-result', 'playing latest recording...');
  const r = await postJSON('/api/audio/play-recording', {});
  showAudio(r);
  await refreshAudioStatus(false);
  await pollStatus();
}

async function playTest() {
  setPre('audio-result', 'playing test sound...');
  const r = await postJSON('/api/audio/play-test', {});
  showAudio(r);
  await refreshAudioStatus(false);
  await pollStatus();
}

function showAudio(r) { setPre('audio-result', r); }

async function pollStatus() {
  try {
    const s = await (await fetch('/api/status')).json();
    setText('face-mode', s.face_mode);
    setText('display-mode', s.display_mode);
    setText('last-action', s.last_action);
    setText('camera-status', s.camera_status);
    setText('audio-in', s.audio_input_status);
    setText('audio-out', s.audio_output_status);
    setText('brain-status', s.brain_status);
    setText('brain-latency', s.last_brain_latency_ms == null ? '--' : `${s.last_brain_latency_ms} ms`);
    setText('host', s.hostname);
    setText('ip', s.lan_ip);
    setText('uptime', s.uptime_seconds);
    if (s.touch) {
      setText('touch-device', s.touch.device_name);
      setText('taps', s.touch.tap_count);
      setText('xy', `${s.touch.x},${s.touch.y}`);
    }
  } catch (e) {
    console.log(e);
  }
}

function formatLoad(load) {
  if (!load) return '--';
  return `${load['1m']} / ${load['5m']} / ${load['15m']}`;
}

async function pollDiagnostics(showRaw = false) {
  try {
    const d = await (await fetch('/api/diagnostics')).json();

    setText('cpu-temp', d.cpu?.temperature_c == null ? '--' : `${d.cpu.temperature_c}°C`);
    setText('loadavg', formatLoad(d.cpu?.load));
    setText('memory-used', d.memory?.used_percent == null ? '--' : `${d.memory.used_percent}% (${d.memory.used_mb}/${d.memory.total_mb} MB)`);
    setText('disk-used', d.disk?.used_percent == null ? '--' : `${d.disk.used_percent}% (${d.disk.used_gb}/${d.disk.total_gb} GB)`);

    setText('diag-host', d.system?.hostname);
    setText('diag-ip', d.system?.lan_ip);
    setText('diag-profile', d.system?.profile);
    setText('diag-uptime', d.system?.uptime_seconds + ' sec');
    setText('diag-python', d.system?.python);
    setText('diag-cpu-temp', d.cpu?.temperature_c == null ? '--' : `${d.cpu.temperature_c}°C`);
    setText('diag-load', formatLoad(d.cpu?.load));
    setText('diag-memory', d.memory?.used_percent == null ? '--' : `${d.memory.used_percent}% used`);
    setText('diag-disk', d.disk?.used_percent == null ? '--' : `${d.disk.used_percent}% used`);
    setText('diag-camera-device', d.camera?.device);
    setText('diag-camera-exists', d.camera?.device_exists ? 'yes' : 'no');
    setText('diag-camera-status', d.camera?.status);
    setText('diag-camera-snapshot', d.camera?.snapshot_exists ? 'yes' : 'no');
    setText('diag-touch-device', d.touch?.runtime_device || d.touch?.configured_device);
    setText('diag-touch-event', d.touch?.last_event);
    setText('diag-audio-in', `${d.audio?.input_device} / ${d.audio?.input_status}`);
    setText('diag-audio-out', `${d.audio?.output_device} / ${d.audio?.output_status}`);
    setText('diag-brain-status', d.brain?.status);
    setText('diag-brain-host', d.brain?.host);
    setText('diag-brain-model', d.brain?.model);
    setText('diag-brain-latency', d.brain?.last_latency_ms == null ? '--' : `${d.brain.last_latency_ms} ms`);
    setText('diag-brain-error', d.brain?.last_error || 'none');

    if (showRaw) setPre('diagnostics-raw', d);
  } catch (e) {
    setPre('diagnostics-raw', 'diagnostics error: ' + e);
  }
}

async function loadFullDiagnostics() {
  setPre('diagnostics-raw', 'collecting full hardware report...');
  const r = await (await fetch('/api/diagnostics/full')).json();
  setPre('diagnostics-raw', r);
}

function boolFromSelect(id) {
  const el = document.getElementById(id);
  return el ? el.value === 'true' : false;
}

function setSelectValue(id, value) {
  const el = document.getElementById(id);
  if (!el) return;
  const val = String(value ?? '');
  let found = false;
  for (const opt of el.options) {
    if (opt.value === val) { found = true; break; }
  }
  if (!found && val) {
    const opt = document.createElement('option');
    opt.value = val;
    opt.textContent = `${val} (configured)`;
    el.appendChild(opt);
  }
  el.value = val;
}

function fillSelect(id, options, configured, includeDefault = true) {
  const el = document.getElementById(id);
  if (!el) return;
  el.innerHTML = '';
  if (includeDefault) {
    const opt = document.createElement('option');
    opt.value = 'default';
    opt.textContent = 'default';
    el.appendChild(opt);
  }
  for (const item of options || []) {
    const opt = document.createElement('option');
    opt.value = item.value || item.device || item.path || item;
    opt.textContent = item.label || item.name || opt.value;
    el.appendChild(opt);
  }
  setSelectValue(id, configured || (includeDefault ? 'default' : ''));
}

function setInputValue(id, value) {
  const el = document.getElementById(id);
  if (el) el.value = value ?? '';
}

async function loadConfigOptions() {
  setPre('config-result', 'probing devices and loading config...');
  const r = await (await fetch('/api/config/options')).json();
  const cfg = r.config || {};

  fillSelect('cfg-camera-device', r.camera?.options || [], cfg.camera?.device, false);
  fillSelect('cfg-audio-input-device', r.audio?.input_options || [], cfg.audio?.input?.device, true);
  fillSelect('cfg-audio-output-device', r.audio?.output_options || [], cfg.audio?.output?.device, true);
  fillSelect('cfg-touch-device', r.touch?.options || [], cfg.touch?.device, false);

  setSelectValue('cfg-camera-enabled', String(cfg.camera?.enabled !== false));
  const res = cfg.camera?.resolution || [640, 480];
  setSelectValue('cfg-camera-resolution', `${res[0]}x${res[1]}`);
  setSelectValue('cfg-camera-command', cfg.camera?.capture_command || 'fswebcam');
  setInputValue('cfg-snapshot-path', cfg.camera?.snapshot_path || '/tmp/norm_latest.jpg');

  setSelectValue('cfg-audio-input-enabled', String(cfg.audio?.input?.enabled !== false));
  setSelectValue('cfg-sample-rate', cfg.audio?.input?.sample_rate || 16000);
  setSelectValue('cfg-input-channels', cfg.audio?.input?.channels || 1);
  setInputValue('cfg-record-seconds', cfg.audio?.input?.record_seconds || 5);

  setSelectValue('cfg-audio-output-enabled', String(cfg.audio?.output?.enabled === true));
  setInputValue('cfg-volume', cfg.audio?.output?.volume_percent ?? 80);
  setInputValue('cfg-api-port', cfg.api?.port || 8088);

  const idle = cfg.face?.idle_behavior || {};
  setInputValue('cfg-face-status-text', cfg.face?.default_status_text || 'LISTENING...');
  setSelectValue('cfg-idle-enabled', String(idle.enabled !== false));
  setInputValue('cfg-idle-min', idle.min_seconds ?? 35);
  setInputValue('cfg-idle-max', idle.max_seconds ?? 90);
  setInputValue('cfg-idle-expression-min', idle.expression_min_seconds ?? 5);
  setInputValue('cfg-idle-expression-max', idle.expression_max_seconds ?? 11);
  const exprs = idle.expressions || ['annoyed', 'bored', 'worried'];
  const setChecked = (id, val) => { const el = document.getElementById(id); if (el) el.checked = exprs.includes(val); };
  setChecked('cfg-expr-annoyed', 'annoyed');
  setChecked('cfg-expr-bored', 'bored');
  setChecked('cfg-expr-worried', 'worried');

  const brain = cfg.brain || {};
  setSelectValue('cfg-brain-enabled', String(brain.enabled === true));
  setSelectValue('cfg-brain-provider', brain.provider || 'ollama');
  setInputValue('cfg-brain-host', brain.host || 'http://192.168.1.24:11434');
  setInputValue('cfg-brain-model', brain.chat_model || 'norm-alpha');
  setInputValue('cfg-brain-timeout', brain.timeout_seconds ?? 60);
  setInputValue('cfg-brain-speaking-hold', brain.speaking_hold_seconds ?? 4);
  setInputValue('cfg-brain-max-prompt', brain.max_prompt_chars ?? 2000);
  const streamEl = document.getElementById('cfg-brain-stream');
  if (streamEl) streamEl.checked = brain.stream === true;

  const mem = cfg.memory || {};
  setSelectValue('cfg-memory-enabled', String(mem.enabled === true));
  setInputValue('cfg-memory-db', mem.database_path || 'data/norm_memory.sqlite3');
  setInputValue('cfg-memory-session', mem.session_id || 'default');
  setInputValue('cfg-memory-recent', mem.max_recent_messages ?? 16);
  const memRecentEl = document.getElementById('cfg-memory-include-recent');
  if (memRecentEl) memRecentEl.checked = mem.include_recent_messages !== false;
  const memAutosaveEl = document.getElementById('cfg-memory-autosave');
  if (memAutosaveEl) memAutosaveEl.checked = mem.auto_save_messages !== false;
  const memSystemEl = document.getElementById('cfg-memory-system-prompt');
  if (memSystemEl) memSystemEl.checked = mem.inject_system_prompt !== false;

  const tts = cfg.speech?.tts || {};
  fillVoicePresets(r.speech?.presets || r.speech?.tts?.presets || [], tts.voice_preset || 'creepy_terminal');
  setSelectValue('cfg-tts-enabled', String(tts.enabled === true));
  setSelectValue('cfg-tts-provider', tts.provider || 'espeak-ng');
  setSelectValue('cfg-tts-voice', tts.voice || 'en-us+m3');
  setInputValue('cfg-tts-speed', tts.speed ?? 130);
  setInputValue('cfg-tts-pitch', tts.pitch ?? 28);
  setInputValue('cfg-tts-amplitude', tts.amplitude ?? 135);
  setInputValue('cfg-tts-word-gap', tts.word_gap ?? 5);
  setInputValue('cfg-tts-max-chars', tts.max_spoken_chars ?? 500);
  setInputValue('cfg-tts-test-phrase', tts.test_phrase || 'Routine oversight is active. Your compliance has been logged.');
  const speakDefaultEl = document.getElementById('cfg-tts-speak-default');
  if (speakDefaultEl) speakDefaultEl.checked = tts.speak_brain_responses_by_default === true;

  const raw = document.getElementById('raw-config');

  if (raw && !raw.value.trim()) raw.value = JSON.stringify(cfg, null, 2);

  setPre('config-result', r);
}

function intInput(id, fallback) {
  const raw = document.getElementById(id)?.value;
  const n = parseInt(raw || String(fallback), 10);
  return Number.isFinite(n) ? n : fallback;
}

function checkedExpressions() {
  const out = [];
  if (document.getElementById('cfg-expr-annoyed')?.checked) out.push('annoyed');
  if (document.getElementById('cfg-expr-bored')?.checked) out.push('bored');
  if (document.getElementById('cfg-expr-worried')?.checked) out.push('worried');
  return out.length ? out : ['annoyed', 'bored', 'worried'];
}

async function saveDeviceConfig() {
  const resStr = document.getElementById('cfg-camera-resolution')?.value || '640x480';
  const [rw, rh] = resStr.split('x').map(v => parseInt(v, 10));

  const payload = {
    camera: {
      enabled: boolFromSelect('cfg-camera-enabled'),
      device: document.getElementById('cfg-camera-device')?.value,
      resolution: [rw || 640, rh || 480],
      capture_command: document.getElementById('cfg-camera-command')?.value,
      snapshot_path: document.getElementById('cfg-snapshot-path')?.value
    },
    audio: {
      input: {
        enabled: boolFromSelect('cfg-audio-input-enabled'),
        device: document.getElementById('cfg-audio-input-device')?.value,
        sample_rate: parseInt(document.getElementById('cfg-sample-rate')?.value || '16000', 10),
        channels: parseInt(document.getElementById('cfg-input-channels')?.value || '1', 10),
        record_seconds: parseInt(document.getElementById('cfg-record-seconds')?.value || '5', 10)
      },
      output: {
        enabled: boolFromSelect('cfg-audio-output-enabled'),
        device: document.getElementById('cfg-audio-output-device')?.value,
        volume_percent: parseInt(document.getElementById('cfg-volume')?.value || '80', 10)
      }
    },
    touch: {
      device: document.getElementById('cfg-touch-device')?.value
    },
    face: {
      default_status_text: document.getElementById('cfg-face-status-text')?.value || 'LISTENING...',
      idle_behavior: {
        enabled: boolFromSelect('cfg-idle-enabled'),
        min_seconds: intInput('cfg-idle-min', 35),
        max_seconds: intInput('cfg-idle-max', 90),
        expression_min_seconds: intInput('cfg-idle-expression-min', 5),
        expression_max_seconds: intInput('cfg-idle-expression-max', 11),
        expressions: checkedExpressions()
      }
    },
    api: {
      port: parseInt(document.getElementById('cfg-api-port')?.value || '8088', 10)
    },
    brain: {
      enabled: boolFromSelect('cfg-brain-enabled'),
      provider: document.getElementById('cfg-brain-provider')?.value || 'ollama',
      host: document.getElementById('cfg-brain-host')?.value || 'http://192.168.1.24:11434',
      chat_model: document.getElementById('cfg-brain-model')?.value || 'norm-alpha',
      timeout_seconds: intInput('cfg-brain-timeout', 60),
      stream: document.getElementById('cfg-brain-stream')?.checked === true,
      speaking_hold_seconds: intInput('cfg-brain-speaking-hold', 4),
      max_prompt_chars: intInput('cfg-brain-max-prompt', 2000)
    },
    memory: {
      enabled: boolFromSelect('cfg-memory-enabled'),
      database_path: document.getElementById('cfg-memory-db')?.value || 'data/norm_memory.sqlite3',
      session_id: document.getElementById('cfg-memory-session')?.value || 'default',
      max_recent_messages: intInput('cfg-memory-recent', 16),
      include_recent_messages: document.getElementById('cfg-memory-include-recent')?.checked !== false,
      auto_save_messages: document.getElementById('cfg-memory-autosave')?.checked !== false,
      inject_system_prompt: document.getElementById('cfg-memory-system-prompt')?.checked !== false,
      include_session_summary: false,
      include_long_term_memories: false,
      max_long_term_memories: 8,
      max_memory_block_chars: 6000,
      max_runtime_context_chars: 2000,
      vector_enabled: false,
      embedding_provider: 'ollama',
      embedding_model: 'nomic-embed-text',
      vector_top_k: 5,
      vector_min_score: 0.65
    },
    speech: {
      tts: {
        enabled: boolFromSelect('cfg-tts-enabled'),
        provider: document.getElementById('cfg-tts-provider')?.value || 'espeak-ng',
        voice_preset: document.getElementById('cfg-tts-preset')?.value || 'creepy_terminal',
        voice: document.getElementById('cfg-tts-voice')?.value || 'en-us+m3',
        speed: intInput('cfg-tts-speed', 130),
        pitch: intInput('cfg-tts-pitch', 28),
        amplitude: intInput('cfg-tts-amplitude', 135),
        word_gap: intInput('cfg-tts-word-gap', 5),
        max_spoken_chars: intInput('cfg-tts-max-chars', 500),
        test_phrase: document.getElementById('cfg-tts-test-phrase')?.value || 'Routine oversight is active. Your compliance has been logged.',
        speak_brain_responses_by_default: document.getElementById('cfg-tts-speak-default')?.checked === true,
        output_path: '/tmp/norm_tts.wav',
        future_providers: ['piper', 'remote']
      }
    }
  };

  setPre('config-result', 'saving device settings...');
  const r = await postJSON('/api/config/device-settings', payload);
  setPre('config-result', r);
  await loadConfigOptions();
  await pollStatus();
}

async function loadRawConfig() {
  const r = await (await fetch('/api/config')).json();
  const raw = document.getElementById('raw-config');
  if (raw) raw.value = JSON.stringify(r, null, 2);
  setPre('config-result', 'raw config loaded into editor');
}

async function saveRawConfig() {
  const raw = document.getElementById('raw-config');
  if (!raw) return;
  let parsed;
  try {
    parsed = JSON.parse(raw.value);
  } catch (e) {
    setPre('config-result', 'JSON parse error: ' + e);
    return;
  }
  setPre('config-result', 'saving raw config...');
  const r = await postJSON('/api/config/raw', {config: parsed});
  setPre('config-result', r);
  await loadConfigOptions();
}

async function reloadConfigNotice() {
  const r = await postJSON('/api/config/reload', {});
  setPre('config-result', r);
}


async function refreshBrainStatus(showRaw = true) {
  try {
    const r = await (await fetch('/api/brain/status')).json();
    setText('brain-status', r.status || (r.ok ? 'ready' : 'offline'));
    setText('brain-host', r.host);
    setText('brain-model', r.model);
    setText('brain-latency', r.latency_ms == null ? '--' : `${r.latency_ms} ms`);
    if (showRaw) setPre('brain-result', r);
    await pollStatus();
  } catch (e) {
    setPre('brain-result', 'brain status error: ' + e);
  }
}

async function askBrain() {
  const prompt = document.getElementById('brain-prompt')?.value || '';
  const context = document.getElementById('brain-context')?.value || '';
  if (!prompt.trim()) {
    setPre('brain-response', 'Prompt is empty. Even N.O.R.M. needs something to brood over.');
    return;
  }
  setPre('brain-response', 'PROCESSING...');
  setPre('brain-result', 'waiting for Ollama...');
  const started = Date.now();
  try {
    const speak = document.getElementById('brain-speak')?.checked === true;
    const r = await postJSON('/api/brain/ask', {prompt, context, speak});
    const elapsed = Date.now() - started;
    setPre('brain-response', r.response || '(no response)');
    setPre('brain-result', {...r, browser_elapsed_ms: elapsed});
    await refreshSpeechStatus(false);
    await pollStatus();
  } catch (e) {
    setPre('brain-response', 'Brain request failed: ' + e);
    setPre('brain-result', 'Brain request failed: ' + e);
  }
}

function askPreset(prompt) {
  const el = document.getElementById('brain-prompt');
  if (el) el.value = prompt;
  askBrain();
}

function clearBrainOutput() {
  const p = document.getElementById('brain-prompt');
  const c = document.getElementById('brain-context');
  if (p) p.value = '';
  if (c) c.value = '';
  setPre('brain-response', 'awaiting prompt...');
  setPre('brain-result', 'cleared.');
}

async function refreshSpeechStatus(showRaw = true) {
  try {
    const r = await (await fetch('/api/speech/status')).json();
    setText('speech-status', r.status || (r.ok ? 'ready' : 'error'));
    setText('tts-provider', r.provider || '--');
    setText('tts-preset', r.voice_preset || '--');
    setText('tts-voice', r.voice || '--');
    setText('tts-speed-pitch', `${r.speed ?? '--'} / ${r.pitch ?? '--'}`);
    setText('tts-word-gap', r.word_gap ?? '--');
    if (showRaw) setPre('speech-result', r);
    const player = document.getElementById('tts-player');
    if (player && r.output_exists) player.src = '/api/speech/latest.wav?cache=' + Date.now();
    return r;
  } catch (e) {
    setPre('speech-result', 'speech status error: ' + e);
  }
}

async function speakText(text) {
  setPre('speech-result', 'synthesizing speech...');
  const r = await postJSON('/api/speech/speak', {text});
  setPre('speech-result', r);
  await refreshSpeechStatus(false);
  await pollStatus();
  return r;
}

async function speakTest() {
  setPre('speech-result', 'running TTS test...');
  const r = await postJSON('/api/speech/speak-test', {});
  setPre('speech-result', r);
  await refreshSpeechStatus(false);
  await pollStatus();
}

async function speakLastBrainResponse() {
  const text = document.getElementById('brain-response')?.textContent || '';
  if (!text.trim() || text.includes('awaiting prompt')) {
    setPre('speech-result', 'No response to speak yet. Ask N.O.R.M. something first.');
    return;
  }
  await speakText(text);
}


async function refreshMemoryStatus(showRaw = true) {
  try {
    const r = await (await fetch('/api/memory/status')).json();
    setText('memory-enabled', r.enabled === true ? 'yes' : 'no');
    setText('memory-db', r.database_path || '--');
    setText('memory-session', r.session_id || '--');
    setText('memory-message-count', r.message_count == null ? '--' : r.message_count);
    setText('memory-long-count', r.long_term_memory_count == null ? '--' : r.long_term_memory_count);
    setText('memory-summary', r.summary_exists ? 'exists' : 'none');
    if (showRaw) setPre('memory-result', r);
    return r;
  } catch (e) {
    setPre('memory-result', 'memory status error: ' + e);
  }
}

async function refreshMemoryRecent() {
  try {
    const r = await (await fetch('/api/memory/recent?limit=30')).json();
    if (!r.enabled) {
      setPre('memory-recent', 'Memory disabled in config.');
    } else {
      const lines = (r.messages || []).map(m => `${m.id} ${m.created_at} ${String(m.role).toUpperCase()}: ${m.content}`);
      setPre('memory-recent', lines.length ? lines.join('\n\n') : 'No messages stored yet.');
    }
    setPre('memory-result', r);
    await refreshMemoryStatus(false);
  } catch (e) {
    setPre('memory-result', 'recent memory error: ' + e);
  }
}

async function refreshMemoryLongTerm() {
  try {
    const r = await (await fetch('/api/memory/long-term?limit=50')).json();
    if (!r.enabled) {
      setPre('memory-long-term', 'Memory disabled in config.');
    } else {
      const lines = (r.memories || []).map(m => `${m.id} [${m.memory_type} / ${m.importance}] ${m.text}\nsource=${m.source || '--'} created=${m.created_at}`);
      setPre('memory-long-term', lines.length ? lines.join('\n\n') : 'No long-term memories stored yet.');
    }
    setPre('memory-result', r);
    await refreshMemoryStatus(false);
  } catch (e) {
    setPre('memory-result', 'long-term memory error: ' + e);
  }
}

async function saveManualMemory() {
  const text = document.getElementById('memory-text')?.value || '';
  if (!text.trim()) {
    setPre('memory-result', 'Memory text is empty. The archive demands substance.');
    return;
  }
  const payload = {
    text,
    memory_type: document.getElementById('memory-type')?.value || 'note',
    importance: parseInt(document.getElementById('memory-importance')?.value || '5', 10)
  };
  const r = await postJSON('/api/memory/remember', payload);
  setPre('memory-result', r);
  if (r.ok) {
    const el = document.getElementById('memory-text');
    if (el) el.value = '';
  }
  await refreshMemoryStatus(false);
  await refreshMemoryLongTerm();
}

async function clearMemorySession() {
  const ok = confirm('Clear the current conversation memory session? Long-term memories stay intact.');
  if (!ok) return;
  const r = await postJSON('/api/memory/clear-session', {});
  setPre('memory-result', r);
  await refreshMemoryStatus(false);
  await refreshMemoryRecent();
}

function fillVoicePresets(presets, configured) {
  const el = document.getElementById('cfg-tts-preset');
  if (!el) return;
  el.innerHTML = '';
  for (const p of presets || []) {
    const opt = document.createElement('option');
    opt.value = p.id;
    opt.textContent = `${p.name} — ${p.voice}, s${p.speed}, p${p.pitch}, g${p.word_gap}`;
    opt.dataset.voice = p.voice;
    opt.dataset.speed = p.speed;
    opt.dataset.pitch = p.pitch;
    opt.dataset.amplitude = p.amplitude;
    opt.dataset.wordGap = p.word_gap;
    el.appendChild(opt);
  }
  setSelectValue('cfg-tts-preset', configured || 'creepy_terminal');
}

function applyVoicePreset() {
  const el = document.getElementById('cfg-tts-preset');
  const opt = el?.selectedOptions?.[0];
  if (!opt) return;
  setSelectValue('cfg-tts-voice', opt.dataset.voice || 'en-us+m3');
  setInputValue('cfg-tts-speed', opt.dataset.speed || 130);
  setInputValue('cfg-tts-pitch', opt.dataset.pitch || 28);
  setInputValue('cfg-tts-amplitude', opt.dataset.amplitude || 135);
  setInputValue('cfg-tts-word-gap', opt.dataset.wordGap || 5);
  setPre('config-result', `applied preset: ${opt.textContent}. Click Save Settings to persist.`);
}
