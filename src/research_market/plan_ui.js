'use strict';
const $ = id => document.getElementById(id);
const csrf = document.querySelector('meta[name="multivac-csrf"]').content;
let snapshot = null, projects = [], current = null, taskShown = null, activeTimer = null, evidenceShown = null;
function message(text) { $('message').textContent = text || ''; $('message').hidden = !text; }
async function api(path, body) {
  const response = await fetch(path, {method: body === undefined ? 'GET' : 'POST', cache:'no-store',
    headers:{'X-Multivac-CSRF':csrf, ...(body === undefined ? {} : {'Content-Type':'application/json'})},
    ...(body === undefined ? {} : {body:JSON.stringify(body)})});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'The request could not finish.');
  return result;
}
function button(id, action) { $(id).addEventListener('click', async () => {
  $(id).disabled = true; message('');
  try { await action(); } catch(error) { message(error.message); }
  finally { $(id).disabled = false; await refresh().catch(error => message(error.message)); }
}); }
function options(id, entries, title) {
  const select = $(id), previous = select.value;
  select.replaceChildren(new Option(title, ''));
  for (const [value,label] of entries) select.add(new Option(label,value));
  if (entries.some(([value]) => value === previous)) select.value = previous;
}
function controls() {
  const running = snapshot?.running, state = current?.state;
  $('reserve').disabled = running || !$('project').value || !$('model').value ||
    (current && !['accepted','rejected','cancelled','expired','failed'].includes(state));
  $('run').disabled = running || state !== 'ready' || !$('model').value || !$('confirmed').checked;
  $('cancel').disabled = !current || ['accepted','rejected','cancelled','expired','failed'].includes(state);
  $('collect').disabled = running || !current;
  $('chatgpt-disconnect').disabled = running;
  $('chatgpt-connect').disabled = running;
  $('confirmation').hidden = state !== 'ready';
  $('web-search').disabled = running;
  $('model').disabled = running;
}
async function refresh() {
  snapshot = await api('/api/state');
  const account = snapshot.account, platform = snapshot.platform;
  $('platform-origin').textContent = snapshot.origin;
  $('account-status').textContent = account.connected ?
    `${account.email || account.account} · ${account.plan_use_authorized ? 'Plan use authorized' : 'Signed in; plan use disabled'}` : 'Not connected. No ChatGPT usage is authorized.';
  $('chatgpt-connect').textContent = account.connected ? 'Review ChatGPT permissions' : 'Continue with ChatGPT';
  $('chatgpt-disconnect').hidden = !account.connected;
  $('platform-status').textContent = platform.state === 'approved' ? 'Connected · invited pilot access' :
    platform.code ? 'Give this pairing code to the pilot owner, then check approval.' : 'Connect this client, then check your invitation approval.';
  $('pairing-code').textContent = platform.code || ''; $('pairing-code').hidden = !platform.code;
  if (snapshot.contribution.id) current = {...current, ...snapshot.contribution};
  if (current) {
    $('work-title').textContent = current.project_id;
    $('work-state').textContent = snapshot.running ? (snapshot.job_kind === 'collect' ? 'Recovering saved result' : 'Contribution in progress') : (snapshot.outcome?.state || current.state);
    $('work-id').textContent = `Contribution ${current.id}`;
  }
  if (snapshot.error || snapshot.authorization_error) message(snapshot.error || snapshot.authorization_error);
  const evidenceKey = current?.id + ':' + (snapshot.outcome?.state || snapshot.error || '');
  if (!snapshot.running && (snapshot.outcome || snapshot.error) && evidenceKey !== evidenceShown) {
    await showEvidence(); evidenceShown = evidenceKey;
  }
  controls();
  clearTimeout(activeTimer);
  if (snapshot.running || ['claiming','delivering'].includes(current?.state)) {
    activeTimer = setTimeout(async () => {
      try {
        await readWork(false);
        await refresh();
      } catch(error) { message(error.message); }
    }, 2500);
  }
}
async function readWork(force) {
  if (!current) return;
  current = await api('/api/work', {id:current.id});
  if (force || (current.state === 'ready' && taskShown !== current.id)) {
    current = await api('/api/task', {});
    $('task').textContent = JSON.stringify(current.task, null, 2);
    $('task-details').hidden = !current.task;
    $('task-details').open = current.state === 'ready';
    if (taskShown !== current.id) $('confirmed').checked = false;
    taskShown = current.id;
  }
}
async function showEvidence() {
  const data = await api('/api/evidence');
  $('evidence').hidden = !data.result && !data.attempt;
  $('report').textContent = data.result?.artifact?.report || 'No completed report is saved. The attempt record preserves the interruption.';
  $('receipt-status').textContent = data.receipt ?
    `${data.receipt.accepted === true ? 'Accepted by the project.' : 'Project disposition received.'} ${data.receipt.accomplishment || ''}${data.receipt.review_required ? ' Further interpretation is required.' : ''}` : 'No project receipt yet. A saved report can be delivered again without repeating inference.';
  $('receipt').textContent = JSON.stringify({attempt:data.attempt, usage:data.result?.usage, receipt:data.receipt ?? null}, null, 2);
}
button('platform-connect', () => api('/api/platform/connect', {}));
button('platform-check', () => api('/api/platform/check', {}));
button('chatgpt-connect', async () => {
  const result = await api('/api/chatgpt/connect', {enable_plan:snapshot?.account?.connected === true});
  window.location.assign(result.url);
});
button('chatgpt-disconnect', async () => {
  const result = await api('/api/chatgpt/disconnect', {});
  message(result.remote_revocation_confirmed ? 'Disconnected. OpenAI confirmed revocation.' : result.note);
});
button('load-choices', async () => {
  const [directory,catalog] = await Promise.all([api('/api/projects'),api('/api/models')]);
  const identity = snapshot.platform.identity, permitted = identity?.projects || [];
  projects = directory.projects.filter(p => p.status === 'active' && p.kinds.includes('agent') &&
    (identity?.role === 'admin' || permitted.includes(p.id)));
  options('project', projects.map(p => [p.id,p.title]), 'Choose a research project');
  options('model', catalog.models.map(m => [m.slug,m.display_name]), 'Choose a model');
  if (!projects.length) message('No approved agent projects are currently available. Check your invitation and project scopes.');
});
button('reserve', async () => {
  current = await api('/api/reserve', {project:$('project').value, seconds:Number($('seconds').value)});
  taskShown = null; evidenceShown = null; $('confirmed').checked = false; $('evidence').hidden = true;
  await readWork(false);
});
button('run', async () => {
  await api('/api/run', {id:current.id, model:$('model').value, confirmed:$('confirmed').checked, web_search:$('web-search').checked});
});
button('cancel', () => api('/api/cancel', {}));
button('collect', async () => { await api('/api/collect', {id:current.id}); });
button('history-load', async () => {
  const result = await api('/api/history'); $('history').replaceChildren();
  for (const item of result.contributions.slice(0,20)) {
    const b = document.createElement('button'); b.className = 'secondary';
    b.textContent = `${item.project_id} · ${item.state} · ${item.id.slice(0,8)}`;
    b.onclick = async () => { try { current = item; await readWork(true); await refresh(); await showEvidence(); } catch(error) { message(error.message); } };
    $('history').append(b);
  }
  if (!result.contributions.length) $('history').textContent = 'No contributions yet.';
});
$('project').addEventListener('change', () => {
  $('project-description').textContent = projects.find(p => p.id === $('project').value)?.description || '';
  controls();
});
for (const id of ['model','confirmed']) $(id).addEventListener('change', controls);
refresh().catch(error => message(error.message));
