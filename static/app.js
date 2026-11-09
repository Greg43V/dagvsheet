const $ = id => document.getElementById(id);
async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'The request failed.');
  return data;
}
function message(error) { $('message').textContent = error.message; }
async function loadRows() {
  $('refresh').disabled = true;
  try {
    const data = await api('/api/sheet');
    $('title').textContent = data.title;
    $('tab').textContent = data.tab;
    $('limit').textContent = data.limit + ' · Read-only';
    $('rows').replaceChildren();
    data.rows.forEach((row, index) => {
      const tr = document.createElement('tr');
      row.forEach(value => {
        const cell = document.createElement(index === 0 ? 'th' : 'td');
        cell.textContent = value;
        tr.appendChild(cell);
      });
      $('rows').appendChild(tr);
    });
    $('empty').hidden = data.rows.length > 0;
    $('data').hidden = false;
    $('message').textContent = 'Your selected tab is connected. Review the rows below.';
  } catch (error) { message(error); }
  finally { $('refresh').disabled = false; }
}
async function start() {
  try {
    const status = await api('/api/status');
    $('status').textContent = status.connected ? 'Google authorized' : 'Not connected';
    $('connect').hidden = status.connected;
    $('refresh').hidden = !status.connected;
    $('disconnect').hidden = !status.connected;
    if (status.error) $('message').textContent = status.error;
    if (status.connected) await loadRows();
  } catch (error) { message(error); }
}
$('refresh').addEventListener('click', loadRows);
$('disconnect').addEventListener('click', async () => {
  try { await api('/disconnect', { method: 'POST' }); window.location.replace('/'); }
  catch (error) { message(error); }
});
start();
