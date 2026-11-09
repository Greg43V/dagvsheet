const $ = id => document.getElementById(id);
const gbp = new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP', maximumFractionDigits: 2 });
const integer = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 2 });
let orders = [], loaded = false, connected = false, visible = 75, fetchedAt = null;
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
    const tr = element('tr');
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
    tr.append(qty, element('td', money(order.unitPrice), 'numeric'), element('td', money(order.totalSales), 'numeric moneytotal'));
    const allocation = element('td'); allocation.append(element('span', { unallocated: 'Unallocated', allocated: 'Allocated', review: 'Needs review' }[order.status], `badge ${order.status}`)); tr.append(allocation);
    const source = element('td'); const link = sourceLink(order, 'Open', 'source-link'); link.setAttribute('aria-label', `Open source row ${order.sourceRow}`); source.append(link); tr.append(source);
    $('orderrows').append(tr);
  });
  $('empty').hidden = selected.length > 0;
  $('empty-title').textContent = loaded ? 'No orders match these filters' : 'Your buying list starts here';
  $('empty-description').textContent = loaded ? 'Try another match, section, or allocation status.' : 'Connect your Google account to see your orders.';
  $('showing').textContent = loaded ? `Showing ${Math.min(visible, selected.length)} of ${integer.format(selected.length)} orders` : 'No orders loaded';
  $('more').hidden = selected.length <= visible;
}
async function refresh() {
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
  } finally { $('refresh').disabled = !connected; }
}
['match', 'allocation'].forEach(id => $(id).addEventListener('change', () => { visible = 75; rebuildSections(); render(); }));
['section', 'sort'].forEach(id => $(id).addEventListener('change', () => { visible = 75; render(); }));
$('search').addEventListener('input', () => { visible = 75; render(); });
$('more').addEventListener('click', () => { visible += 75; render(); });
$('refresh').addEventListener('click', refresh);
$('clear').addEventListener('click', () => { $('match').value = ''; $('allocation').value = 'unallocated'; $('search').value = ''; $('sort').value = 'source'; $('section').value = ''; visible = 75; rebuildSections(); render(); });
$('disconnect').addEventListener('click', async () => { try { await api('/disconnect', { method: 'POST' }); orders = []; loaded = false; connection(false); render(); window.location.replace('/'); } catch (error) { notice(error.message); } });
(async () => {
  try { const status = await api('/api/status'); connection(status.connected); if (status.error) notice(status.error); if (status.connected) await refresh(); }
  catch (error) { connection(false); notice(error.message); }
})();
