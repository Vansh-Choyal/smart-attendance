(() => {
  'use strict';
  const A = window.Attend, $ = A.$;
  let stats = null, events = [], loading = false, date = $('attendance-date').value, signature = '', requestVersion = 0;
  function renderStats(data) {
    stats = data; $('total-count').textContent = data.total.toLocaleString('en-IN');
    $('count-period').textContent = date === data.date && date === A.today() ? 'Confirmed entries today' : 'Confirmed entries on '+A.formatDate(date);
    $('last-checkin').textContent = A.formatTime(data.last_check_in);
    $('last-checkin-support').textContent = data.last_check_in ? 'Most recent confirmed entry' : 'No entry recorded yet';
    $('activity-count').textContent = data.total+' event'+(data.total === 1 ? '' : 's');
    $('reset-today').hidden = date !== A.today();
  }
  function renderEvents() {
    $('events-body').replaceChildren();
    for (const event of events) {
      const row = document.createElement('tr');
      for (const text of ['#'+String(event.id).padStart(4,'0'), A.formatTime(event.timestamp, true), event.camera_source]) {
        const cell = document.createElement('td'); cell.textContent = text;
        if (row.children.length < 2) cell.className = 'numeric';
        row.append(cell);
      }
      const cell = document.createElement('td'), badge = document.createElement('span'), icon = document.createElement('i');
      badge.className = 'event-badge'; icon.dataset.lucide = 'check'; badge.append(icon, document.createTextNode('Recorded')); cell.append(badge); row.append(cell); $('events-body').append(row);
    }
    A.icons($('events-body'));
    $('activity-empty').hidden = events.length > 0;
    $('load-more-row').hidden = !stats || events.length >= stats.total;
    $('activity-footer-label').textContent = events.length ? `Showing ${events.length} of ${stats?.total ?? events.length} entries.` : 'All records are stored on this computer.';
  }
  function renderWeekly(days) {
    const highest = Math.max(1, ...days.map(day => day.total)), max = highest > 4 ? Math.ceil(highest/4)*4 : 4;
    $('weekly-total').textContent = days.reduce((sum,day) => sum+day.total,0).toLocaleString('en-IN');
    $('chart-max').textContent = max; $('chart-mid').textContent = max/2;
    $('weekly-range').textContent = A.formatDate(days[0].date)+' – '+A.formatDate(days[6].date);
    $('weekly-chart').replaceChildren();
    const summary = [];
    days.forEach((day,index) => {
      const column = document.createElement('div'); column.className = 'chart-column'+(day.date === A.today() ? ' is-today' : '');
      column.title = A.formatDate(day.date)+': '+day.total+' entries';
      const track = document.createElement('div'); track.className = 'bar-track';
      const bar = document.createElement('span'); bar.className = 'chart-bar'+(index === 6 ? ' latest' : ''); bar.style.height = (day.total/max*100)+'%'; track.append(bar);
      const label = document.createElement('span'); label.textContent = A.formatDate(day.date,{weekday:'short',day:undefined,month:undefined});
      column.append(track,label); $('weekly-chart').append(column); summary.push(A.formatDate(day.date)+': '+day.total);
    });
    $('weekly-chart').setAttribute('aria-label', 'Daily attendance. '+summary.join('; '));
    $('chart-note').textContent = days.some(day => day.total) ? 'Based on saved attendance events.' : 'No attendance recorded in this period.';
  }
  async function refresh(force = false) {
    if (loading && !force) return;
    loading = true;
    const version = ++requestVersion, selected = date;
    try {
      const [current, activity, weekly] = await Promise.all([
        A.api('/api/attendance/stats?date='+selected),
        A.api('/api/attendance/events?limit=50&date='+selected),
        A.api('/api/attendance/weekly?date='+selected)
      ]);
      if (version !== requestVersion) return;
      const changed = JSON.stringify([selected,current,activity,weekly]);
      if (signature !== changed) {
        signature = changed; renderStats(current);
        // Keep previously loaded rows when only new events have arrived.
        const fresh = activity.events, seen = new Set(fresh.map(event => event.id));
        events = force ? fresh : [...fresh,...events.filter(event => !seen.has(event.id) && event.id < (fresh.at(-1)?.id ?? Infinity))].slice(0,current.total);
        renderEvents(); renderWeekly(weekly.days);
      }
      $('updates-label').textContent = 'Live updates'; $('updates-dot').classList.add('live');
    } catch (error) { $('updates-label').textContent = 'Updates paused'; $('updates-dot').classList.remove('live'); }
    finally { if (version === requestVersion) loading = false; }
  }
  function changeDate() {
    if (!$('attendance-date').value) return;
    date = $('attendance-date').value; events = []; signature = ''; refresh(true);
  }
  $('attendance-date').addEventListener('change', changeDate);
  $('today-button').addEventListener('click', () => { $('attendance-date').value = A.today(); changeDate(); });
  $('load-more').addEventListener('click', async () => {
    const selected = date; $('load-more').disabled = true;
    try {
      const result = await A.api('/api/attendance/events?limit=50&date='+selected+'&before='+events.at(-1).id);
      if (selected !== date) return;
      const known = new Set(events.map(event => event.id)); events.push(...result.events.filter(event => !known.has(event.id))); renderEvents();
    } catch (error) { A.toast(error.message,true); }
    finally { $('load-more').disabled = false; }
  });
  $('reset-today').addEventListener('click', async () => {
    if (!await A.requireOperator()) return;
    try {
      const current = await A.api('/api/attendance/stats');
      $('reset-date').textContent = A.formatDate(current.date,{year:'numeric'}); $('reset-count').textContent = current.total+' events';
      $('reset-dialog').dataset.date = current.date; $('reset-dialog').showModal();
    } catch (error) { A.toast(error.message,true); }
  });
  $('reset-form').addEventListener('submit', async event => {
    event.preventDefault(); $('confirm-reset').disabled = true;
    try {
      const result = await A.post('/api/attendance/reset', {confirm_date:$('reset-dialog').dataset.date});
      $('reset-dialog').close(); events = []; signature = ''; await refresh(true); A.toast(`Today's attendance reset. ${result.deleted} events removed.`);
    } catch (error) { A.toast(error.message,true); }
    finally { $('confirm-reset').disabled = false; }
  });
  window.addEventListener('attend:status', event => {
    const state = event.detail, camera = state.camera;
    $('camera-status-value').textContent = camera.connected ? 'Connected' : 'Disconnected';
    $('camera-status-value').classList.toggle('good',camera.connected);
    $('camera-source-label').textContent = camera.source?.label || 'No input source selected';
    const face = state.faces_in_zone > 0;
    $('detection-status-value').textContent = !camera.connected ? 'Unavailable' : state.model.phase !== 'ready' ? 'Unavailable' : face ? (state.faces_in_zone > 1 ? 'Multiple faces' : 'Face detected') : 'No face';
    $('detection-status-value').classList.toggle('good',face && state.faces_in_zone === 1);
    $('detection-status-support').textContent = state.model.error ? 'Check the model in Setup' : !camera.connected ? 'Waiting for camera connection' : state.message;
  });
  window.addEventListener('attend:offline', () => {
    $('camera-status-value').textContent = 'Unavailable'; $('camera-status-value').classList.remove('good');
    $('camera-source-label').textContent = 'Local server unreachable'; $('detection-status-value').textContent = 'Unavailable'; $('detection-status-value').classList.remove('good');
    $('detection-status-support').textContent = 'Status cannot be verified';
  });
  refresh(true);
  setInterval(() => { if (!document.hidden) refresh(); }, 2000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
})();
