/* Direct phone capture: one current JPEG per request, never a frame queue. */
(() => {
  'use strict';
  const A = window.Attend;
  const preferenceKey = 'attend.browser-camera';
  function remember(value) {
    try { if (value) sessionStorage.setItem(preferenceKey,JSON.stringify(value)); else sessionStorage.removeItem(preferenceKey); } catch {}
  }
  function preference() { try { return JSON.parse(sessionStorage.getItem(preferenceKey)); } catch { return null; } }
  const C = window.BrowserCamera = {
    stream:null, video:null, token:null, ticket:null, sequence:0, fps:12,
    enabled:false, starting:false, sending:false, epoch:0, facing:'environment', error:'', phase:'idle',
    secureUrl() {
      const port = Number(document.body.dataset.httpsPort);
      if (!port) return null;
      const url = new URL('/setup',location.href); url.protocol = 'https:'; url.port = String(port); url.hash = 'phone-camera'; return url.href;
    },
    emit() {
      const banner = A.$('browser-stream-banner');
      banner.hidden = !this.stream;
      if (this.stream) A.$('browser-stream-banner-label').textContent = this.phase === 'live' ? 'This device is streaming its camera' : this.phase === 'paused' ? 'Camera paused while this page is in the background' : 'Camera connected · reconnecting to the server';
      window.dispatchEvent(new CustomEvent('attend:browser-camera',{detail:{active:!!this.stream,phase:this.phase,error:this.error}}));
    },
    async start(facing = 'environment', automatic = false) {
      if (this.starting) return false;
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        this.error = location.protocol === 'https:' ? 'Your browser has not enabled camera access for this HTTPS connection. Check that it trusts the local certificate and that camera access is allowed, then reload.' : this.secureUrl() ? 'Open the secure connection below to allow your phone camera.' : 'Phone browser cameras require HTTPS. Start Attend with --lan to enable the secure connection.';
        this.phase = 'error'; this.emit(); return false;
      }
      this.starting = true;
      await A.ready;
      if (!A.operator && automatic) { this.starting = false; this.error = 'Unlock operator controls, then tap Use this phone’s camera.'; this.emit(); return false; }
      if (!await A.requireOperator()) { this.starting = false; return false; }
      await this.stop(false);
      this.phase = 'starting'; this.error = ''; this.emit();
      const epoch = ++this.epoch;
      let media = null;
      try {
        media = await navigator.mediaDevices.getUserMedia({audio:false,video:{facingMode:{ideal:facing},width:{ideal:720},height:{ideal:1280},aspectRatio:{ideal:9/16},frameRate:{ideal:20,max:24}}});
        if (epoch !== this.epoch) { media.getTracks().forEach(track => track.stop()); return false; }
        const video = document.querySelector('.browser-local-video') || document.createElement('video');
        video.muted = true; video.autoplay = true; video.playsInline = true; video.srcObject = media;
        if (!video.isConnected) { video.hidden = true; document.body.append(video); }
        await video.play();
        if (!video.videoWidth) await new Promise((resolve,reject) => {
          const timeout = setTimeout(() => reject(new Error('The camera did not provide a video frame. Try again.')),6000);
          video.addEventListener('loadeddata',() => { clearTimeout(timeout); resolve(); },{once:true});
        });
        if (epoch !== this.epoch) { media.getTracks().forEach(track => track.stop()); return false; }
        const result = await A.post('/api/camera/browser/start');
        if (epoch !== this.epoch) {
          media.getTracks().forEach(track => track.stop());
          await A.post('/api/camera/browser/stop',{publisher_token:result.publisher_token}).catch(()=>{}); return false;
        }
        this.stream = media; this.video = video; this.token = result.publisher_token;
        this.ticket = result.capture_ticket; this.sequence = result.sequence; this.fps = result.fps;
        this.facing = facing; this.enabled = true; this.phase = 'connecting';
        remember({facing});
        media.getVideoTracks()[0].addEventListener('ended',() => { if (epoch === this.epoch) { this.stop(); A.toast('The phone camera stopped. Connect it again to continue.',true); } });
        video.hidden = false;
        this.canvas = document.createElement('canvas');
        this.context = this.canvas.getContext('2d',{alpha:false});
        this.emit(); this.tick(epoch); return true;
      } catch (error) {
        if (media) media.getTracks().forEach(track => track.stop());
        if (epoch !== this.epoch) return false;
        const messages = {NotAllowedError:'Camera access was denied. Allow camera access for this site, then try again.',NotFoundError:'No camera was found on this device.',NotReadableError:'The camera is being used by another app. Close it and try again.',OverconstrainedError:'This camera cannot provide the requested video. Try the other camera.'};
        this.error = messages[error.name] || error.message;
        this.phase = 'error'; this.enabled = false; remember(null); this.emit(); return false;
      } finally { this.starting = false; }
    },
    async tick(epoch) {
      if (!this.enabled || epoch !== this.epoch) return;
      if (document.hidden) { if (this.phase !== 'paused') { this.phase = 'paused'; this.emit(); } this.needTicket = true; this.timer = setTimeout(() => this.tick(epoch),500); return; }
      const start = performance.now();
      try {
        if (this.needTicket) {
          const result = await A.post('/api/camera/browser/renew',{publisher_token:this.token});
          if (epoch !== this.epoch) return;
          this.ticket = result.capture_ticket; this.sequence = result.sequence; this.needTicket = false;
        }
        const scale = Math.min(1,1280/Math.max(this.video.videoWidth,this.video.videoHeight));
        this.canvas.width = Math.max(1,Math.round(this.video.videoWidth*scale));
        this.canvas.height = Math.max(1,Math.round(this.video.videoHeight*scale));
        this.context.drawImage(this.video,0,0,this.canvas.width,this.canvas.height);
        const jpeg = await new Promise(resolve => this.canvas.toBlob(resolve,'image/jpeg',.85));
        if (!jpeg || epoch !== this.epoch) return;
        const result = await A.api('/api/camera/browser/frame',{method:'POST',body:jpeg,timeout:2500,headers:{'Content-Type':'image/jpeg','X-Camera-Session':this.token,'X-Capture-Ticket':this.ticket,'X-Frame-Sequence':String(this.sequence)}});
        if (epoch !== this.epoch) return;
        this.ticket = result.capture_ticket; this.sequence = result.sequence;
        const changed = this.phase !== 'live' || this.error;
        this.phase = 'live'; this.error = ''; this.retry = 0;
        if (changed) this.emit();
      } catch (error) {
        if (epoch !== this.epoch) return;
        if (['publisher_changed','authentication_required'].includes(error.code)) {
          await this.stop(); this.error = error.message; this.phase = 'error'; this.emit(); return;
        }
        this.needTicket = true; this.phase = 'reconnecting'; this.error = error.message;
        this.retry = Math.min((this.retry || 0)+1,4); this.emit();
      }
      if (epoch === this.epoch && this.enabled) this.timer = setTimeout(() => this.tick(epoch),this.retry ? Math.min(250*2**this.retry,4000) : Math.max(10,1000/this.fps-(performance.now()-start)));
    },
    async stop(forget = true) {
      ++this.epoch; this.enabled = false; clearTimeout(this.timer);
      const token = this.token; this.token = null; this.needTicket = false; this.retry = 0;
      if (this.stream) this.stream.getTracks().forEach(track => track.stop());
      if (this.video) { this.video.pause(); this.video.srcObject = null; this.video.hidden = true; }
      this.stream = null; this.video = null; this.phase = 'idle';
      if (forget) remember(null);
      this.emit();
      if (token) await A.post('/api/camera/browser/stop',{publisher_token:token}).catch(()=>{});
    }
  };
  A.$('browser-stream-stop').addEventListener('click',() => C.stop());
  window.addEventListener('attend:auth',event => { if (!event.detail) C.stop(); });
  window.addEventListener('pagehide',() => {
    if (!C.token) return;
    const token = C.token; C.token = null; C.enabled = false; ++C.epoch;
    C.stream?.getTracks().forEach(track => track.stop());
    fetch('/api/camera/browser/stop',{method:'POST',credentials:'same-origin',keepalive:true,headers:{'Content-Type':'application/json','X-CSRF-Token':A.csrf},body:JSON.stringify({publisher_token:token})}).catch(()=>{});
  });
  window.addEventListener('pageshow',event => { if (event.persisted && preference()) C.start(preference().facing,true); });
  A.ready.then(() => { const saved = preference(); if (saved && A.operator) C.start(saved.facing,true); });
})();
