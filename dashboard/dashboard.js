const $ = id => document.getElementById(id);
const gbp = new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP', maximumFractionDigits: 2 });
const integer = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 2 });
let orders = [], loaded = false, connected = false, visible = 75, fetchedAt = null;
let activeView = 'buying', profitRequest = 0;
let ordersRefreshing = false, copyingOrders = false;
const controls = ['match', 'section', 'allocation', 'search', 'clear', 'sort'];
const money = value => value == null ? '—' : gbp.format(value);
const matchKey = order => JSON.stringify([order.home, order.away]);
const matchLabel = order => `${order.home || 'Unknown home'} v ${order.away || 'Unknown away'}`;
function notice(text) { $('notice').textContent = text; $('notice').hidden = !text; }
async function api(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) { const error = new Error(data.error || 'The request failed.'); error.code = data.code; throw error; }
  return data;
}
function connection(value) {
  connected = value;
  $('signin').hidden = value;
  $('disconnect').hidden = !value;
  $('connection-label').textContent = value ? 'Google authorized' : 'Sign in to connect';
  document.querySelector('.sidebarfoot').classList.toggle('connected', value);
  $('refresh').disabled = !value;
  controls.forEach(id => $(id).disabled = !value || !loaded);
  if (!value) {
    clearProfit();
    $('copy-dialog').close();
    $('copy-text').value = '';
    $('copy-status').textContent = '';
  }
  updateCopyButton();
}
function options(id, pairs, first) {
  const selected = $(id).value;
  const nodes = [new Option(first, ''), ...pairs.map(([value, label]) => new Option(label, value))];
  $(id).replaceChildren(...nodes);
  $(id).value = pairs.some(([value]) => value === selected) ? selected : '';
}
function rebuildMatches() {
  const matches = new Map(orders.map(order => [matchKey(order), matchLabel(order)]));
  options('match', [...matches].sort((a, b) => a[1].localeCompare(b[1])), 'All matches');
}
function rebuildSections() {
  const matches = orders.filter(order => (!$('match').value || matchKey(order) === $('match').value) && ($('allocation').value === 'all' || order.status === $('allocation').value));
  const sections = [...new Set(matches.map(order => order.section))].sort((a, b) => a.localeCompare(b));
  options('section', sections.map(section => [section || '__blank__', section || 'Unspecified section']), 'All sections');
}
function selectedOrders() {
  const search = $('search').value.trim().toLowerCase();
  const section = $('section').value === '__blank__' ? '' : $('section').value;
  const selected = orders.filter(order =>
    (!$('match').value || matchKey(order) === $('match').value) &&
    (!$('section').value || order.section === section) &&
    ($('allocation').value === 'all' || order.status === $('allocation').value) &&
    (!search || order.orderNumber.toLowerCase().includes(search) || order.orderId.toLowerCase().includes(search)));
  const field = $('sort').value;
  if (field !== 'source') selected.sort((a, b) => (b[field] ?? -Infinity) - (a[field] ?? -Infinity) || a.sourceRow - b.sourceRow);
  return selected;
}
function unallocatedForCopy() {
  return selectedOrders().filter(order => order.status === 'unallocated');
}
function updateCopyButton() {
  const count = connected && loaded && $('match').value ? unallocatedForCopy().length : 0;
  $('copy-unallocated').disabled = !count || ordersRefreshing || copyingOrders;
  $('copy-unallocated').textContent = count ? `Copy unallocated (${integer.format(count)})` : 'Copy unallocated';
  $('copy-hint').textContent = !connected || !loaded ? 'Load your orders and choose a match to copy.'
    : ordersRefreshing ? 'Refreshing orders…'
    : !$('match').value ? 'Choose a match to copy its unallocated orders.'
    : count ? 'Section · Qty · Unit sale price. Copies all matching rows.'
    : 'No unallocated orders match these filters.';
}
async function copyUnallocated() {
  if (!connected || !loaded || !$('match').value || ordersRefreshing || copyingOrders) return;
  const selected = unallocatedForCopy();
  if (!selected.length) return;
  const text = selected.map(order => [
    (order.section || 'Unspecified').replace(/\s+/g, ' ').trim(),
    order.quantity == null ? '—' : integer.format(order.quantity),
    money(order.unitPrice)
  ].join(' | ')).join('\n');
  copyingOrders = true;
  updateCopyButton();
  $('copy-status').textContent = '';
  try {
    await navigator.clipboard.writeText(text);
    if (connected && loaded) $('copy-status').textContent = `Copied ${integer.format(selected.length)} unallocated order${selected.length === 1 ? '' : 's'}.`;
  } catch (_) {
    if (!connected || !loaded) return;
    $('copy-text').value = text;
    $('copy-dialog').showModal();
    $('copy-text').focus();
    $('copy-text').select();
  } finally {
    copyingOrders = false;
    updateCopyButton();
  }
}
function element(tag, text, className) { const node = document.createElement(tag); if (text != null) node.textContent = text; if (className) node.className = className; return node; }
function sourceLink(order, label, className) { const link = element('a', label, className); link.href = order.sourceUrl; link.target = '_blank'; link.rel = 'noopener noreferrer'; return link; }
function render() {
  const selected = selectedOrders();
  const validQuantity = selected.filter(order => order.quantity != null && order.quantity > 0);
  const quantity = validQuantity.reduce((sum, order) => sum + order.quantity, 0);
  const sales = selected.reduce((sum, order) => sum + (order.totalSales ?? 0), 0);
  const complete = selected.filter(order => order.quantity != null && order.quantity > 0 && order.totalSales != null);
  const averageQuantity = complete.reduce((sum, order) => sum + order.quantity, 0);
  const averageSales = complete.reduce((sum, order) => sum + order.totalSales, 0);
  $('metric-orders').textContent = loaded ? integer.format(selected.length) : '—';
  $('metric-tickets').textContent = loaded ? integer.format(quantity) : '—';
  $('metric-sales').textContent = loaded ? money(sales) : '—';
  $('metric-average').textContent = loaded && averageQuantity ? money(averageSales / averageQuantity) : '—';
  const missing = selected.length - validQuantity.length;
  $('ticket-caption').textContent = missing ? `${missing} order${missing === 1 ? '' : 's'} with quantity to review` : 'For the selected filters';
  $('rowcount').textContent = integer.format(selected.length);
  const label = $('match').value ? $('match').selectedOptions[0].textContent : 'All matches';
  const status = $('allocation').selectedOptions[0].textContent;
  $('selection').textContent = loaded ? `${label} · ${status}` : 'Connect your sheet to view orders.';
  $('orderrows').replaceChildren();
  selected.slice(0, visible).forEach(order => {
    const tr = element('tr', null, `order-row ${order.status}`);
    const identifier = element('td');
    identifier.append(sourceLink(order, order.orderNumber || order.orderId || `Row ${order.sourceRow}`, 'orderlink'));
    if (order.orderId && order.orderId !== order.orderNumber) identifier.append(element('small', order.orderId, 'orderid'));
    tr.append(identifier);
    const match = element('td');
    const teams = element('div', null, 'matchteams');
    teams.append(element('b', order.home || '—'), element('span', 'v'), element('b', order.away || '—')); match.append(teams); tr.append(match);
    tr.append(element('td', order.section || 'Unspecified', 'category'));
    const qty = element('td', order.quantity == null ? '—' : integer.format(order.quantity), 'numeric qty');
    if (order.issues.length) { const flag = element('span', '⚑', 'issue'); flag.title = order.issues.join(' · '); flag.setAttribute('aria-label', flag.title); qty.append(flag); }
    tr.append(qty, element('td', money(order.unitPrice), 'numeric unitprice'), element('td', money(order.totalSales), 'numeric moneytotal'));
    const allocation = element('td'); allocation.append(element('span', { unallocated: 'Unallocated', allocated: 'Allocated', review: 'Needs review' }[order.status], `badge ${order.status}`)); tr.append(allocation);
    const source = element('td'); const link = sourceLink(order, 'Open', 'source-link'); link.setAttribute('aria-label', `Open source row ${order.sourceRow}`); source.append(link); tr.append(source);
    ['Order', 'Match', 'Section / category', 'Quantity', 'Unit sale', 'Total sales', 'Allocation', 'Source'].forEach((label, index) => tr.children[index].dataset.label = label);
    $('orderrows').append(tr);
  });
  $('empty').hidden = selected.length > 0;
  $('empty-title').textContent = loaded ? 'No orders match these filters' : 'Your buying list starts here';
  $('empty-description').textContent = loaded ? 'Try another match, section, or allocation status.' : 'Connect your Google account to see your orders.';
  $('showing').textContent = loaded ? `Showing ${Math.min(visible, selected.length)} of ${integer.format(selected.length)} orders` : 'No orders loaded';
  $('more').hidden = selected.length <= visible;
  $('copy-status').textContent = '';
  updateCopyButton();
}
async function refresh() {
  ordersRefreshing = true;
  updateCopyButton();
  $('refresh').disabled = true;
  $('updated').textContent = 'Refreshing…';
  try {
    const data = await api('/api/orders');
    orders = data.orders; loaded = true; fetchedAt = data.fetchedAt; visible = 75;
    rebuildMatches(); rebuildSections(); connection(true); render();
    const warnings = orders.filter(order => order.issues.length).length;
    notice(warnings ? `${warnings} source orders have missing or invalid data. Flagged rows are marked for review; missing values are excluded from the corresponding totals.` : '');
    $('updated').textContent = `Updated ${new Date(fetchedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
  } catch (error) {
    if (error.code === 'sign_in_required') { orders = []; loaded = false; connection(false); render(); }
    notice(error.message);
    $('updated').textContent = fetchedAt ? 'Refresh failed · previous data shown' : 'Could not load orders';
  } finally { ordersRefreshing = false; updateCopyButton(); $('refresh').disabled = !connected; }
}
['match', 'allocation'].forEach(id => $(id).addEventListener('change', () => { visible = 75; rebuildSections(); render(); }));
['section', 'sort'].forEach(id => $(id).addEventListener('change', () => { visible = 75; render(); }));
$('search').addEventListener('input', () => { visible = 75; render(); });
$('more').addEventListener('click', () => { visible += 75; render(); });
$('copy-unallocated').addEventListener('click', copyUnallocated);
$('copy-close').addEventListener('click', () => $('copy-dialog').close());
function clearProfit() {
  profitRequest++;
  $('profit-value').textContent = '—';
  $('profit-change').textContent = '—';
  $('profit-change').className = '';
  $('profit-updated').textContent = 'Awaiting connection';
  $('profit-baseline').textContent = 'No snapshot available yet';
  $('profit-history').replaceChildren();
  $('profit-empty').hidden = false;
  $('profit-status').textContent = 'Sign in to view the current figure and snapshot history.';
}
function signedMoney(value) { return `${Number(value) > 0 ? '+' : ''}${money(Number(value))}`; }
function changeClass(value) { return Number(value) > 0 ? 'positive' : Number(value) < 0 ? 'negative' : ''; }
async function refreshProfit() {
  if (!connected) return;
  const requestId = ++profitRequest;
  $('refresh').disabled = true;
  $('profit-status').textContent = 'Refreshing Live Profit…';
  try {
    const data = await api('/api/profit');
    if (requestId !== profitRequest || !connected) return;
    const { figure, snapshots } = data;
    $('profit-value').textContent = money(Number(figure.value));
    $('profit-updated').textContent = `Read ${new Date(figure.fetchedAt).toLocaleString('en-GB', { timeZone: 'Africa/Johannesburg' })} SAST`;
    const latest = snapshots.history[0];
    const delta = latest ? Number(figure.value) - Number(latest.value) : null;
    $('profit-change').textContent = delta == null ? '—' : signedMoney(delta);
    $('profit-change').className = delta == null ? '' : changeClass(delta);
    $('profit-baseline').textContent = latest ? `Compared with ${latest.date} · ${money(Number(latest.value))}` : 'The first scheduled capture establishes your baseline';
    $('profit-status').textContent = {
      setup_required: 'Automatic snapshots need setup. The current figure is available; saved history is shown below.',
      retrying: 'The last snapshot attempt failed. Retrying every minute; existing history is preserved.',
      storage_error: 'Snapshot storage is unavailable. The current figure is available; history could not be loaded.',
      scheduled: `Automatic snapshots are scheduled. Next scheduled date: ${snapshots.nextDate} (SAST).`
    }[snapshots.state] || 'Snapshot status unavailable.';
    $('profit-history').replaceChildren();
    snapshots.history.forEach(snapshot => snapshot.kinds.forEach(kind => {
      const comparison = snapshot.comparisons[kind];
      const row = element('tr');
      const date = element('td', snapshot.date);
      date.append(element('small', `Captured ${new Date(snapshot.capturedAt).toLocaleString('en-GB', { timeZone: 'Africa/Johannesburg' })} SAST`, 'capture-time'));
      row.append(date, element('td', kind === 'weekly' ? 'Monday' : 'Month start'),
        element('td', money(Number(snapshot.value)), 'numeric moneytotal'),
        element('td', comparison.previousValue == null ? '—' : `${money(Number(comparison.previousValue))} (${comparison.previousDate})`, 'numeric'),
        element('td', comparison.change == null ? 'First snapshot' : signedMoney(comparison.change), `numeric ${comparison.change == null ? '' : changeClass(comparison.change)}`),
        element('td', comparison.changePercent == null ? '—' : `${Number(comparison.changePercent) > 0 ? '+' : ''}${integer.format(Number(comparison.changePercent))}%`, 'numeric'));
      ['Snapshot date (SAST)', 'Schedule', 'Profit', 'Previous profit', 'Change', 'Change %'].forEach((label, index) => row.children[index].dataset.label = label);
      $('profit-history').append(row);
    }));
    $('profit-empty').hidden = snapshots.history.length > 0;
  } catch (error) {
    if (requestId !== profitRequest) return;
    if (error.code === 'sign_in_required') { orders = []; loaded = false; connection(false); render(); }
    else $('profit-status').textContent = 'Refresh failed. Any previously displayed figures may be out of date.';
    notice(error.message);
  } finally { if (requestId === profitRequest || !connected) $('refresh').disabled = !connected; }
}
function selectView(view) {
  activeView = view;
  ['buying', 'profit'].forEach(name => {
    const selected = name === view;
    $(`${name}-panel`).hidden = !selected;
    $(`${name}-tab`).setAttribute('aria-selected', String(selected));
    $(`${name}-tab`).tabIndex = selected ? 0 : -1;
  });
  $('refresh').replaceChildren(element('span', '↻'), document.createTextNode(view === 'profit' ? ' Refresh profit' : ' Refresh orders'));
  if (view === 'profit') refreshProfit();
}
['buying', 'profit'].forEach(view => {
  $(`${view}-tab`).addEventListener('click', () => selectView(view));
  $(`${view}-tab`).addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 'buying' : event.key === 'End' ? 'profit' : view === 'buying' ? 'profit' : 'buying';
    selectView(next); $(`${next}-tab`).focus();
  });
});
$('refresh').addEventListener('click', () => activeView === 'profit' ? refreshProfit() : refresh());
$('clear').addEventListener('click', () => { $('match').value = ''; $('allocation').value = 'unallocated'; $('search').value = ''; $('sort').value = 'source'; $('section').value = ''; visible = 75; rebuildSections(); render(); });
$('disconnect').addEventListener('click', async () => { try { await api('/disconnect', { method: 'POST' }); orders = []; loaded = false; connection(false); render(); window.location.replace('/'); } catch (error) { notice(error.message); } });
(async () => {
  try { const status = await api('/api/status'); connection(status.connected); if (status.error) notice(status.error); if (status.connected) await refresh(); }
  catch (error) { connection(false); notice(error.message); }
})();
