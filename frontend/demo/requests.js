(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const taskNames = {summarization:'Summaries','document-qa':'Document questions','information-extraction':'Information extraction','coding-assistance':'Coding assistance'};
  let token = '', identity = null, providers = [];
  const node = (tag, text, cls) => { const value = document.createElement(tag); if (text != null) value.textContent = text; if (cls) value.className = cls; return value; };
  async function api(path, body) {
    const response = await fetch('/api' + path, {method: body === undefined ? 'GET' : 'POST', redirect:'error', signal:AbortSignal.timeout(15000), headers:{Authorization:'Bearer '+token, ...(body === undefined ? {} : {'Content-Type':'application/json'})}, body:body === undefined ? undefined : JSON.stringify(body)});
    if (!response.ok) { const data = await response.json().catch(() => ({})); throw Error(typeof data.detail === 'string' ? data.detail : `Request rejected (${response.status}).`); }
    return response.json();
  }
  function disconnect() { token=''; identity=null; providers=[]; $('dashboard').hidden=true; $('disconnect').hidden=true; $('connect').disabled=false; $('account-token').value=''; $('identity').textContent='Not connected'; $('error').textContent=''; }
  $('disconnect').onclick = disconnect;
  function renderProviderOptions() {
    const select = $('provider'), previous = select.value; select.replaceChildren(node('option','Choose a provider')); select.firstChild.value='';
    for (const item of providers) { const option=node('option', `${item.provider_name} · ${item.worker_name}${item.accepting_new_tasks ? '' : ' · '+item.admission_reasons.join(', ').toLowerCase()}`); option.value=item.worker_id; option.dataset.provider=item.provider_account_id; option.disabled=!item.task_types.length; select.append(option); }
    select.value = previous;
    renderModelOptions();
  }
  function selectedProvider() { return providers.find(item => item.worker_id === $('provider').value); }
  function renderModelOptions() {
    const select=$('model'), previous=select.value, provider=selectedProvider(), task=$('task').value; select.replaceChildren(node('option','Provider chooses compatible model')); select.firstChild.value='';
    for (const model of provider?.models || []) if ((model.supported_tasks || []).includes(task)) { const option=node('option', model.model_id); option.value=model.model_id; select.append(option); }
    select.value=previous;
  }
  function providerCard(item) {
    const card=node('article',null,'provider-card'), heading=node('div',null,'heading'); heading.append(node('h3',`${item.provider_name} · ${item.worker_name}`),node('span',item.accepting_new_tasks?'Ready for requests':'Currently limited','badge')); card.append(heading);
    card.append(node('p',item.accepting_new_tasks?'The provider can review a request now.':'The provider can still review a request, but current limits may delay execution.','hint'));
    card.append(node('p',`Tasks: ${(item.task_types||[]).map(t=>taskNames[t]||t).join(', ')||'No advertised tasks'}`));
    card.append(node('p',`Models: ${(item.models||[]).map(m=>m.model_id).join(', ')||'Not reported'} · Active tasks: ${item.active_tasks}/${item.max_concurrent_tasks}`));
    return card;
  }
  async function loadProviders() { try { providers=await api('/work-requests/providers'); $('providers').replaceChildren(...providers.map(providerCard)); if (!providers.length) $('providers').append(node('p','No other approved providers are currently visible.')); renderProviderOptions(); $('providers-error').textContent=''; } catch(error) { $('providers-error').textContent=error.message; } }
  const readable = status => ({PENDING:'Waiting for provider approval',APPROVED:'Approved — submit the matching job',DECLINED:'Declined by provider',USED:'Used by a submitted job',EXPIRED:'Expired'}[status] || status);
  function renderRequests(items) {
    const target=$('requests'); target.replaceChildren(); if (!items.length) { target.append(node('p','No work requests yet.')); return; }
    for (const item of items) { const row=node('article',null,'provider-card'), heading=node('div',null,'heading'); heading.append(node('h3',`${item.requester_name} → ${item.provider_name}`),node('span',readable(item.status),'badge')); row.append(heading,node('p',`${taskNames[item.task_type]||item.task_type} · ${item.model_id||'provider chooses model'} · ${item.worker_name}`),node('small',new Date(item.created_at).toLocaleString()));
      if (item.status==='PENDING' && identity?.account_id===item.provider_account_id) { const actions=node('div','', 'row'); const approve=node('button','Approve'); const decline=node('button','Decline','secondary'); approve.onclick=async()=>{approve.disabled=decline.disabled=true; try { await api(`/work-requests/${item.id}/approve`,{}); await loadRequests(); } catch(error) { $('requests-error').textContent=error.message; approve.disabled=decline.disabled=false; }}; decline.onclick=async()=>{approve.disabled=decline.disabled=true; try { await api(`/work-requests/${item.id}/decline`,{}); await loadRequests(); } catch(error) { $('requests-error').textContent=error.message; approve.disabled=decline.disabled=false; }}; actions.append(approve,decline); row.append(actions); }
      target.append(row);
    }
  }
  async function loadRequests() { try { renderRequests(await api('/work-requests')); $('requests-error').textContent=''; } catch(error) { $('requests-error').textContent=error.message; } }
  $('provider').onchange=renderModelOptions; $('task').onchange=renderModelOptions; $('refresh-providers').onclick=loadProviders; $('refresh-requests').onclick=loadRequests;
  $('request-form').onsubmit=async event=>{event.preventDefault(); const provider=selectedProvider(), option=$('provider').selectedOptions[0]; if(!provider) return; const button=event.currentTarget.querySelector('button'); button.disabled=true; $('request-message').textContent=''; try { await api('/work-requests',{provider_account_id:option.dataset.provider,worker_id:provider.worker_id,task_type:$('task').value,model_id:$('model').value||null}); $('request-message').textContent='Request sent. The provider can approve it from this page.'; await loadRequests(); } catch(error) { $('request-message').textContent=error.message; } finally { button.disabled=false; }};
  $('connection-form').onsubmit=async event=>{event.preventDefault(); const next=$('account-token').value.trim(); disconnect(); token=next; $('connect').disabled=true; try { identity=await api('/me'); if(identity.credential_kind!=='account'&&identity.credential_kind!=='demo') throw Error('Use a member account token here.'); $('dashboard').hidden=false; $('disconnect').hidden=false; $('identity').textContent=`${identity.name} · ${identity.role}`; await Promise.all([loadProviders(),loadRequests()]); } catch(error) { token=''; $('error').textContent=error.message; } finally {$('connect').disabled=false;} };
})();
