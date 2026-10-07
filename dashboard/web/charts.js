/* Chart.js wrappers: two donuts plus inline SVG sparklines. */

const PALETTE = ['#4c8dff', '#26c281', '#f5a623', '#a06cff', '#f2555a',
                 '#2bc4c9', '#ff8a4c', '#7c8aa5'];

Chart.defaults.color = '#8996ad';
Chart.defaults.font.family = 'system-ui, -apple-system, sans-serif';
Chart.defaults.font.size = 11;

const charts = {};

function donut(canvasId, labels, values, formatter) {
  const el = document.getElementById(canvasId);
  if (!el) return;
  if (charts[canvasId]) charts[canvasId].destroy();
  charts[canvasId] = new Chart(el, {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: labels.map((_, i) => PALETTE[i % PALETTE.length]),
        borderColor: '#131822',
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '62%',
      plugins: {
        legend: {
          position: 'right',
          labels: { boxWidth: 9, boxHeight: 9, padding: 8, usePointStyle: true },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
              const pct = total ? (ctx.raw / total * 100).toFixed(1) : '0.0';
              return ` ${ctx.label}: ${formatter(ctx.raw)} (${pct}%)`;
            },
          },
        },
      },
    },
  });
}

/* Inline SVG sparkline — cheaper than a Chart.js instance per table row. */
function sparkline(points, up) {
  if (!points || points.length < 2) return '';
  const w = 68, h = 22, pad = 2;
  const min = Math.min(...points), max = Math.max(...points);
  const span = max - min || 1;
  const step = (w - pad * 2) / (points.length - 1);
  const d = points
    .map((p, i) => {
      const x = pad + i * step;
      const y = pad + (h - pad * 2) * (1 - (p - min) / span);
      return `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
  const color = up ? '#26c281' : '#f2555a';
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
    <path d="${d}" fill="none" stroke="${color}" stroke-width="1.5"
          stroke-linejoin="round" stroke-linecap="round"/></svg>`;
}

/* Sector heat colour: red -> neutral -> green, saturation by magnitude. */
function heatColor(pct) {
  if (pct === null || pct === undefined) return '#1a2130';
  const capped = Math.max(-3, Math.min(3, pct));
  const strength = Math.abs(capped) / 3;
  const alpha = (0.10 + strength * 0.45).toFixed(3);
  return capped >= 0
    ? `rgba(38,194,129,${alpha})`
    : `rgba(242,85,90,${alpha})`;
}


/* Price history for one security.

   The series is coloured by its own direction over the window -- green when it
   closes above where it started, red when below -- so the chart reads before
   the axis does. Prices come back unadjusted for splits, which is why the
   caption warns about corporate actions rather than the chart smoothing them. */
function priceHistory(canvasId, points, labels, formatter) {
  const el = document.getElementById(canvasId);
  if (!el) return;
  if (charts[canvasId]) charts[canvasId].destroy();

  const closes = points.map((p) => p.p);
  const rising = closes.length > 1 && closes[closes.length - 1] >= closes[0];
  const line = rising ? '#26c281' : '#f2555a';
  const fill = rising ? 'rgba(38,194,129,.12)' : 'rgba(242,85,90,.12)';

  charts[canvasId] = new Chart(el, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: 'Close',
        data: closes,
        borderColor: line,
        backgroundColor: fill,
        borderWidth: 2,
        fill: true,
        tension: 0.12,
        // Only the latest point is marked, so the eye lands on where it ended.
        pointRadius: (ctx) => (ctx.dataIndex === closes.length - 1 ? 3.5 : 0),
        pointBackgroundColor: line,
        pointHoverRadius: 4,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      scales: {
        x: {
          grid: { display: false },
          ticks: { maxTicksLimit: 9, maxRotation: 0, autoSkip: true },
        },
        y: {
          grid: { color: 'rgba(35,44,61,.6)' },
          ticks: { callback: (v) => formatter(v) },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => ` Close ${formatter(ctx.raw)}`,
            afterBody: (items) => {
              const p = points[items[0].dataIndex];
              const out = [];
              if (p.h !== null && p.l !== null) {
                out.push(`High ${formatter(p.h)} · Low ${formatter(p.l)}`);
              }
              if (p.q) out.push(`Volume ${p.q.toLocaleString('en-LK')}`);
              return out;
            },
          },
        },
      },
    },
  });
}
