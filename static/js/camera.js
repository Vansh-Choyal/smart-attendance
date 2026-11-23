(() => {
  'use strict';
  const A = window.Attend, $ = A.$, feed = A.makeFeed($('monitor-feed'));
  let state = null, busy = false, successUntil = 0;
  function layout() {
    if (!state?.camera?.width || !state.camera.height) return;
    const width = $('camera-stage').clientWidth, height = $('camera-stage').clientHeight;
    const scale = Math.max(width/state.camera.width, height/state.camera.height);
    Object.assign($('video-plane').style, {width:state.camera.width*scale+'px',height:state.camera.height*scale+'px',left:(width-state.camera.width*scale)/2+'px',top:(height-state.camera.height*scale)/2+'px'});
    const [left,top,right,bottom] = state.zone;
    Object.assign($('detection-zone').style, {left:left*100+'%',top:top*100+'%',width:(right-left)*100+'%',height:(bottom-top)*100+'%'});
  }
  function boxes() {
    $('face-boxes').replaceChildren();
    for (const face of state.faces) {
      const [left,top,right,bottom] = face.box, zone = state.zone;
      const inside = (left+right)/2 >= zone[0] && (left+right)/2 <= zone[2] && (top+bottom)/2 >= zone[1] && (top+bottom)/2 <= zone[3];
      const box = document.createElement('div'); box.className = 'face-box'+(inside ? ' inside' : '');
      Object.assign(box.style,{left:left*100+'%',top:top*100+'%',width:(right-left)*100+'%',height:(bottom-top)*100+'%'});
      $('face-boxes').append(box);
    }
  }
  function render(data) {
    state = data;
    const camera = data.camera, connected = camera.connected && A.online, show = connected && A.operator;
    const own = !!window.BrowserCamera?.stream && camera.source?.type === 'browser';
    feed.update(camera,A.operator && A.online && !own);
    $('browser-monitor-feed').hidden = !own;
    $('monitor-empty').hidden = show;
    $('video-plane').classList.toggle('visible',show);
    $('monitor-source').textContent = camera.source?.label || 'Entrance camera';
    $('monitor-live-label').textContent = connected ? 'Live' : camera.phase === 'connecting' ? 'Connecting' : 'Offline';
    $('monitor-live-dot').classList.toggle('live',connected);
    $('monitor-unlock').hidden = A.operator || !connected;
    $('monitor-setup-link').hidden = !A.operator && connected;
    if (!A.operator && connected) {
      $('monitor-empty-title').textContent = 'Operator access required';
      $('monitor-empty-description').textContent = 'Unlock this browser to view the live camera and confirm attendance.';
    } else {
      $('monitor-empty-title').textContent = camera.source?.type === 'browser' ? 'Connect your phone browser' : camera.source ? camera.phase === 'connecting' ? 'Connecting to camera…' : 'Camera disconnected' : 'Connect a camera to begin';
      $('monitor-empty-description').textContent = camera.source?.type === 'browser' ? 'Open Setup on your phone and tap Use this phone’s camera. Keep that page open while streaming.' : camera.source ? 'Check the device and local network. Attend will reconnect automatically.' : 'Choose a built-in webcam or connect your phone on the same Wi-Fi network.';
    }
    $('monitor-status').textContent = !A.operator ? 'Operator controls locked' : data.message;
    $('monitor-instruction').textContent = data.model.error || (!A.operator ? 'Unlock this browser to mark attendance' : data.state === 'WAITING_FOR_CLEAR' || data.state === 'RECORDED' ? 'Have the subject step out before the next entry' : data.ready ? 'Ready for operator confirmation' : 'One person in the zone at a time');
    $('zone-status').textContent = data.message;
    $('detection-zone').classList.toggle('detected',data.faces_in_zone === 1);
    $('toolbar-status-icon').classList.toggle('ready',data.ready && A.operator);
    const recorded = Date.now() < successUntil || data.state === 'RECORDED';
    $('mark-attendance').classList.toggle('recorded',recorded);
    $('mark-button-label').textContent = recorded ? 'Attendance recorded' : 'Mark attendance';
    $('mark-attendance').disabled = busy || !A.operator || !A.online || !data.ready || recorded;
    layout(); boxes();
  }
  async function mark() {
    if (busy || !$('mark-attendance') || $('mark-attendance').disabled || !state?.ready) return;
    busy = true; $('mark-attendance').disabled = true;
    try {
      const result = await A.post('/api/attendance/mark',{session_id:state.session_id});
      successUntil = Date.now()+1100;
      $('monitor-count').textContent = result.stats.total.toLocaleString('en-IN');
      render(result.detection); A.toast('Attendance recorded · '+A.formatTime(result.event.timestamp,true));
    } catch (error) { A.toast(error.message,true); }
    finally { busy = false; if (state) render(state); }
  }
  $('mark-attendance').addEventListener('click',mark);
  document.addEventListener('keydown',event => {
    const target = event.target;
    if (target.matches('input,textarea,select,button,a') || target.isContentEditable || document.querySelector('dialog[open]')) return;
    if ((event.code === 'Space' || event.code === 'Enter' || event.code === 'NumpadEnter') && !event.repeat && !$('mark-attendance').disabled) { event.preventDefault(); mark(); }
    if (event.key === 'Escape' && document.fullscreenElement) document.exitFullscreen().catch(()=>{});
  });
  $('fullscreen-button').addEventListener('click',async () => {
    try { if (document.fullscreenElement) await document.exitFullscreen(); else await document.documentElement.requestFullscreen(); }
    catch { A.toast('Fullscreen is unavailable in this browser.',true); }
  });
  document.addEventListener('fullscreenchange',() => {
    const full = !!document.fullscreenElement;
    $('fullscreen-button').setAttribute('aria-label',full ? 'Exit fullscreen' : 'Enter fullscreen');
    $('fullscreen-button').replaceChildren(); const icon = document.createElement('i'); icon.dataset.lucide = full ? 'minimize' : 'maximize'; $('fullscreen-button').append(icon); A.icons($('fullscreen-button')); layout();
  });
  window.addEventListener('attend:status', event => render(event.detail));
  window.addEventListener('attend:auth', () => { if (state) render(state); });
  window.addEventListener('attend:browser-camera',event => { if (event.detail.phase === 'error' && event.detail.error) A.toast(event.detail.error,true); if (state) render(state); });
  window.addEventListener('attend:offline',() => {
    feed.stop(); $('mark-attendance').disabled = true; $('monitor-empty').hidden = false; $('video-plane').classList.remove('visible');
    $('monitor-empty-title').textContent = 'Local server unreachable'; $('monitor-empty-description').textContent = 'Check that Attend is running. Attendance is paused until fresh detection returns.';
    $('monitor-status').textContent = 'Connection lost'; $('monitor-instruction').textContent = 'Attendance is paused'; $('monitor-live-label').textContent = 'Offline'; $('monitor-live-dot').classList.remove('live');
  });
  new ResizeObserver(layout).observe($('camera-stage'));
  window.addEventListener('pagehide',() => feed.stop());
  function clock() { $('monitor-clock').textContent = A.formatTime(new Date().toISOString(),true); }
  async function count() { try { const data = await A.api('/api/attendance/stats'); $('monitor-count').textContent = data.total.toLocaleString('en-IN'); } catch {} }
  clock(); setInterval(clock,1000); count(); setInterval(count,2000);
})();
