/* Dashboard state, polling, WebSocket client and rendering. */

const state = {
  portfolio: null,
  sectors: [],
  feeds: {},
  owned: new Set(),
  sparks: {},          // stockId -> price series
  stock: null,         // the security currently charted in Price history
  securities: [],      // full symbol list, for the picker
  sort: { key: 'market_value', dir: -1 },
  relayConnected: false,
  marketOpen: false,
  ageSeconds: null,
};

const money = new Intl.NumberFormat('en-LK', {
  minimumFractionDigits: 2, maximumFractionDigits: 2,
});
const compact = new Intl.NumberFormat('en-LK', {
  notation: 'compact', maximumFractionDigits: 1,
});

const $ = (id) => document.getElementById(id);
const fmt = (n) => (n === null || n === undefined ? '—' : money.format(n));
const signed = (n) => (n === null || n === undefined ? '—'
  : (n >= 0 ? '+' : '') + money.format(n));
const signedPct = (n) => (n === null || n === undefined ? '—'
  : (n >= 0 ? '+' : '') + n.toFixed(2) + '%');
const cls = (n) => (n === null || n === undefined ? 'flat' : n > 0 ? 'up' : n < 0 ? 'down' : 'flat');
const esc = (s) => String(s).replace(/[&<>"]/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function showError(msg) {
  $('error-slot').innerHTML = msg ? `<div class="err">${esc(msg)}</div>` : '';
}

/* ---------------- data ---------------- */

async function loadPortfolio() {
  try {
    const r = await fetch('/api/portfolio');
    if (!r.ok) throw new Error(`portfolio: HTTP ${r.status}`);
    const body = await r.json();
    state.portfolio = body.portfolio;
    state.marketOpen = body.marketOpen;
    state.ageSeconds = body.asOfAgeSeconds;
    state.owned = new Set(body.portfolio.positions.map((p) => p.symbol));
    showError('');
    renderPortfolio();
    renderStatus();
    loadSparklines();
  } catch (err) {
    showError(`Could not load portfolio — ${err.message}. Retrying…`);
  }
}

async function loadSectors() {
  try {
    const r = await fetch('/api/sectors');
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    state.sectors = await r.json();
    renderHeatmap();
  } catch (err) {
    $('heatmap').innerHTML = `<div class="empty">sectors unavailable (${esc(err.message)})</div>`;
  }
}

async function loadSparklines() {
  const positions = (state.portfolio?.positions || []).filter((p) => p.stock_id);
  await Promise.all(positions.map(async (p) => {
    if (state.sparks[p.stock_id]) return;
    try {
      const r = await fetch(`/api/chart/${p.stock_id}?period=3`);
      if (!r.ok) return;
      const series = await r.json();
      state.sparks[p.stock_id] = series.map((x) => x.p).filter((x) => x !== null);
    } catch { /* a missing sparkline is cosmetic */ }
  }));
  renderPortfolio();
}

/* ---------------- price history ---------------- */

/* Daily points arrive as epoch ms at Colombo local midnight, so they must be
   formatted in Colombo time — formatting in UTC shifts every date back a day. */
const CO = 'Asia/Colombo';
const dayFmt = new Intl.DateTimeFormat('en-CA',
  { timeZone: CO, year: 'numeric', month: '2-digit', day: '2-digit' });
const clockFmt = new Intl.DateTimeFormat('en-GB',
  { timeZone: CO, hour: '2-digit', minute: '2-digit', hour12: false });

const stamp = (t, intraday) =>
  (intraday ? `${dayFmt.format(new Date(t))} ${clockFmt.format(new Date(t))}`
            : dayFmt.format(new Date(t)));

function shError(msg) {
  const box = $('sh-error');
  box.textContent = msg || '';
  box.hidden = !msg;
}

async function loadSecurities() {
  try {
    const r = await fetch('/api/securities');
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    state.securities = await r.json();
    $('sh-list').innerHTML = state.securities
      .map((s) => `<option value="${esc(s.symbol)}">${esc(s.name)}</option>`)
      .join('');
  } catch {
    state.securities = [];   // typing a symbol still works without the list
  }
}

async function loadStockHistory(symbol, period) {
  const query = (symbol || '').trim();
  if (!query) { shError('Enter a symbol or company name.'); return; }

  $('sh-note').textContent = 'Loading…';
  try {
    const r = await fetch(
      `/api/stock/history?symbol=${encodeURIComponent(query)}&period=${period}`);
    const body = await r.json();
    if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
    if (!body.points.length) throw new Error(`no price history for ${body.symbol}`);
    shError('');
    state.stock = body;
    renderStockHistory();
  } catch (err) {
    state.stock = null;
    $('sh-csv').disabled = true;
    $('sh-note').textContent = '';
    $('sh-meta').textContent = '';
    shError(`${err.message}`);
  }
}

function renderStockHistory() {
  const s = state.stock;
  if (!s) return;
  const intraday = s.period === 1;
  const labels = s.points.map((p) => (intraday
    ? clockFmt.format(new Date(p.t))
    : dayFmt.format(new Date(p.t))));

  priceHistory('sh-chart', s.points, labels, (v) => money.format(v));

  const closes = s.points.map((p) => p.p);
  const first = closes[0], last = closes[closes.length - 1];
  const move = last - first;
  const movePct = first ? (move / first) * 100 : 0;
  const hi = Math.max(...s.points.map((p) => (p.h ?? p.p)));
  const lo = Math.min(...s.points.map((p) => (p.l ?? p.p)));

  $('sh-meta').textContent =
    `— ${s.symbol} · ${s.name} · ${s.periodLabel}`;

  const held = state.owned.has(s.symbol) ? ' You hold this line.' : '';
  const alts = s.alternatives.length
    ? ` Also listed: ${s.alternatives.map((a) => a.symbol).join(', ')} — `
      + `enter one directly to chart that share class.`
    : '';

  $('sh-note').innerHTML =
    `<strong>${s.points.length}</strong> ${intraday ? 'trades' : 'sessions'} `
    + `from ${stamp(s.points[0].t, intraday)} to ${stamp(s.points[s.points.length - 1].t, intraday)}. `
    + `Last ${money.format(last)}, `
    + `<span class="${cls(move)}">${signed(move)} (${signedPct(movePct)})</span> `
    + `end to end; ranged ${money.format(lo)}–${money.format(hi)}.${held}${alts} `
    + `Prices are as traded and <strong>not adjusted for splits</strong>, so a `
    + `sudden step may be a change in share count rather than a change in value.`;

  $('sh-csv').disabled = false;
}

/* Export exactly what is charted, so the file and the picture always agree. */
function exportCsv() {
  const s = state.stock;
  if (!s) return;
  const intraday = s.period === 1;
  const num = (v) => (v === null || v === undefined ? '' : String(v));

  const rows = [
    `${intraday ? 'timestamp' : 'date'},close,high,low,volume`,
    ...s.points.map((p) => [
      stamp(p.t, intraday), num(p.p), num(p.h), num(p.l), num(p.q),
    ].join(',')),
  ];

  const name = `${s.symbol}_${s.periodLabel.replace(/\s+/g, '')}`
    + `_${dayFmt.format(new Date())}.csv`;
  const url = URL.createObjectURL(
    new Blob([rows.join('\n') + '\n'], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function initStockHistory() {
  await loadSecurities();
  // Open on a security you actually hold rather than an empty chart.
  let seed = '';
  try {
    const r = await fetch('/api/holdings');
    if (r.ok) seed = (await r.json())[0]?.symbol || '';
  } catch { /* seeding is a convenience, not a requirement */ }
  if (!seed) seed = state.securities[0]?.symbol || '';
  if (seed) {
    $('sh-symbol').value = seed;
    loadStockHistory(seed, Number($('sh-period').value));
  }
}

/* ---------------- websocket ---------------- */

function connectFeed() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  let socket;
  try {
    socket = new WebSocket(`${proto}://${location.host}/ws`);
  } catch {
    setTimeout(connectFeed, 5000);
    return;
  }

  socket.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.feed === '_snapshot') {
      Object.assign(state.feeds, msg.data.feeds || {});
      state.relayConnected = msg.data.connected;
    } else if (msg.feed === '_relay') {
      state.relayConnected = msg.data.connected;
    } else {
      state.feeds[msg.feed] = msg.data;
      state.relayConnected = true;
    }
    renderFeeds();
    renderStatus();
  };

  socket.onclose = () => {
    state.relayConnected = false;
    renderStatus();
    setTimeout(connectFeed, 5000);   // matches the upstream reconnectDelay
  };
  socket.onerror = () => socket.close();
}

/* ---------------- rendering ---------------- */

function renderStatus() {
  const marketPill = $('market-pill');
  marketPill.className = `pill ${state.marketOpen ? 'open' : 'closed'}`;
  $('market-text').textContent = state.marketOpen ? 'Market open' : 'Market closed';

  const status = state.feeds.status?.status;
  if (status) $('market-text').textContent = status;

  const feedPill = $('feed-pill');
  feedPill.className = `pill ${state.relayConnected ? 'live' : 'stale'}`;
  $('feed-text').textContent = state.relayConnected ? 'Live feed' : 'Feed offline';

  // Stale prices only matter while the market is trading -- after the close
  // the last snapshot is the correct value, not a warning.
  const agePill = $('age-pill');
  if (state.marketOpen && state.ageSeconds !== null && state.ageSeconds > 90) {
    agePill.hidden = false;
    agePill.className = 'pill stale';
    $('age-text').textContent = `Prices ${Math.round(state.ageSeconds)}s old`;
  } else {
    agePill.hidden = true;
  }
}

function renderPortfolio() {
  const pf = state.portfolio;
  if (!pf) return;

  $('h-value').textContent = fmt(pf.total_value);
  $('h-cost').textContent = `cost ${fmt(pf.total_cost)}`;

  const pnl = $('h-pnl');
  pnl.textContent = signed(pf.total_pnl);
  pnl.className = `value ${cls(pf.total_pnl)}`;
  $('h-pnlpct').textContent = signedPct(pf.total_pnl_pct) + ' vs cost';

  const day = $('h-day');
  day.textContent = signed(pf.total_day_change);
  day.className = `value ${cls(pf.total_day_change)}`;
  $('h-daypct').textContent = signedPct(pf.total_day_change_pct) + ' today';

  $('h-count').textContent = pf.positions.length;
  const ranked = pf.positions.filter((p) => p.pnl_pct !== null)
    .sort((a, b) => b.pnl_pct - a.pnl_pct);
  $('h-best').textContent = ranked.length
    ? `best ${ranked[0].symbol.split('.')[0]} ${signedPct(ranked[0].pnl_pct)} · worst ${ranked[ranked.length - 1].symbol.split('.')[0]} ${signedPct(ranked[ranked.length - 1].pnl_pct)}`
    : '';

  // sort
  const { key, dir } = state.sort;
  const rows = [...pf.positions].sort((a, b) => {
    const x = a[key], y = b[key];
    if (x === null || x === undefined) return 1;
    if (y === null || y === undefined) return -1;
    return typeof x === 'string' ? dir * x.localeCompare(y) : dir * (x - y);
  });

  $('holdings-body').innerHTML = rows.map((p) => {
    if (!p.priced) {
      return `<tr class="unpriced"><td><span class="sym">${esc(p.symbol)}</span>
        <div class="coname">not in today's market data</div></td>
        <td colspan="11" style="text-align:center;color:var(--warn)">unpriced</td></tr>`;
    }
    const spark = sparkline(state.sparks[p.stock_id], p.pnl >= 0);
    return `<tr>
      <td><span class="sym">${esc(p.symbol.split('.')[0])}</span>
          <div class="coname">${esc(p.name)}</div></td>
      <td>${spark}</td>
      <td class="num">${p.qty}</td>
      <td class="num">${money.format(p.avg_price)}</td>
      <td class="num">${money.format(p.bes_price)}</td>
      <td class="num">${money.format(p.last_price)}</td>
      <td class="num ${cls(p.day_change)}">${signed(p.day_change)}<br>
          <span style="font-size:11px">${signedPct(p.day_change_pct)}</span></td>
      <td class="num">${fmt(p.market_value)}</td>
      <td class="num ${cls(p.pnl)}">${signed(p.pnl)}</td>
      <td class="num ${cls(p.pnl_pct)}">${signedPct(p.pnl_pct)}</td>
      <td class="num ${cls(p.pnl_vs_bes_pct)}">${signedPct(p.pnl_vs_bes_pct)}</td>
      <td class="num">${p.cost_weight.toFixed(2)}%</td>
    </tr>`;
  }).join('');

  $('holdings-foot').innerHTML = `<tr>
    <td>Total</td><td></td><td></td><td></td><td></td><td></td>
    <td class="${cls(pf.total_day_change)}">${signed(pf.total_day_change)}</td>
    <td>${fmt(pf.total_value)}</td>
    <td class="${cls(pf.total_pnl)}">${signed(pf.total_pnl)}</td>
    <td class="${cls(pf.total_pnl_pct)}">${signedPct(pf.total_pnl_pct)}</td>
    <td></td><td>100.00%</td></tr>`;

  if (pf.unpriced.length) {
    showError(`No live price for ${pf.unpriced.join(', ')} — totals exclude these.`);
  }

  const priced = pf.positions.filter((p) => p.market_value !== null);
  donut('alloc-chart', priced.map((p) => p.symbol.split('.')[0]),
        priced.map((p) => p.market_value), fmt);
  donut('sector-chart', pf.sector_exposure.map((s) => s.sector),
        pf.sector_exposure.map((s) => s.value), fmt);
}

function renderHeatmap() {
  if (!state.sectors.length) {
    $('heatmap').innerHTML = '<div class="empty">no sector data</div>';
    return;
  }
  const mine = new Set((state.portfolio?.sector_exposure || []).map((s) => s.sectorId));
  const maxTurnover = Math.max(...state.sectors.map((s) => s.turnover || 0), 1);

  $('heatmap').innerHTML = state.sectors.map((s) => {
    // Turnover drives tile width so the eye lands on where money actually moved.
    const weight = Math.sqrt((s.turnover || 0) / maxTurnover);
    const grow = (1 + weight * 3).toFixed(2);
    const owned = mine.has(s.sectorId);
    return `<div class="tile ${owned ? 'mine' : ''} ${s.hasData ? '' : 'nodata'}"
      style="background:${heatColor(s.percentage)};flex-grow:${grow}"
      title="${esc(s.name)} — turnover ${fmt(s.turnover)}">
      ${owned ? '<span class="own">HELD</span>' : ''}
      <div class="n">${esc(s.name)}</div>
      <div class="v ${cls(s.percentage)}">${s.hasData ? signedPct(s.percentage) : 'n/a'}</div>
      <div class="t">${compact.format(s.turnover || 0)}</div>
    </div>`;
  }).join('');
}

function renderFeeds() {
  // indices
  const rows = [];
  const idx = (label, feed) => {
    const d = state.feeds[feed];
    if (!d) return;
    rows.push(`<div class="index-row">
      <span class="nm">${label}</span>
      <span><span class="vl">${money.format(d.value)}</span>
        <span class="ch ${cls(d.change)}">${signed(d.change)} (${signedPct(d.percentage)})</span></span>
    </div>`);
  };
  idx('ASPI', 'aspi');
  idx('S&P SL20', 'snp');

  const s = state.feeds.summary;
  if (s) {
    rows.push(`<div class="index-row" style="border-top:1px solid var(--line);padding-top:10px">
      <span class="nm">Turnover</span><span class="ch">${compact.format(s.tradeVolume || 0)}</span></div>
      <div class="index-row"><span class="nm">Shares</span>
        <span class="ch">${compact.format(s.shareVolume || 0)}</span></div>
      <div class="index-row"><span class="nm">Trades</span>
        <span class="ch">${compact.format(s.trades || 0)}</span></div>`);
  }
  if (rows.length) $('indices').innerHTML = rows.join('');

  movers('gainers', state.feeds['top-gainers']);
  movers('losers', state.feeds['top-looses']);
  activeList('active', state.feeds['most-active-trades']);
}

/* Gainers/losers carry price + changePercentage. */
function movers(elId, data) {
  if (!Array.isArray(data) || !data.length) return;
  $(elId).innerHTML = data.slice(0, 10).map((r) => {
    const owned = state.owned.has(r.symbol);
    return `<div class="leader ${owned ? 'owned' : ''}">
      <span class="s">${esc(r.symbol.split('.')[0])}${owned ? '<span class="badge">HELD</span>' : ''}</span>
      <span class="p">${money.format(r.price)}</span>
      <span class="c ${cls(r.changePercentage)}">${signedPct(r.changePercentage)}</span>
    </div>`;
  }).join('');
}

/* most-active-trades has no `price` field -- only shareVolume and turnover.
   Showing money.format(r.price) here rendered "NaN". */
function activeList(elId, data) {
  if (!Array.isArray(data) || !data.length) return;
  $(elId).innerHTML = data.slice(0, 10).map((r) => {
    const owned = state.owned.has(r.symbol);
    return `<div class="leader ${owned ? 'owned' : ''}"
        title="${esc(r.symbol)} — ${compact.format(r.shareVolume || 0)} shares, turnover ${fmt(r.turnover)}">
      <span class="s">${esc(r.symbol.split('.')[0])}${owned ? '<span class="badge">HELD</span>' : ''}</span>
      <span class="p" style="color:var(--muted)">${compact.format(r.shareVolume || 0)}</span>
      <span class="c">${compact.format(r.turnover || 0)}</span>
    </div>`;
  }).join('');
}

/* ---------------- holdings editor ---------------- */

function editorRow(h = { symbol: '', qty: '', avgPrice: '', besPrice: '' }) {
  const div = document.createElement('div');
  div.className = 'hrow';
  div.innerHTML = `
    <input placeholder="ABC.N0000" value="${esc(h.symbol)}" data-f="symbol">
    <input type="number" min="1" step="1" placeholder="0" value="${h.qty}" data-f="qty">
    <input type="number" min="0" step="0.0001" placeholder="0.00" value="${h.avgPrice}" data-f="avgPrice">
    <input type="number" min="0" step="0.0001" placeholder="optional" value="${h.besPrice ?? ''}" data-f="besPrice">
    <button class="danger" title="Remove">✕</button>`;
  div.querySelector('button').onclick = () => div.remove();
  return div;
}

async function openEditor() {
  const rows = await (await fetch('/api/holdings')).json();
  const box = $('editor-rows');
  box.innerHTML = '';
  rows.forEach((h) => box.appendChild(editorRow(h)));
  $('editor-error').hidden = true;
  $('editor').showModal();
}

async function saveEditor() {
  const payload = [...$('editor-rows').children].map((row) => {
    const get = (f) => row.querySelector(`[data-f="${f}"]`).value.trim();
    return {
      symbol: get('symbol').toUpperCase(),
      qty: Number(get('qty')),
      avgPrice: Number(get('avgPrice')),
      besPrice: get('besPrice') ? Number(get('besPrice')) : null,
    };
  }).filter((h) => h.symbol);

  const bad = payload.find((h) => !Number.isFinite(h.qty) || h.qty <= 0
    || !Number.isFinite(h.avgPrice) || h.avgPrice <= 0);
  if (bad) {
    const box = $('editor-error');
    box.textContent = `${bad.symbol}: quantity and average price must be positive numbers.`;
    box.hidden = false;
    return;
  }

  const r = await fetch('/api/holdings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!r.ok) {
    const box = $('editor-error');
    box.textContent = (await r.json()).detail || `Save failed (HTTP ${r.status})`;
    box.hidden = false;
    return;
  }
  $('editor').close();
  state.sparks = {};
  loadPortfolio();
}

/* ---------------- wiring ---------------- */

document.querySelectorAll('#holdings-table th[data-sort]').forEach((th) => {
  th.onclick = () => {
    const key = th.dataset.sort;
    state.sort = { key, dir: state.sort.key === key ? -state.sort.dir : -1 };
    document.querySelectorAll('#holdings-table th .arrow').forEach((a) => a.remove());
    th.insertAdjacentHTML('beforeend',
      `<span class="arrow">${state.sort.dir < 0 ? '▼' : '▲'}</span>`);
    renderPortfolio();
  };
});

$('edit-btn').onclick = openEditor;
$('cancel-edit').onclick = () => $('editor').close();
$('save-edit').onclick = saveEditor;
$('add-row').onclick = () => $('editor-rows').appendChild(editorRow());
$('refresh-btn').onclick = () => { loadPortfolio(); loadSectors(); };

$('sh-form').onsubmit = (e) => {
  e.preventDefault();
  loadStockHistory($('sh-symbol').value, Number($('sh-period').value));
};
// Changing the period re-queries immediately; making you press Show as well
// would be a second step for an unambiguous intent.
$('sh-period').onchange = () =>
  loadStockHistory($('sh-symbol').value, Number($('sh-period').value));
$('sh-csv').onclick = exportCsv;

loadPortfolio();
loadSectors();
initStockHistory();
connectFeed();

// Portfolio prices come from REST (the WebSocket's today-sharePrice carries only
// 10 symbols, so it cannot price an arbitrary book). Poll while open, idle after.
setInterval(loadPortfolio, 20000);
setInterval(loadSectors, 60000);
