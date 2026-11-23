(() => {
  'use strict';
  const A = window.Attend, C = window.BrowserCamera, $ = A.$, feed = A.makeFeed($('preview-feed'));
  let saved = null, useSaved = false, busy = false, tested = false, phoneMode = 'browser';
  const chosen = () => document.querySelector('input[name="source"]:checked').value;
  const isBrowser = () => chosen() === 'ip' && phoneMode === 'browser';
  function feedback(copy,tone = '') { $('connection-feedback').textContent = copy; $('connection-feedback').className = 'connection-feedback '+tone; }
  function updateFields() {
    const phone = chosen() === 'ip', browser = phone && phoneMode === 'browser';
    $('ip-fields').hidden = !phone || browser; $('browser-fields').hidden = !browser; $('webcam-fields').hidden = phone;
    $('test-camera').hidden = browser;
    $('source-title').textContent = browser ? 'Connect this phone' : phone ? 'Connect an IP camera' : 'Connect your camera';
    $('source-description').textContent = browser ? 'Stream directly to Attend. No extra app needed.' : phone ? 'Enter the direct address of an existing camera stream.' : 'Select a device, then check its live preview.';
    $('manual-index-row').hidden = $('camera-index').value !== 'manual';
    $('use-saved').hidden = !phone || browser || saved?.type !== 'ip';
    useSaved = false; tested = false;
    feedback(browser ? 'Tap the camera button on the device you want to stream from.' : 'Test the selected source to check its connection.');
    const secure = C.secureUrl();
    $('secure-camera-link').hidden = window.isSecureContext || !secure || location.protocol === 'https:';
    if (secure) $('secure-camera-link').href = secure;
    $('browser-camera-help').textContent = !window.isSecureContext ? 'Phone cameras need a secure connection. The button opens local HTTPS; your browser may ask you to trust this laptop.' : 'Allow camera access when asked. Keep Attend open and the phone awake while streaming.';
  }
  document.querySelectorAll('input[name="source"]').forEach(input => input.addEventListener('change',updateFields));
  $('show-ip-fields').addEventListener('click',() => { phoneMode = 'ip'; updateFields(); });
  $('show-browser-fields').addEventListener('click',() => { phoneMode = 'browser'; updateFields(); });
  $('camera-index').addEventListener('change',updateFields);
  $('stream-url').addEventListener('input',() => { useSaved = false; tested = false; });
  $('use-saved').addEventListener('click',() => { useSaved = true; $('stream-url').value = ''; feedback('Saved encrypted stream selected. Test its connection.'); });
  async function startPhone() {
    if (!window.isSecureContext && location.protocol !== 'https:' && C.secureUrl()) { window.location.assign(C.secureUrl()); return false; }
    $('start-browser-camera').disabled = true;
    try { return await C.start($('browser-facing').value); }
    finally { $('start-browser-camera').disabled = false; }
  }
  $('start-browser-camera').addEventListener('click',startPhone);
  $('browser-facing').addEventListener('change',() => { if (C.stream) startPhone(); });
  function payload() {
    if (isBrowser()) return {type:'browser'};
    if (chosen() === 'ip') return useSaved ? {use_saved:true} : {type:'ip',url:$('stream-url').value.trim()};
    return {type:'webcam',index:Number($('camera-index').value === 'manual' ? $('manual-index').value : $('camera-index').value)};
  }
  async function connect(save) {
    if (busy || !await A.requireOperator()) return;
    const source = payload();
    if (source.type === 'ip' && !source.url) { feedback('Enter a stream URL or choose the saved IP camera.','error'); $('stream-url').focus(); return; }
    busy = true; $('test-camera').disabled = $('save-camera').disabled = true;
    try {
      if (source.type === 'browser') {
        const remotePhone = A.status?.camera?.source?.type === 'browser' && A.status.camera.connected && !C.stream;
        if (!C.stream && !remotePhone && !await startPhone()) return;
        if (C.stream) {
          feedback('Waiting for the first camera frame…');
          const deadline = Date.now()+10000;
          while (C.phase !== 'live' && C.stream && Date.now()<deadline) await new Promise(resolve => setTimeout(resolve,100));
          if (C.phase !== 'live') throw new Error(C.error || 'The camera has not reached the server yet. Check the connection and try again.');
        }
      } else if (C.stream) await C.stop();
      feedback(save ? 'Saving camera configuration…' : 'Connecting to camera…');
      const result = await A.post(save ? '/api/camera/select' : '/api/camera/test',source);
      tested = true; feedback(result.message);
      if (save) window.location.assign(source.type === 'browser' && C.stream ? '/camera' : '/dashboard');
    } catch (error) { feedback(error.message,'error'); }
    finally { busy = false; $('test-camera').disabled = $('save-camera').disabled = false; }
  }
  $('test-camera').addEventListener('click',() => connect(false));
  $('save-camera').addEventListener('click',() => connect(true));
  $('scan-cameras').addEventListener('click',async () => {
    if (!await A.requireOperator()) return;
    $('scan-cameras').disabled = true; $('scan-feedback').textContent = 'Looking for connected cameras…';
    try {
      const data = await A.api('/api/cameras'), current = $('camera-index').value;
      $('camera-index').replaceChildren();
      for (const device of data.cameras) { const option = document.createElement('option'); option.value = device.index; option.textContent = device.label; $('camera-index').append(option); }
      const manual = document.createElement('option'); manual.value = 'manual'; manual.textContent = data.cameras.length ? 'Enter another device index' : 'No cameras found — enter index'; $('camera-index').append(manual);
      if ([...$('camera-index').options].some(option => option.value === current) && current !== 'manual') $('camera-index').value = current;
      $('manual-index-row').hidden = $('camera-index').value !== 'manual';
      $('scan-feedback').textContent = data.cameras.length ? `${data.cameras.length} camera${data.cameras.length === 1 ? '' : 's'} available.` : 'No camera responded. Check its USB connection, Windows camera access, or enter its index.';
    } catch (error) { $('scan-feedback').textContent = error.message; }
    finally { $('scan-cameras').disabled = false; }
  });
  function render(state) {
    const camera = state.camera, own = !!C.stream && camera.source?.type === 'browser';
    feed.update(camera,A.operator && A.online && !own);
    $('browser-local-preview').hidden = !own;
    $('preview-empty').hidden = own || (camera.connected && A.operator && A.online);
    $('preview-status').classList.toggle('connected',camera.connected);
    $('preview-status').replaceChildren();
    const dot = document.createElement('span'); dot.className = 'dot';
    $('preview-status').append(dot,document.createTextNode(camera.connected ? 'Connected' : camera.phase === 'connecting' ? 'Connecting' : camera.phase === 'awaiting_browser' ? 'Waiting for phone' : 'Not connected'));
    if (!A.operator && camera.connected) {
      $('preview-empty-title').textContent = 'Unlock to view the live camera'; $('preview-empty-description').textContent = 'The live preview is restricted to authorized operators.';
    } else if (camera.source?.type === 'browser' && !camera.connected) {
      $('preview-empty-title').textContent = 'Waiting for your phone camera'; $('preview-empty-description').textContent = 'Open Attend on your phone and tap Use this phone’s camera.';
    } else if (camera.source && !camera.connected) {
      $('preview-empty-title').textContent = camera.phase === 'connecting' ? 'Connecting to camera…' : 'Camera is disconnected';
      $('preview-empty-description').textContent = camera.retry ? `Retrying automatically with a delay of up to ${camera.retry_in || 16} seconds. Check the device or stream address.` : 'Waiting for the first live frame from your device.';
    }
    if (tested && !busy) {
      if (camera.connected) feedback('Connected. Live video is available.','success');
      else if (camera.phase === 'disconnected') feedback('Connection lost or unavailable. Retrying automatically. Check the camera and network.','error');
    }
    $('model-notice').hidden = !state.model.error;
    if (state.model.error) $('model-notice-message').textContent = state.model.error;
  }
  window.addEventListener('attend:status',event => render(event.detail));
  window.addEventListener('attend:auth',() => { if (A.status) render(A.status); });
  window.addEventListener('attend:browser-camera',event => {
    $('browser-camera-error').textContent = event.detail.error;
    if (event.detail.active) { tested = true; feedback(event.detail.phase === 'live' ? 'Streaming directly from this browser.' : event.detail.phase === 'paused' ? 'Streaming pauses when this page is in the background.' : 'Connecting your browser camera…',event.detail.phase === 'live' ? 'success' : ''); }
    if (A.status) render(A.status);
  });
  window.addEventListener('attend:offline',() => { feed.stop(); if (!C.stream) $('preview-empty').hidden = false; $('preview-empty-title').textContent = 'Local server unreachable'; $('preview-empty-description').textContent = 'Check that Attend is still running on this computer.'; feedback('Cannot reach the local server.','error'); });
  window.addEventListener('pagehide',() => feed.stop());
  const requestedPhone = location.hash === '#phone-camera';
  if (requestedPhone || /Android|iPhone|iPad/i.test(navigator.userAgent)) document.querySelector('input[name="source"][value="ip"]').checked = true;
  updateFields();
  A.api('/api/camera/status').then(data => {
    saved = data.saved_source;
    if (saved && !requestedPhone) {
      document.querySelector(`input[name="source"][value="${saved.type === 'webcam' ? 'webcam' : 'ip'}"]`).checked = true;
      phoneMode = saved.type === 'ip' ? 'ip' : 'browser'; updateFields();
      if (saved.type === 'ip') { useSaved = true; feedback('Your saved encrypted IP camera is selected.'); }
      else if (saved.type === 'webcam') { $('manual-index').value = saved.index; feedback('Your saved camera is selected.'); }
    }
    if (data.configuration_error) feedback(data.configuration_error,'error');
  }).catch(error => feedback(error.message,'error'));
})();
