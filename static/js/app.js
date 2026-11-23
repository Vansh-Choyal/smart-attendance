/* Shared browser session, status polling and accessible operator controls. */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const App = window.Attend = {
    operator: document.body.dataset.operator === 'true',
    timezone: document.body.dataset.timezone,
    csrf: document.querySelector('meta[name="csrf-token"]').content,
    status: null,
    online: false,
    $,
    icons(root = document) { if (window.lucide) lucide.createIcons({root}); },
    async api(path, options = {}) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), options.timeout || 12000);
      try {
        const headers = {'Accept': 'application/json', ...options.headers};
        if (options.method && options.method !== 'GET') {
          headers['Content-Type'] ||= 'application/json';
          headers['X-CSRF-Token'] = this.csrf;
        }
        const response = await fetch(path, {...options, headers, credentials: 'same-origin', signal: controller.signal, cache: 'no-store'});
        const body = await response.json();
        if (!response.ok || !body.ok) {
          if (response.status === 401 && body.error?.code === 'authentication_required') this.setOperator(false);
          const error = new Error(body.error?.message || 'The request could not be completed.');
          error.code = body.error?.code;
          throw error;
        }
        return body.data;
      } catch (error) {
        if (error.name === 'AbortError') throw new Error('The server took too long to respond. Check the connection and try again.');
        if (error instanceof TypeError) throw new Error('Cannot reach the local server. Check that Attend is running.');
        throw error;
      } finally { clearTimeout(timeout); }
    },
    post(path, body = {}) { return this.api(path, {method: 'POST', body: JSON.stringify(body)}); },
    toast(message, error = false) {
      const item = document.createElement('div');
      item.className = 'toast' + (error ? ' error' : '');
      const icon = document.createElement('i'); icon.dataset.lucide = error ? 'circle-alert' : 'circle-check';
      const copy = document.createElement('span'); copy.textContent = message;
      item.append(icon, copy); $('toast-stack').append(item); this.icons(item);
      setTimeout(() => item.remove(), error ? 6500 : 4000);
    },
    formatTime(stamp, seconds = false) {
      return stamp ? new Intl.DateTimeFormat('en-IN', {hour:'2-digit', minute:'2-digit', ...(seconds ? {second:'2-digit'} : {}), hour12: false, timeZone:this.timezone}).format(new Date(stamp)) : '—';
    },
    formatDate(date, options = {}) {
      const dayOnly = date.length === 10;
      return new Intl.DateTimeFormat('en-IN', {day:'numeric', month:'short', timeZone:dayOnly ? 'UTC' : this.timezone, ...options}).format(new Date(dayOnly ? date+'T12:00:00Z' : date));
    },
    today() { return new Intl.DateTimeFormat('en-CA', {year:'numeric',month:'2-digit',day:'2-digit',timeZone:this.timezone}).format(new Date()); },
    setOperator(value) {
      this.operator = value; document.body.dataset.operator = String(value);
      document.querySelectorAll('[data-auth-button]').forEach(button => {
        if (button.id === 'monitor-unlock') return;
        button.replaceChildren();
        const icon = document.createElement('i'); icon.dataset.lucide = value ? 'lock-open' : 'lock-keyhole';
        const copy = document.createElement('span'); copy.textContent = value ? 'Operator' : 'Unlock controls';
        button.append(icon, copy); this.icons(button);
      });
      window.dispatchEvent(new CustomEvent('attend:auth', {detail:value}));
    },
    requireOperator() {
      if (this.operator) return Promise.resolve(true);
      $('auth-error').textContent = '';
      if (!$('auth-dialog').open) { $('auth-dialog').showModal(); $('operator-pin').focus(); }
      return new Promise(resolve => {
        const closed = () => { $('auth-dialog').removeEventListener('close', closed); resolve(this.operator); };
        $('auth-dialog').addEventListener('close', closed);
      });
    },
    makeFeed(img) {
      let running = false, generation = null, started = 0, retryAfter = 0;
      img.addEventListener('error', () => { running = false; img.hidden = true; img.removeAttribute('src'); retryAfter = Date.now()+1500; });
      return {
        update(camera, permitted) {
          if (!camera?.connected || !permitted) {
            if (running || img.hasAttribute('src')) img.removeAttribute('src');
            running = false; img.hidden = true; return;
          }
          if (Date.now() < retryAfter) return;
          if (!running || generation !== camera.generation || Date.now()-started > 110000) {
            img.src = '/api/camera/feed?t=' + Date.now();
            generation = camera.generation; running = true; started = Date.now();
          }
          img.hidden = false;
        },
        stop() { img.removeAttribute('src'); img.hidden = true; running = false; }
      };
    },
    async pollStatus() {
      try {
        const data = await this.api('/api/detection/status', {timeout:4000});
        this.online = true; this.status = data;
        if ($('system-dot')) $('system-dot').classList.add('live');
        if ($('system-label')) $('system-label').textContent = 'Local system online';
        if ($('header-date')) $('header-date').textContent = this.formatDate(new Date().toISOString(),{weekday:'short'});
        window.dispatchEvent(new CustomEvent('attend:status', {detail:data}));
      } catch (error) {
        this.online = false;
        if ($('system-dot')) $('system-dot').classList.remove('live');
        if ($('system-label')) $('system-label').textContent = 'Server unreachable';
        window.dispatchEvent(new CustomEvent('attend:offline', {detail:error}));
      } finally {
        this.pollTimer = setTimeout(() => this.pollStatus(), document.hidden ? 2500 : document.body.dataset.page === 'camera' ? 350 : 1000);
      }
    }
  };
  App.icons();
  document.querySelectorAll('[data-close-dialog]').forEach(button => button.addEventListener('click', () => $(button.dataset.closeDialog).close()));
  document.querySelectorAll('[data-auth-button]').forEach(button => button.addEventListener('click', () => {
    if (App.operator) $('lock-dialog').showModal(); else App.requireOperator();
  }));
  $('auth-form').addEventListener('submit', async event => {
    event.preventDefault(); $('auth-submit').disabled = true; $('auth-error').textContent = '';
    try {
      const result = await App.post('/api/auth/login', {pin:$('operator-pin').value});
      App.csrf = result.csrf; App.setOperator(true); $('operator-pin').value = ''; $('auth-dialog').close();
      App.toast('Operator controls unlocked.');
    } catch (error) { $('auth-error').textContent = error.message; }
    finally { $('auth-submit').disabled = false; }
  });
  $('logout-button').addEventListener('click', async () => {
    try { const result = await App.post('/api/auth/logout'); App.csrf = result.csrf; App.setOperator(false); $('lock-dialog').close(); App.toast('This browser is locked.'); }
    catch (error) { App.toast(error.message, true); }
  });
  App.ready = App.api('/api/auth/status').then(data => { App.csrf = data.csrf; App.setOperator(data.operator); }).catch(() => {});
  App.pollStatus();
})();
