// First-run setup page. No dependencies, no secrets embedded. The token is typed by
// the operator and kept in memory only. All DOM text is set with textContent.
(function () {
  'use strict';
  var token = '';
  var state = null;
  var pollTimer = null;
  var preflightId = null;

  function $(id) { return document.getElementById(id); }
  function show(id, on) { $(id).hidden = !on; }

  function api(method, path, body) {
    var opt = { method: method, headers: { 'Authorization': 'Bearer ' + token }, cache: 'no-store' };
    if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
    return fetch(path, opt).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, status: r.status, json: j }; });
    });
  }

  var FIELDS = [
    ['netbox_pg_container', 'Old NetBox database container name', 'text', true],
    ['netbox_db_password_file', 'Path of the file with the old NetBox database password', 'text', true],
    ['netbox_db', 'Old NetBox database name (default netbox)', 'text'],
    ['netbox_db_user', 'Old NetBox database user (default netbox)', 'text'],
    ['netbox_media_path', 'Old NetBox media folder (path)', 'text'],
    ['netdisco_pg_container', 'Old Netdisco database container name', 'text'],
    ['netdisco_db_password_file', 'Path of the file with the old Netdisco database password', 'text'],
    ['grafana_data_path', 'Old Grafana data folder (path, contains grafana.db)', 'text'],
    ['grafana_provisioning_path', 'Old Grafana provisioning folder (path, copied for review)', 'text'],
    ['alertmanager_config_path', 'Old Alertmanager config file (path, copied for review)', 'text'],
    ['caddyfile_path', 'Old Caddyfile (path, copied for review)', 'text']
  ];

  function buildForm() {
    var box = $('migrate-form');
    FIELDS.forEach(function (f) {
      var l = document.createElement('label');
      l.appendChild(document.createTextNode(f[1] + (f[3] ? ' *' : '')));
      var i = document.createElement('input');
      i.type = 'text'; i.id = 'f-' + f[0]; i.autocomplete = 'off';
      l.appendChild(i); box.appendChild(l);
    });
  }
  function oldStack() {
    var o = {};
    FIELDS.forEach(function (f) { var v = $('f-' + f[0]).value.trim(); if (v) { o[f[0]] = v; } });
    return o;
  }

  function renderState() {
    if (!state) { return; }
    show('s-status', true);
    $('st-state').textContent = state.state;
    $('st-step').textContent = state.step;
    $('st-client').textContent = state.client_name || '';
    $('st-error').textContent = state.error || '';
    var s = state.state, step = state.step;
    var busy = s === 'applying' || (state.job && state.job.state === 'running');
    show('s-client', s === 'unconfigured' && step === 'client' || s === 'failed' || s === 'complete');
    $('rename-box').hidden = s !== 'complete';
    if (s === 'complete' && !$('client-name').value) { $('client-name').value = state.client_name; }
    show('s-admin', s === 'unconfigured' && step === 'admin');
    show('s-mode', s === 'unconfigured' && step === 'mode');
    show('s-migrate', s === 'unconfigured' && (step === 'migrate' || step === 'history'));
    show('s-history', s === 'unconfigured' && step === 'history');
    show('s-done', s === 'complete');
    show('s-log', true);
    ['btn-client', 'btn-admin', 'btn-mode', 'btn-preflight', 'btn-history'].forEach(function (b) { $(b).disabled = !!busy; });
    var pf = state.last_preflight;
    preflightId = pf && pf.passed ? pf.id : null;
    $('btn-run').disabled = !(preflightId && $('confirm-run').checked) || !!busy;
    if (pf) {
      $('preflight-summary').textContent = 'Preflight ' + (pf.passed ? 'passed' : 'FAILED') + ': ' + pf.errors + ' error(s), ' + pf.warnings + ' warning(s)';
      $('preflight-summary').className = pf.passed ? 'ok' : 'err';
    }
  }

  function refresh() {
    return api('GET', '/setup/state').then(function (r) {
      if (r.status === 401) { stopPoll(); show('s-token', true); $('token-msg').textContent = 'Token rejected.'; return; }
      if (r.ok) { state = r.json; show('s-token', false); renderState(); }
    }).catch(function () {
      // The proxy restarts while the stack is recreated; keep retrying.
      $('st-error').textContent = 'Waiting for the service (containers may be restarting)...';
    });
  }

  function loadProgress() {
    return api('GET', '/setup/migrate/status').then(function (r) {
      if (!r.ok) { return; }
      $('preflight-log').textContent = (r.json.log_tail || []).join('\n');
      var lines = (r.json.progress || []).slice(-20).map(function (p) { return p.time + '  ' + p.step + '  ' + p.state + '  ' + (p.detail || ''); });
      if (r.json.job) { lines.unshift('job: ' + r.json.job.kind + ' ' + r.json.job.state + (r.json.job.error ? ' - ' + r.json.job.error : '')); }
      $('progress').textContent = lines.join('\n');
    });
  }
  function loadLog() {
    return api('GET', '/setup/log?lines=200').then(function (r) { if (r.ok) { $('log').textContent = r.json.lines.join('\n'); } });
  }
  function tick() { refresh().then(function () { if (!$('s-migrate').hidden) { loadProgress(); } loadLog(); }); }
  function startPoll() { stopPoll(); tick(); pollTimer = setInterval(tick, 3000); }
  function stopPoll() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

  function post(path, body, msgId, then) {
    $(msgId).textContent = '';
    api('POST', path, body).then(function (r) {
      if (!r.ok) { $(msgId).textContent = (r.json && r.json.error) || ('Error ' + r.status); return; }
      if (then) { then(r.json); }
      tick();
    }).catch(function () { $(msgId).textContent = 'Request failed (service restarting?). It will retry on its own.'; });
  }

  $('btn-token').addEventListener('click', function () {
    token = $('token').value.trim(); $('token').value = '';
    if (!token) { $('token-msg').textContent = 'Enter the token.'; return; }
    $('token-msg').textContent = ''; startPoll();
  });
  $('btn-client').addEventListener('click', function () {
    var b = { client_name: $('client-name').value };
    if (state && state.state === 'complete') { b.confirm_downtime = $('confirm-downtime').checked; }
    post('/setup/client', b, 'client-msg');
  });
  $('btn-admin').addEventListener('click', function () {
    var gen = $('admin-generate').checked;
    var b = { email: $('admin-email').value.trim() };
    if (gen) { b.generate = true; } else { b.password = $('admin-password').value; }
    $('admin-password').value = '';
    $('admin-once').textContent = '';
    post('/setup/admin', b, 'admin-msg', function (j) {
      if (j.generated_password) {
        $('admin-once').textContent = 'Generated password (shown once): ' + j.generated_password;
      }
    });
  });
  $('btn-mode').addEventListener('click', function () {
    var m = document.querySelector('input[name=mode]:checked').value;
    post('/setup/mode', { mode: m }, 'mode-msg');
  });
  $('btn-preflight').addEventListener('click', function () {
    post('/setup/migrate/preflight', { old_stack: oldStack() }, 'migrate-msg');
  });
  $('confirm-run').addEventListener('change', renderState);
  $('btn-run').addEventListener('click', function () {
    post('/setup/migrate/run', { preflight_id: preflightId, confirm: true }, 'migrate-msg');
  });
  document.querySelectorAll('input[name=hist]').forEach(function (r) {
    r.addEventListener('change', function () { show('hist-keep', document.querySelector('input[name=hist]:checked').value === 'keep'); });
  });
  $('hist-method').addEventListener('change', function () { show('hist-url-l', $('hist-method').value === 'snapshot'); });
  $('btn-history').addEventListener('click', function () {
    var m = document.querySelector('input[name=hist]:checked').value;
    var b = { mode: m };
    if (m === 'keep') { b.method = $('hist-method').value; b.old_data_dir = $('hist-dir').value.trim(); if (b.method === 'snapshot') { b.old_url = $('hist-url').value.trim(); } }
    post('/setup/prom-history', b, 'hist-msg');
  });
  $('btn-log').addEventListener('click', loadLog);

  buildForm();
})();
