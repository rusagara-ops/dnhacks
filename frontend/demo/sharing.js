(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const taskNames = {summarization: 'Summaries', 'document-qa': 'Document questions', 'information-extraction': 'Information extraction', 'coding-assistance': 'Coding assistance', 'sentiment-classification': 'Sentiment (legacy)'};
  const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  let token = '', identity = null, epoch = 0, ledgerOffset = 0, grantRetry = null;
  const TOKEN_KEY = 'dnhacksDemoToken';
  const saveToken = value => { try { value ? localStorage.setItem(TOKEN_KEY, value) : localStorage.removeItem(TOKEN_KEY); } catch { /* storage is optional */ } };
  const loadStoredToken = () => { try { return localStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; } };
  const node = (tag, text, cls) => { const value = document.createElement(tag); if (text != null) value.textContent = text; if (cls) value.className = cls; return value; };
  const signed = value => value > 0 ? `+${value}` : String(value);
  const time = minute => `${String(Math.floor(minute / 60)).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`;
  const minutes = value => { const [h, m] = value.split(':').map(Number); return h * 60 + m; };
  function requestId() {
    const bytes = crypto.getRandomValues(new Uint8Array(16)); bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
    const hex = [...bytes].map(b => b.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
  }
  async function api(path, body) {
    const response = await fetch('/api' + path, {method: body === undefined ? 'GET' : 'POST', redirect: 'error', signal: AbortSignal.timeout(15000),
      headers: {...(token ? {Authorization: 'Bearer ' + token} : {}), ...(body === undefined ? {} : {'Content-Type': 'application/json'})},
      body: body === undefined ? undefined : JSON.stringify(body)});
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      const error = new Error(response.status === 404 ? 'This endpoint is unavailable. Update and restart the coordinator backend.' : typeof data.detail === 'string' ? data.detail : `Request rejected (${response.status}). Check the fields and your account permissions.`);
      error.status = response.status; throw error;
    }
    return response.json();
  }
  function clearSecret() { $('new-token').value = ''; $('new-token').type = 'password'; $('reveal-token').textContent = 'Reveal token'; $('one-time-secret').hidden = true; $('secret-status').textContent = ''; }
  function showSecret(value, description) {
    $('new-token').value = value; $('secret-description').textContent = description + ' It cannot be retrieved again. Store it privately before leaving this page.';
    $('one-time-secret').hidden = false; $('one-time-secret').scrollIntoView({block: 'nearest'});
  }
  function requireSavedSecret() { if (!$('one-time-secret').hidden) throw new Error('Save and clear the credential shown above before creating another.'); }
  $('reveal-token').onclick = () => { const show = $('new-token').type === 'password'; $('new-token').type = show ? 'text' : 'password'; $('reveal-token').textContent = show ? 'Hide token' : 'Reveal token'; };
  $('copy-token').onclick = async () => { try { await navigator.clipboard.writeText($('new-token').value); $('secret-status').textContent = 'Copied. Keep it private and clear it here after saving.'; } catch { $('secret-status').textContent = 'Clipboard access is unavailable here. Reveal and copy the token manually.'; } };
  $('clear-token').onclick = clearSecret;
  function disconnect() {
    epoch++; saveToken(''); token = ''; identity = null; grantRetry = null; ledgerOffset = 0; clearSecret();
    $('account-token').value = ''; $('dashboard').hidden = true; $('disconnect').hidden = true; $('connect').disabled = false; $('identity').textContent = 'Not connected'; $('error').textContent = '';
    for (const id of ['providers', 'credentials', 'accounts', 'ledger']) $(id).replaceChildren();
    for (const id of ['wallet-error', 'providers-error', 'credential-error', 'account-error', 'grant-message', 'enroll-message']) $(id).textContent = '';
  }
  $('disconnect').onclick = disconnect;
  async function action(form, message, work) {
    const current = epoch; const controls = [...form.querySelectorAll('button,input,select')];
    if (form.dataset.busy === 'true') return;
    form.dataset.busy = 'true'; controls.forEach(control => control.disabled = true); message.textContent = '';
    try { await work(current); } catch (error) { if (current === epoch) message.textContent = error.message || 'Request could not be confirmed. Refresh before retrying.'; }
    finally { form.dataset.busy = ''; controls.forEach(control => control.disabled = false); }
  }
  $('connection-form').onsubmit = async event => {
    event.preventDefault(); const nextToken = $('account-token').value.trim(); disconnect(); token = nextToken;
    const current = epoch; $('connect').disabled = true;
    try {
      const me = await api('/me'); if (current !== epoch) return;
      if (me.credential_kind === 'worker') throw new Error('Use an account token in this dashboard. Worker credentials are restricted to their installation.');
      identity = me; $('dashboard').hidden = false; $('disconnect').hidden = false;
      $('identity').textContent = `${me.name || 'Demo operator'} · ${me.auth_mode} mode · ${me.role}`;
      $('mode-message').textContent = me.auth_mode === 'demo' ? 'Demo mode: existing jobs remain unmetered and the shared demo access rules still apply. Account isolation and demo-credit accounting require controlled mode.' : me.credential_kind === 'bootstrap' ? 'Setup access only. Create an administrator account, save its token, then reconnect with that account token.' : 'Controlled sharing: your account has its own jobs, credit balance, and worker credentials. Providers can read inputs processed on their machines.';
      const account = me.credential_kind === 'account', admin = me.auth_mode === 'controlled' && me.role === 'admin';
      $('wallet-panel').hidden = !account; $('credentials-panel').hidden = !account;
      $('providers-panel').hidden = !(account || me.auth_mode === 'demo'); $('admin-panel').hidden = !admin;
      $('providers-title').textContent = admin || me.auth_mode === 'demo' ? 'Managed compute machines' : 'Your compute machines';
      $('grant-form').hidden = !(admin && account); $('enroll-form').hidden = !(admin && account);
      $('bootstrap-help').textContent = me.credential_kind === 'bootstrap' ? 'First create an administrator. The setup token cannot submit jobs or operate workers.' : 'Enroll approved team members. Each account token is shown once and should be delivered privately.';
      if (me.credential_kind === 'bootstrap') $('account-role').value = 'admin';
      await Promise.allSettled([account ? loadWallet() : null, account ? loadCredentials() : null, !$('providers-panel').hidden ? loadWorkers() : null, admin ? loadAccounts() : null]);
      if (current === epoch) saveToken(token);
    } catch (error) { if (current === epoch) { token = ''; saveToken(''); $('error').textContent = error.message; } }
    finally { if (current === epoch) $('connect').disabled = false; }
  };
  const storedToken = loadStoredToken();
  if (storedToken) { $('account-token').value = storedToken; $('connection-form').requestSubmit(); }
  async function loadWallet() {
    const current = epoch, offset = ledgerOffset;
    try {
      const data = await api(`/credits?limit=20&offset=${offset}`); if (current !== epoch || offset !== ledgerOffset) return;
      $('available').textContent = data.available; $('reserved').textContent = data.reserved; $('earned').textContent = data.lifetime_earned;
      $('ledger').replaceChildren(); $('wallet-error').textContent = '';
      for (const entry of data.entries) {
        const row = node('tr'); for (const value of [new Date(entry.created_at).toLocaleString(), entry.kind.replaceAll('_', ' '), signed(entry.available_delta), signed(entry.reserved_delta), entry.job_id || '—']) row.append(node('td', value)); $('ledger').append(row);
      }
      if (!data.entries.length) { const row = node('tr'), cell = node('td', 'No credit entries yet. Ask an administrator for demo credits.'); cell.colSpan = 5; row.append(cell); $('ledger').append(row); }
      $('ledger-prev').disabled = offset === 0; $('ledger-next').disabled = offset + data.entries.length >= data.total_entries;
      $('ledger-page').textContent = data.total_entries ? `${offset + 1}–${offset + data.entries.length} of ${data.total_entries}` : '0 entries';
    } catch (error) { if (current === epoch) $('wallet-error').textContent = error.message + ' Displayed balances may be stale.'; }
  }
  $('refresh-wallet').onclick = loadWallet;
  $('ledger-prev').onclick = () => { ledgerOffset = Math.max(0, ledgerOffset - 20); void loadWallet(); };
  $('ledger-next').onclick = () => { ledgerOffset += 20; void loadWallet(); };
  function field(label, input) { const wrapper = node('label', label); wrapper.append(input); return wrapper; }
  function input(type, value) { const valueInput = node('input'); valueInput.type = type; valueInput.value = value; return valueInput; }
  function checkbox(label, checked) { const control = input('checkbox', ''); control.checked = checked; const wrapper = node('label', null, 'check'); wrapper.append(control, node('span', label)); return {control, wrapper}; }
  function providerCard(worker) {
    const card = node('article', null, 'provider-card'), heading = node('div', null, 'heading'); card.dataset.workerId = worker.worker_id;
    heading.append(node('h3', worker.name), node('span', worker.accepting_new_tasks ? 'Accepting work' : 'Not accepting work', 'badge')); card.append(heading);
    const admission = node('p', worker.admission_reasons.length ? worker.admission_reasons.map(reason => reason.toLowerCase().replaceAll('_', ' ')).join(' · ') : 'Ready for compatible assignments.', 'hint'); card.append(admission);
    const reliability = worker.reliability, metrics = node('div', null, 'reliability');
    for (const [label, value] of [['Accepted tasks', reliability.completed_tasks], ['Failed attempts', reliability.failed_attempts], ['Expired attempts', reliability.expired_attempts], ['Observed attempts', reliability.observed_attempts]]) metrics.append(node('span', `${label}: ${value}`));
    card.append(metrics, node('p', `Average worker-reported execution: ${reliability.average_reported_execution_ms == null ? 'not available' : (reliability.average_reported_execution_ms / 1000).toFixed(2) + ' s'}. Recorded outcomes since tracking began; not an independent benchmark, quality score, or security certification.`, 'hint'));
    const policy = worker.policy, form = node('form', null, 'policy-form');
    const sharing = checkbox('Share this machine', policy.sharing_enabled); form.append(sharing.wrapper);
    const taskSet = node('fieldset'), checks = node('div', null, 'task-checks'); taskSet.append(node('legend', 'Allowed workloads'));
    const taskChecks = Object.entries(taskNames).map(([name, label]) => { const item = checkbox(label, policy.allowed_task_types.includes(name)); item.control.value = name; checks.append(item.wrapper); return item.control; }); taskSet.append(checks); form.append(taskSet);
    const caps = node('div', null, 'row'), concurrency = input('number', policy.max_concurrent_tasks), freeRam = input('number', policy.min_ram_available_gb);
    concurrency.min = '1'; concurrency.max = '2'; concurrency.step = '1'; concurrency.required = true; freeRam.min = '0'; freeRam.max = String(worker.ram_gb ?? 100000); freeRam.step = '0.1'; freeRam.required = true;
    caps.append(field('Maximum active tasks', concurrency), field('Minimum free RAM (GiB)', freeRam)); form.append(caps);
    form.append(node('p', 'The worker must support the requested concurrency. This setting is a coordinator admission ceiling, not extra execution capacity.', 'hint'));
    const schedule = node('fieldset'); schedule.append(node('legend', 'Availability windows · UTC'), node('p', 'No windows means any time. Split overnight availability into two windows. 24:00 is the end of a day.', 'hint'));
    const windows = node('div'); const windowRows = [];
    function addWindow(value = {days: [0, 1, 2, 3, 4], start_minute: 540, end_minute: 1020}) {
      const row = node('div', null, 'schedule-row'), selections = node('div', null, 'schedule-days');
      const selectedDays = days.map((name, index) => { const check = checkbox(name, value.days.includes(index)); selections.append(check.wrapper); return check.control; });
      const start = input('time', time(value.start_minute)), end = input('text', time(value.end_minute)); start.required = true; end.required = true; end.pattern = '(?:[01][0-9]|2[0-3]):[0-5][0-9]|24:00'; end.placeholder = '17:00 or 24:00';
      const range = node('div', null, 'row'); range.append(field('Start (UTC)', start), field('End (UTC)', end));
      const remove = node('button', 'Remove window', 'secondary'); remove.type = 'button'; const item = {row, selectedDays, start, end}; windowRows.push(item);
      remove.onclick = () => { row.remove(); windowRows.splice(windowRows.indexOf(item), 1); };
      row.append(selections, range, remove); windows.append(row);
    }
    for (const window of policy.availability) addWindow(window);
    const add = node('button', 'Add availability window', 'secondary'); add.type = 'button'; add.onclick = () => addWindow(); schedule.append(windows, add); form.append(schedule);
    const save = node('button', 'Save sharing settings'); const message = node('p'); message.setAttribute('role', 'status');
    form.append(save, message); form.onsubmit = event => {
      event.preventDefault(); void action(form, message, async current => {
        const availability = windowRows.map(item => ({days: item.selectedDays.flatMap((check, index) => check.checked ? [index] : []), start_minute: minutes(item.start.value), end_minute: minutes(item.end.value)}));
        if (availability.some(window => !window.days.length || !Number.isFinite(window.start_minute) || !Number.isFinite(window.end_minute) || window.start_minute >= window.end_minute || window.end_minute > 1440)) throw new Error('Each window needs at least one day and a start earlier than its end. Split overnight windows at midnight.');
        const allowed_task_types = taskChecks.filter(check => check.checked).map(check => check.value);
        await api(`/provider/workers/${encodeURIComponent(worker.worker_id)}/policy`, {sharing_enabled: sharing.control.checked, allowed_task_types, max_concurrent_tasks: Number(concurrency.value), min_ram_available_gb: Number(freeRam.value), availability});
        if (current !== epoch) return; message.textContent = 'Saved. Existing assignments continue; these settings apply to new work.';
        admission.textContent = 'Settings saved. Refresh machines to check current availability.';
        heading.lastChild.textContent = sharing.control.checked ? 'Sharing enabled · refresh status' : 'Sharing paused';
      });
    };
    card.append(form); return card;
  }
  async function loadWorkers() {
    const current = epoch;
    try { const data = await api('/provider/workers'); if (current !== epoch) return; $('providers').replaceChildren(...data.items.map(providerCard)); if (!data.items.length) $('providers').append(node('p', 'No machines owned by this account yet. Create a worker credential below and start that installation.')); $('providers-error').textContent = ''; }
    catch (error) { if (current === epoch) $('providers-error').textContent = error.message + ' Displayed machine information may be stale.'; }
  }
  $('refresh-workers').onclick = loadWorkers;
  async function loadCredentials() {
    const current = epoch;
    try {
      const credentials = await api('/credentials'); if (current !== epoch) return; $('credentials').replaceChildren();
      for (const credential of credentials) {
        const row = node('div', null, 'credential'), description = node('p', credential.label || credential.kind); description.append(node('small', `${credential.kind} · ${credential.device_id || 'Account access'} · ${credential.revoked_at ? 'Revoked' : 'Active'}`)); row.append(description);
        if (!credential.revoked_at) {
          const revoke = node('button', 'Revoke', 'secondary'); revoke.type = 'button'; revoke.setAttribute('aria-label', 'Revoke ' + (credential.label || credential.kind)); let confirmed = false;
          revoke.onclick = async () => {
            if (!confirmed) { confirmed = true; revoke.textContent = 'Confirm revoke'; revoke.classList.add('pending-revoke'); return; }
            revoke.disabled = true;
            try { await api(`/credentials/${encodeURIComponent(credential.id)}/revoke`, {}); if (current !== epoch) return; if (credential.kind === 'account') { disconnect(); $('identity').textContent = 'Account credential revoked. Reconnect with another active account credential.'; } else await loadCredentials(); }
            catch (error) { if (current === epoch) { $('credential-error').textContent = error.message; revoke.disabled = false; } }
          }; row.append(revoke);
        }
        $('credentials').append(row);
      }
      if (!credentials.length) $('credentials').append(node('p', 'No credentials listed.'));
    } catch (error) { if (current === epoch) $('credential-error').textContent = error.message; }
  }
  $('credential-form').onsubmit = event => {
    event.preventDefault(); void action(event.currentTarget, $('credential-error'), async current => {
      requireSavedSecret(); const result = await api('/credentials', {device_id: $('device-id').value.trim(), label: $('credential-label').value.trim()});
      if (current !== epoch) return; showSecret(result.token, 'Use this worker credential as API_TOKEN in that installation’s terminal.'); await loadCredentials();
    });
  };
  async function loadAccounts() {
    const current = epoch;
    try {
      const accounts = await api('/accounts'); if (current !== epoch) return; $('accounts').replaceChildren();
      for (const id of ['grant-account', 'enroll-account']) { const select = $(id), previous = select.value; select.replaceChildren(); for (const account of accounts) { const option = node('option', account.name); option.value = account.id; option.disabled = !account.enabled; select.append(option); } if (accounts.some(account => account.id === previous)) select.value = previous; }
      for (const account of accounts) {
        const wrapper = node('div'), row = node('div', null, 'account'), description = node('p', account.name);
        description.append(node('small', `${account.role} · ${account.id} · ${account.enabled ? 'Enabled' : 'Disabled'}`)); row.append(description);
        const actions = node('div', null, 'row'), credentials = node('div'), message = node('p'); message.setAttribute('role', 'status');
        const view = node('button', 'View credentials', 'secondary'); view.type = 'button'; view.setAttribute('aria-label', `View credentials for ${account.name}`);
        async function accountCredentials() {
          const values = await api(`/accounts/${encodeURIComponent(account.id)}/credentials`); if (current !== epoch) return;
          credentials.replaceChildren();
          for (const value of values) {
            const item = node('div', null, 'credential'), text = node('p', `${value.label || value.kind} · ${value.revoked_at ? 'Revoked' : 'Active'}`); text.append(node('small', `${value.kind} · created ${new Date(value.created_at).toLocaleString()}`)); item.append(text);
            if (!value.revoked_at) {
              const revoke = node('button', 'Revoke', 'secondary'); revoke.type = 'button'; revoke.setAttribute('aria-label', `Revoke ${account.name} credential ${value.id}`); let confirmed = false;
              revoke.onclick = async () => { if (!confirmed) { confirmed = true; revoke.textContent = 'Confirm revoke'; return; } revoke.disabled = true;
                try { await api(`/credentials/${encodeURIComponent(value.id)}/revoke`, {}); if (current !== epoch) return; if (value.kind === 'account' && value.account_id === identity.account_id) { disconnect(); $('identity').textContent = 'Account credential revoked. Reconnect with an active account credential.'; } else await accountCredentials(); }
                catch (error) { if (current === epoch) { message.textContent = error.message; revoke.disabled = false; } }
              }; item.append(revoke);
            }
            credentials.append(item);
          }
        }
        view.onclick = async () => { view.disabled = true; try { await accountCredentials(); } catch (error) { if (current === epoch) message.textContent = error.message; } finally { view.disabled = false; } };
        const recover = node('button', 'Issue replacement token', 'secondary'); recover.type = 'button'; recover.setAttribute('aria-label', `Issue replacement token for ${account.name}`); recover.disabled = !account.enabled;
        recover.onclick = async () => { recover.disabled = true; message.textContent = '';
          try { requireSavedSecret(); const result = await api(`/accounts/${encodeURIComponent(account.id)}/credentials`, {label: 'Administrator-issued replacement'}); if (current !== epoch) return; showSecret(result.token, `Replacement account access for ${account.name}. Existing tokens remain active until explicitly revoked; this preserves the same jobs, workers, and balance.`); await accountCredentials(); }
          catch (error) { if (current === epoch) message.textContent = error.message; } finally { recover.disabled = false; }
        };
        actions.append(view, recover); row.append(actions); wrapper.append(row, message, credentials); $('accounts').append(wrapper);
      }
    } catch (error) { if (current === epoch) $('account-error').textContent = error.message; }
  }
  $('account-form').onsubmit = event => {
    event.preventDefault(); void action(event.currentTarget, $('account-error'), async current => {
      requireSavedSecret(); const result = await api('/accounts', {name: $('account-name').value.trim(), role: $('account-role').value});
      if (current !== epoch) return; showSecret(result.token, `Account token for ${result.account.name}. Use it in the dashboard; do not use it as a worker credential.`); await loadAccounts();
    });
  };
  $('grant-form').onsubmit = event => {
    event.preventDefault(); void action(event.currentTarget, $('grant-message'), async current => {
      const payload = {account_id: $('grant-account').value, amount: Number($('grant-amount').value)};
      const signature = JSON.stringify(payload);
      if (!grantRetry || grantRetry.signature !== signature) grantRetry = {signature, request_id: requestId()};
      await api('/credits/grants', {...payload, request_id: grantRetry.request_id}); if (current !== epoch) return;
      grantRetry = null; $('grant-message').textContent = 'Demo credits granted. These credits have no cash value.'; if (payload.account_id === identity.account_id) await loadWallet();
    });
  };
  $('enroll-form').onsubmit = event => {
    event.preventDefault(); void action(event.currentTarget, $('enroll-message'), async current => {
      await api(`/accounts/${encodeURIComponent($('enroll-account').value)}/workers/${encodeURIComponent($('enroll-worker').value.trim())}/enroll`, {});
      if (current !== epoch) return; $('enroll-message').textContent = 'Worker assigned. Its owner can review sharing settings and issue an installation credential.'; await loadWorkers();
    });
  };
  $('coordinator-origin').textContent = location.origin;
  $('transport-message').hidden = location.protocol === 'https:' || ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
  window.addEventListener('pagehide', disconnect);
})();
