/* CTA bus speed scorecard: renders every chart and number on the page from the build outputs.
   The data is fetched from the relative data/bus-speed-scorecard/ directory; a single-file bundle sets
   window.BUS_SCORECARD = {scorecard, cells, outline} instead. */
(function () {
  'use strict';
  const BASE = 'data/bus-speed-scorecard/';
  const BINS = [5, 6.5, 8, 10, 12, 15];
  const CLASS_LABELS = ['under 5', '5–6.5', '6.5–8', '8–10', '10–12', '12–15', '15+'];
  const HOURS = Array.from({ length: 18 }, (_, i) => i + 5);
  const NS = 'http://www.w3.org/2000/svg';
  let D, CELLS, OUTLINE;
  const state = { mode: 'peak', period: 'pm', sort: { key: 'rank', dir: 1 } };

  const $ = (sel, root = document) => root.querySelector(sel);
  const f1 = (x) => (x == null || Number.isNaN(x) ? '—' : Number(x).toFixed(1));
  const pct = (x) => `${Math.round(x * 100)}%`;
  const sgn = (n) => (n < 0 ? `−${Math.abs(n)}` : String(n));
  const WORDS = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve',
    'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen', 'twenty'];
  const word = (n) => WORDS[n] || String(n);
  const cls = (v) => BINS.filter((b) => v >= b).length;
  const hourLabel = (h) => (h === 12 ? 'noon' : h < 12 ? `${h} AM` : `${h - 12} PM`);
  const shortName = (n) => n.replace('Inner Lake Shore/Michigan Express', 'Inner Lake Shore Exp.');

  function svg(tag, attrs = {}, parent) {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    if (parent) parent.appendChild(el);
    return el;
  }
  function text(parent, x, y, str, attrs = {}) {
    const t = svg('text', { x, y, ...attrs }, parent);
    t.textContent = str;
    return t;
  }
  function h(tag, attrs = {}, kids = []) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'text') el.textContent = v; else if (k === 'class') el.className = v; else el.setAttribute(k, v);
    }
    for (const k of [].concat(kids)) if (k != null) el.appendChild(typeof k === 'string' ? document.createTextNode(k) : k);
    return el;
  }

  // ---- Tooltip (hover and keyboard focus share it) -----------------------------------------------
  const tip = () => $('#tip');
  function showTip(evt, lines) {
    const t = tip();
    t.replaceChildren(...lines.map((l, i) => h('div', { class: i ? 't-sub' : '' }, [l])));
    t.hidden = false;
    let x, y;
    if (evt && evt.clientX != null && evt.type !== 'focus') { x = evt.clientX; y = evt.clientY; }
    else { const r = evt.target.getBoundingClientRect(); x = r.left + r.width / 2; y = r.top; }
    const w = t.offsetWidth, hgt = t.offsetHeight;
    let left = x + 14, top = y - hgt - 10;
    if (left + w > window.innerWidth - 8) left = x - w - 14;
    if (left < 8) left = 8;
    if (top < 8) top = y + 18;
    t.style.left = `${left}px`; t.style.top = `${top}px`;
  }
  function hideTip() { tip().hidden = true; }
  function bindTip(el, linesFn) {
    el.addEventListener('pointermove', (e) => showTip(e, linesFn()));
    el.addEventListener('pointerleave', hideTip);
    el.addEventListener('focus', (e) => showTip(e, linesFn()));
    el.addEventListener('blur', hideTip);
  }

  // ---- Data ---------------------------------------------------------------------------------------
  async function load() {
    if (window.BUS_SCORECARD) return window.BUS_SCORECARD;
    const get = (f) => fetch(BASE + f).then((r) => { if (!r.ok) throw new Error(`${f}: HTTP ${r.status}`); return r.json(); });
    const [scorecard, cells, outline] = await Promise.all([get('scorecard.json'), get('map_cells.json'), get('chicago-outline.json')]);
    return { scorecard, cells, outline };
  }
  const linkBase = () => window.BUS_SCORECARD_LINK_BASE || '';

  // ---- Bound numbers in the prose ------------------------------------------------------------------
  function bindNumbers() {
    const s = D.system, R = D.routes;
    const slowest = R.reduce((a, b) => (b.peak_mph < a.peak_mph ? b : a));
    const byPen = [...R].sort((a, b) => b.penalty - a.penalty);
    const adv = D.express.flatMap((e) => ['am', 'pm'].filter((p) => e[p]).map((p) => e[p].advantage));
    const ranks = Object.values(s.top20_peak_ranks || {});
    // Outside the wider downtown (Roosevelt to North Ave, east of Ashland), one stretch per route and place.
    const nearDowntown = (x) => { const la = (x.start[0] + x.end[0]) / 2, lo = (x.start[1] + x.end[1]) / 2; return la > 41.86 && la < 41.91 && lo > -87.66; };
    const stretches = R.flatMap((r) => r.slowest_stretch_rush.map((x) => ({ ...x, route: r.route })))
      .filter((x) => !nearDowntown(x)).sort((a, b) => a.mph - b.mph);
    const seenR = new Set(), seenW = new Set(), picks = [];
    for (const x of stretches) {
      if (seenR.has(x.route) || seenW.has(x.where) || picks.length >= 4) continue;
      seenR.add(x.route); seenW.add(x.where); picks.push(x);
    }
    const phrase = (w) => { const [on, cross] = w.split(', '); return cross.startsWith('at ') ? `${on} ${cross}` : `${on} between ${cross.replace(' to ', ' and ')}`; };
    const listText = picks.map((x) => `${phrase(x.where)} (route ${x.route}, ${f1(x.mph)} mph)`);
    const e2e = R.reduce((a, b) => (b.peak_minutes_end_to_end - b.mid_minutes_end_to_end > a.peak_minutes_end_to_end - a.mid_minutes_end_to_end ? b : a));
    const sens = {};
    D.sensitivity.filter((x) => x.route !== 'TOP20').forEach((x) => { (sens[x.route] = sens[x.route] || []).push(x.peak_mph); });
    const sensMax = Math.max(...Object.values(sens).map((v) => Math.max(...v) - Math.min(...v)));
    const vals = {
      'counts.raw_rows_m': (s.counts_top20.raw_rows / 1e6).toFixed(1),
      days: String(D.meta.service_days.length),
      'top20.peak': f1(s.top20_pooled.peak), 'top20.mid': f1(s.top20_pooled.mid),
      'top20.pm': f1(s.top20_pooled.pm), 'top20.am': f1(s.top20_pooled.am),
      'other.peak': f1(s.other_routes_pooled.peak), 'other.n': String((s.other_routes || []).length),
      'belowmed.n': (() => {
        const others = (s.other_routes || []).map((r) => (D.all_routes.find((x) => x.route === r) || {}).peak_mph).filter((v) => v != null).sort((a, b) => a - b);
        const med = others.length % 2 ? others[(others.length - 1) / 2] : (others[others.length / 2 - 1] + others[others.length / 2]) / 2;
        const w = word(R.filter((r) => r.peak_mph < med).length);
        return w.charAt(0).toUpperCase() + w.slice(1);
      })(),
      'slowhalf.n': word(ranks.filter((k) => k <= s.route_count / 2).length),
      'stretches.list': listText.length ? `${listText.slice(0, -1).join(', ')} and ${listText[listText.length - 1]}` : '—',
      'express.range': `${Math.round(Math.min(...adv) * 100)}–${Math.round(Math.max(...adv) * 100)}%`,
      coverage: pct(s.counts_top20.fixed_segment_coverage),
      'slowest.label': `${slowest.route} ${slowest.name}`, 'slowest.peak': f1(slowest.peak_mph),
      'penalty.list': `${byPen[0].route} ${byPen[0].name} and ${byPen[1].route} ${byPen[1].name}`,
      'penalty.max': pct((byPen[0].penalty + byPen[1].penalty) / 2),
      'loop.pm': f1(s.regions.loop.pm),
      'e2e.route': `${e2e.route} ${e2e.name}`, 'e2e.peak': String(Math.round(e2e.peak_minutes_end_to_end)),
      'e2e.mid': String(Math.round(e2e.mid_minutes_end_to_end)),
      'sens.max': sensMax.toFixed(2),
    };
    document.querySelectorAll('[data-k]').forEach((el) => {
      const v = vals[el.dataset.k];
      if (v != null) el.textContent = v;
    });
  }

  // ---- Scorecard table -----------------------------------------------------------------------------
  const COLS = [
    { key: 'rank', label: '#', cls: 'l', val: (r) => r.rank },
    { key: 'route', label: 'Route', cls: 'l', val: (r) => Number(r.route) || 999 },
    { key: 'avg_weekday_rides', label: 'Riders', val: (r) => r.avg_weekday_rides },
    { key: 'mid_mph', label: 'Midday', val: (r) => r.mid_mph },
    { key: 'peak_mph', label: 'Rush', val: (r) => r.peak_mph },
    { key: 'penalty', label: 'Change', val: (r) => r.penalty },
    { key: 'am_mph', label: 'AM rush', val: (r) => r.am_mph },
    { key: 'pm_mph', label: 'PM rush', val: (r) => r.pm_mph },
    { key: 'peak_minutes_end_to_end', label: 'End to end', val: (r) => r.peak_minutes_end_to_end },
    { key: 'stretch', label: 'Slowest half-mile at rush', cls: 'l', val: (r) => (r.slowest_stretch_rush[0] || {}).mph || 99 },
    { key: 'hourly', label: '5 AM → 11 PM', val: null },
  ];
  function sparkline(hourly) {
    const w = 120, hh = 28, vals = hourly.filter((v) => v != null);
    const lo = 5, hi = 14;
    const x = (i) => (i / (hourly.length - 1)) * w;
    const y = (v) => hh - 2 - ((Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo)) * (hh - 4);
    const s = svg('svg', { class: 'spark', viewBox: `0 0 ${w} ${hh}`, 'aria-hidden': 'true' });
    for (const [a, b] of [[7, 9], [16, 18]]) svg('rect', { class: 'rushband', x: x(a - 5), y: 0, width: x(b - 5) - x(a - 5), height: hh }, s);
    let d = '';
    hourly.forEach((v, i) => { if (v != null) d += `${d ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`; });
    svg('path', { d }, s);
    return vals.length ? s : null;
  }
  function renderTable() {
    const head = $('#scorecard-head'), body = $('#scorecard-body');
    head.replaceChildren();
    COLS.forEach((c) => {
      const th = h('th', { scope: 'col', class: c.cls || '' });
      if (c.val) {
        const b = h('button', { type: 'button', text: c.label });
        b.addEventListener('click', () => {
          state.sort = { key: c.key, dir: state.sort.key === c.key ? -state.sort.dir : (['rank', 'route', 'mid_mph', 'peak_mph', 'am_mph', 'pm_mph', 'stretch'].includes(c.key) ? 1 : -1) };
          renderTable();
        });
        th.appendChild(b);
        if (state.sort.key === c.key) th.setAttribute('aria-sort', state.sort.dir > 0 ? 'ascending' : 'descending');
      } else th.textContent = c.label;
      head.appendChild(th);
    });
    const col = COLS.find((c) => c.key === state.sort.key);
    const rows = [...D.routes].sort((a, b) => (col.val(a) - col.val(b)) * state.sort.dir);
    const maxPen = Math.max(...D.routes.map((r) => r.penalty));
    body.replaceChildren(...rows.map((r) => {
      const st = r.slowest_stretch_rush[0];
      const pen = h('td', {}, [
        h('span', { text: Math.round(r.penalty * 100) === 0 ? '0%' : `−${Math.round(r.penalty * 100)}%` }),
        h('span', { class: 'bar', style: `width:${Math.max(2, (r.penalty / maxPen) * 44)}px` }),
        h('div', { class: 'ci', text: `${sgn(Math.round(r.penalty_ci[0] * 100))} to ${sgn(Math.round(r.penalty_ci[1] * 100))}%` }),
      ]);
      const sp = h('td'); const sl = sparkline(r.hourly); if (sl) sp.appendChild(sl);
      return h('tr', {}, [
        h('td', { class: 'l', text: String(r.rank) }),
        h('td', { class: 'l' }, [h('span', { class: 'badge', text: r.route }), shortName(r.name)]),
        h('td', { text: `${(r.avg_weekday_rides / 1000).toFixed(1)}k` }),
        h('td', { class: 'speed-mid', text: f1(r.mid_mph) }),
        h('td', {}, [h('span', { class: 'speed-rush', text: f1(r.peak_mph) }), h('div', { class: 'ci', text: `${f1(r.peak_ci[0])}–${f1(r.peak_ci[1])}` })]),
        pen,
        h('td', { text: f1(r.am_mph) }),
        h('td', { text: f1(r.pm_mph) }),
        h('td', { text: `${Math.round(r.peak_minutes_end_to_end)} min` }),
        h('td', { class: 'wrap' }, st ? [h('b', { text: `${f1(st.mph)} mph` }), ` · ${st.where}`, h('div', { class: 'ci', text: `toward ${st.toward}${st.note ? ` · ${st.note}` : ''}` })] : ['—']),
        sp,
      ]);
    }));
  }

  // ---- Dumbbell: midday vs rush, per route -------------------------------------------------------------
  function renderDumbbell() {
    const box = $('#dumbbell'); box.replaceChildren();
    const W = Math.max(320, box.clientWidth), narrow = W < 560;
    const key = { peak: 'peak_mph', am: 'am_mph', pm: 'pm_mph' }[state.mode];
    const rushLabel = { peak: 'Rush hour', am: 'Morning rush', pm: 'Evening rush' }[state.mode];
    const rows = [...D.routes].sort((a, b) => a[key] - b[key]);
    const rowH = narrow ? 26 : 28, top = 26, left = narrow ? 128 : 220, right = narrow ? 44 : 64;
    const Hh = top + rows.length * rowH + 30;
    const lo = 5.5, hi = 11;
    const x = (v) => left + ((v - lo) / (hi - lo)) * (W - left - right);
    const s = svg('svg', { viewBox: `0 0 ${W} ${Hh}`, role: 'img', 'aria-label': `${rushLabel} and midday speed for each route, slowest first` }, box);
    for (let t = 6; t <= 11; t++) {
      svg('line', { class: 'grid', x1: x(t), x2: x(t), y1: top - 6, y2: Hh - 26 }, s);
      text(s, x(t), Hh - 8, `${t} mph`, { 'text-anchor': 'middle', class: 'axis-label' });
    }
    text(s, W - 4, 12, 'Change', { 'text-anchor': 'end', class: 'axis-label' });
    rows.forEach((r, i) => {
      const y = top + i * rowH + rowH / 2;
      const g = svg('g', { class: 'row', tabindex: '0', 'aria-label': `${r.route} ${r.name}: midday ${f1(r.mid_mph)} mph, ${rushLabel.toLowerCase()} ${f1(r[key])} mph` }, s);
      if (i % 2 === 0) svg('rect', { class: 'row-band', x: 0, y: y - rowH / 2, width: W, height: rowH, rx: 3 }, g);
      else svg('rect', { class: 'row-band', x: 0, y: y - rowH / 2, width: W, height: rowH, rx: 3, style: 'fill:transparent' }, g);
      svg('rect', { class: 'route-badge', x: 4, y: y - 9, width: 36, height: 18, rx: 4 }, g);
      text(g, 22, y + 4, r.route, { 'text-anchor': 'middle', class: 'route-num' });
      const nm = narrow ? ({ 'Blue Island/26th': 'Blue Island', 'Inner Lake Shore/Michigan Express': 'Inner LSD Exp.' }[r.name] || r.name) : shortName(r.name);
      text(g, 48, y + 4.5, nm, { class: 'route-name' });
      const a = x(r.mid_mph), b = x(r[key]);
      svg('line', { class: 'connector', x1: Math.min(a, b) + 5, x2: Math.max(a, b) - 5, y1: y, y2: y }, g);
      svg('circle', { class: 'dot-mid', cx: a, cy: y, r: 6 }, g);
      svg('circle', { class: 'dot-rush', cx: b, cy: y, r: 6.5 }, g);
      if (Math.min(a, b) - 11 - 26 < left - 6) text(g, Math.max(a, b) + 11, y + 4, f1(r[key]), { class: 'val' });
      else text(g, Math.min(a, b) - 11, y + 4, f1(r[key]), { 'text-anchor': 'end', class: 'val' });
      const ch = 1 - r[key] / r.mid_mph;
      const chTxt = Math.round(ch * 100) === 0 ? '0%' : `${ch > 0 ? '−' : '+'}${Math.abs(Math.round(ch * 100))}%`;
      text(g, W - 4, y + 4, chTxt, { 'text-anchor': 'end', class: 'val', style: ch < 0.15 ? 'font-weight:400' : '' });
      const ci = r[`${state.mode}_ci`];
      bindTip(g, () => [`${r.route} ${r.name}`, `Midday ${f1(r.mid_mph)} mph (95%: ${f1(r.mid_ci[0])}–${f1(r.mid_ci[1])})`,
        `${rushLabel} ${f1(r[key])} mph (95%: ${f1(ci[0])}–${f1(ci[1])})`, `${(r.avg_weekday_rides / 1000).toFixed(1)}k weekday riders`]);
    });
    const lg = $('#dumbbell-legend');
    lg.replaceChildren(
      h('span', { class: 'key' }, [h('span', { class: 'sw', style: 'background:var(--mid)' }), 'Midday 10 AM–2 PM']),
      h('span', { class: 'key' }, [h('span', { class: 'sw', style: 'background:var(--rush)' }), { peak: 'Rush hour 7–9 AM and 4–6 PM', am: 'Morning rush 7–9 AM', pm: 'Evening rush 4–6 PM' }[state.mode]]),
      h('span', { class: 'key', text: 'Slowest at top' }));
  }

  // ---- Hourly line ---------------------------------------------------------------------------------
  function renderHourly() {
    const box = $('#hourly'); box.replaceChildren();
    const W = Math.max(320, box.clientWidth), Hh = W < 560 ? 240 : 290;
    const m = { t: 26, r: W < 560 ? 70 : 110, b: 30, l: 40 };
    const A = D.system.top20_hourly, B = D.system.other_routes_hourly;
    const lo = 7, hi = 14;
    const x = (hr) => m.l + ((hr - 5) / 18) * (W - m.l - m.r);
    const y = (v) => m.t + (1 - (v - lo) / (hi - lo)) * (Hh - m.t - m.b);
    const s = svg('svg', { viewBox: `0 0 ${W} ${Hh}`, role: 'img', 'aria-label': 'Average speed by hour of day, busiest 20 routes versus all other routes' }, box);
    for (const [a, b] of [[7, 9], [16, 18]]) {
      svg('rect', { class: 'band-rush', x: x(a), y: m.t, width: x(b) - x(a), height: Hh - m.t - m.b }, s);
      text(s, (x(a) + x(b)) / 2, m.t + 12, 'rush', { 'text-anchor': 'middle', class: 'axis-label' });
    }
    for (let v = lo; v <= hi; v++) {
      svg('line', { class: 'grid', x1: m.l, x2: W - m.r, y1: y(v), y2: y(v) }, s);
      text(s, m.l - 6, y(v) + 4, `${v}`, { 'text-anchor': 'end', class: 'axis-label' });
    }
    text(s, m.l - 6, m.t - 12, 'mph', { 'text-anchor': 'end', class: 'axis-label' });
    [6, 9, 12, 15, 18, 21].forEach((hr) => text(s, x(hr), Hh - 10, hourLabel(hr), { 'text-anchor': 'middle', class: 'axis-label' }));
    const path = (arr) => arr.map((v, i) => `${i ? 'L' : 'M'}${x(HOURS[i] + 0.5).toFixed(1)},${y(v).toFixed(1)}`).join('');
    svg('path', { class: 'line-other', d: path(B) }, s);
    svg('path', { class: 'line-top', d: path(A) }, s);
    const last = HOURS.length - 1;
    text(s, x(HOURS[last] + 0.5) + 8, y(B[last]) + 4, 'Other routes', { class: 'val', style: 'fill:var(--mid)' });
    text(s, x(HOURS[last] + 0.5) + 8, y(A[last]) + 4, '20 busiest', { class: 'val', style: 'fill:var(--rush)' });
    const minI = A.indexOf(Math.min(...A));
    svg('circle', { class: 'dot-rush', cx: x(HOURS[minI] + 0.5), cy: y(A[minI]), r: 5 }, s);
    text(s, x(HOURS[minI] + 0.5), y(A[minI]) + 20, `${f1(A[minI])} mph at ${hourLabel(HOURS[minI])}`, { 'text-anchor': 'middle', class: 'val' });
    const cross = svg('line', { class: 'baseline', y1: m.t, y2: Hh - m.b, x1: 0, x2: 0, visibility: 'hidden' }, s);
    const hit = svg('rect', { class: 'hit', x: m.l, y: m.t, width: W - m.l - m.r, height: Hh - m.t - m.b, tabindex: '0', 'aria-label': 'Hover or use arrow keys for hourly values' }, s);
    let idx = 10;
    const show = (e, i) => {
      idx = Math.max(0, Math.min(last, i));
      const cx = x(HOURS[idx] + 0.5); cross.setAttribute('x1', cx); cross.setAttribute('x2', cx); cross.setAttribute('visibility', 'visible');
      showTip(e, [`${hourLabel(HOURS[idx])}–${hourLabel(HOURS[idx] + 1)}`, `20 busiest routes: ${f1(A[idx])} mph`, `Other routes: ${f1(B[idx])} mph`]);
    };
    hit.addEventListener('pointermove', (e) => {
      const r = s.getBoundingClientRect(), px = ((e.clientX - r.left) / r.width) * W;
      show(e, Math.floor(((px - m.l) / (W - m.l - m.r)) * 18));
    });
    hit.addEventListener('pointerleave', () => { hideTip(); cross.setAttribute('visibility', 'hidden'); });
    hit.addEventListener('focus', (e) => show(e, idx));
    hit.addEventListener('blur', hideTip);
    hit.addEventListener('keydown', (e) => { if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { e.preventDefault(); show({ target: hit, type: 'focus' }, idx + (e.key === 'ArrowRight' ? 1 : -1)); } });
    $('#hourly-legend').replaceChildren(
      h('span', { class: 'key' }, [h('span', { class: 'sw', style: 'background:var(--rush)' }), '20 busiest routes']),
      h('span', { class: 'key' }, [h('span', { class: 'sw', style: 'background:var(--mid)' }), `${(D.system.other_routes || []).length} other frequent all-day routes`]));
  }

  // ---- Heatmap: route x hour ---------------------------------------------------------------------------
  function classLegend(el) {
    el.replaceChildren(h('span', { class: 'key', text: 'mph' }), ...CLASS_LABELS.map((l, i) =>
      h('span', { class: 'key' }, [h('span', { class: 'sw sq', style: `background:var(--c${i})` }), l])));
  }
  function renderHeatmap() {
    const box = $('#heatmap'); box.replaceChildren();
    const rows = [...D.routes].sort((a, b) => a.peak_mph - b.peak_mph);
    const left = 150, cw = Math.max(30, Math.min(52, (box.parentElement.clientWidth - left - 8) / 18)), ch = 24, top = 22;
    const W = left + cw * 18 + 4, Hh = top + rows.length * ch + 4;
    const s = svg('svg', { viewBox: `0 0 ${W} ${Hh}`, width: W, role: 'img', 'aria-label': 'Speed by route and hour of day' }, box);
    s.style.width = `${W}px`;
    HOURS.forEach((hr, j) => { if (hr % 3 === 0) text(s, left + j * cw + cw / 2, 14, hourLabel(hr), { 'text-anchor': 'middle', class: 'axis-label' }); });
    rows.forEach((r, i) => {
      const y = top + i * ch;
      text(s, 0, y + ch / 2 + 4, `${r.route} ${shortName(r.name)}`.slice(0, 22), { class: 'route-name' });
      r.hourly.forEach((v, j) => {
        if (v == null) return;
        const c = svg('rect', { class: 'heat-cell', x: left + j * cw, y, width: cw, height: ch, rx: 2, style: `fill:var(--c${cls(v)})`, tabindex: '-1' }, s);
        bindTip(c, () => [`${r.route} ${r.name}`, `${hourLabel(HOURS[j])}–${hourLabel(HOURS[j] + 1)}: ${f1(v)} mph`]);
      });
    });
    classLegend($('#heat-legend'));
  }

  // ---- Map ---------------------------------------------------------------------------------------------
  function renderMap() {
    const box = $('#speedmap'); box.replaceChildren();
    const all = Object.values(CELLS.periods).flat();
    const lat0 = Math.min(...all.map((c) => c[0])) - 0.006, lat1 = Math.max(...all.map((c) => c[0])) + 0.006;
    const lon0 = Math.min(...all.map((c) => c[1])) - 0.01, lon1 = -87.515;
    const k = Math.cos(((lat0 + lat1) / 2) * Math.PI / 180);
    const maxH = Math.max(520, Math.min(900, window.innerHeight * 1.05));
    const W = Math.max(300, Math.min(box.clientWidth, maxH * ((lon1 - lon0) * k) / (lat1 - lat0)));
    const sc = W / ((lon1 - lon0) * k), Hh = (lat1 - lat0) * sc;
    const px = (lon) => (lon - lon0) * k * sc, py = (lat) => (lat1 - lat) * sc;
    const s = svg('svg', { viewBox: `0 0 ${W} ${Hh.toFixed(0)}`, role: 'img', 'aria-label': 'Map of bus speeds along the 20 busiest routes' }, box);
    s.style.maxWidth = `${W}px`; s.style.margin = '0 auto';
    const clip = svg('clipPath', { id: 'mapclip' }, svg('defs', {}, s));
    svg('rect', { x: 0, y: 0, width: W, height: Hh }, clip);
    const land = svg('g', { 'clip-path': 'url(#mapclip)' }, s);
    OUTLINE.rings.forEach((ring) => svg('path', { class: 'map-land', d: ring.map((p, i) => `${i ? 'L' : 'M'}${px(p[0]).toFixed(1)},${py(p[1]).toFixed(1)}`).join('') + 'Z' }, land));
    text(s, px(-87.585), py(41.985), 'Lake Michigan', { class: 'lake-label' });
    const cw = 0.0027 * k * sc + 0.6, chh = 0.002 * sc + 0.6;
    const cells = [...CELLS.periods[state.period]].sort((a, b) => b[2] - a[2]);
    const g = svg('g', {}, s);
    cells.forEach((c) => {
      const r = svg('rect', { x: (px(c[1]) - cw / 2).toFixed(1), y: (py(c[0]) - chh / 2).toFixed(1), width: cw.toFixed(1), height: chh.toFixed(1), style: `fill:var(--c${cls(c[2])})` }, g);
      bindTip(r, () => [`${f1(c[2])} mph`, `Routes: ${c[4]}`, `${c[3].toLocaleString()} measurements`]);
    });
    const reg = D.system.regions;
    const callout = (lx, ly, tx, ty, l1, l2) => {
      svg('line', { class: 'callout-line', x1: px(lx), y1: py(ly), x2: px(tx) - 4, y2: py(ty) }, s);
      text(s, px(tx), py(ty) - 2, l1, { class: 'callout' });
      text(s, px(tx), py(ty) + 13, l2, { class: 'callout', style: 'font-weight:400' });
    };
    callout(-87.621, 41.882, -87.585, 41.872, 'The Loop', `${f1(reg.loop[state.period])} mph`);
    callout(-87.630, 41.936, -87.597, 41.932, 'Lake Shore Dr (146)', `${f1(reg.lsd_146[state.period])} mph`);
    const name = { am: 'morning rush', mid: 'midday', pm: 'evening rush' }[state.period];
    const under8 = cells.filter((c) => c[2] < 8).length / cells.length;
    $('#map-facts').replaceChildren(
      h('div', { class: 'fact' }, [h('b', { text: pct(under8) }), h('span', { text: `of mapped stretches average under 8 mph in the ${name}` })]),
      h('div', { class: 'fact' }, [h('b', { text: `${f1(reg.loop[state.period])} mph` }), h('span', { text: 'bus speed in the Loop' })]),
      h('div', { class: 'fact' }, [h('b', { text: `${f1(D.system.top20_pooled[state.period])} mph` }), h('span', { text: 'all 20 routes combined' })]));
    const lg = $('#map-legend');
    lg.replaceChildren(h('span', { class: 'key', text: 'Miles per hour' }), ...CLASS_LABELS.map((l, i) =>
      h('span', { class: 'key' }, [h('span', { class: 'sw sq', style: `background:var(--c${i})` }), l])));
  }

  // ---- Express vs local ---------------------------------------------------------------------------------
  function renderExpress() {
    const box = $('#expresschart'); box.replaceChildren();
    const W = Math.max(320, box.clientWidth), narrow = W < 560;
    const left = narrow ? 110 : 190, right = 56, rowH = 28, gapH = 18;
    const pers = [['am', 'Morning rush'], ['pm', 'Evening rush']];
    const names = { X9: 'Ashland', X49: 'Western', X4: 'Cottage Grove' };
    const Hh = D.express.length * (pers.length * rowH + gapH + 18) + 26;
    const lo = 8, hi = 11.5;
    const x = (v) => left + ((v - lo) / (hi - lo)) * (W - left - right);
    const s = svg('svg', { viewBox: `0 0 ${W} ${Hh}`, role: 'img', 'aria-label': 'Express versus local bus speeds on the same stretches, three corridors' }, box);
    for (let t = 8; t <= 11; t += 0.5) {
      svg('line', { class: 'grid', x1: x(t), x2: x(t), y1: 4, y2: Hh - 24 }, s);
      if (Number.isInteger(t)) text(s, x(t), Hh - 6, `${t} mph`, { 'text-anchor': 'middle', class: 'axis-label' });
    }
    let y = 8;
    D.express.forEach((e) => {
      text(s, 0, y + 12, `${names[e.express] || e.express}: ${e.local} vs ${e.express}`, { class: 'route-name', style: 'font-weight:700' });
      y += 18;
      pers.forEach(([p, lab]) => {
        const c = e[p];
        if (!c) return;
        const cy = y + rowH / 2, a = c.local_mph, b = c.express_mph;
        text(s, narrow ? 4 : 12, cy + 4, lab, { class: 'axis-label', style: 'font-size:12px;fill:var(--muted)' });
        svg('line', { class: 'connector', x1: x(a) + 5, x2: x(b) - 5, y1: cy, y2: cy, style: 'stroke:var(--line)' }, s);
        svg('circle', { class: 'dot-am', cx: x(a), cy, r: 6 }, s);
        svg('circle', { class: 'dot-mid', cx: x(b), cy, r: 6.5 }, s);
        text(s, W - 4, cy + 4, `+${Math.round(c.advantage * 100)}%`, { 'text-anchor': 'end', class: 'val' });
        const hit = svg('rect', { class: 'hit', x: left, y: cy - rowH / 2, width: W - left, height: rowH, tabindex: '0' }, s);
        bindTip(hit, () => [`${names[e.express]}, ${lab.toLowerCase()}`, `Local ${e.local}: ${f1(a)} mph`, `Express ${e.express}: ${f1(b)} mph`,
          `Same ${c.cells} segments for both`]);
        y += rowH;
      });
      y += gapH;
    });
    $('#express-legend').replaceChildren(
      h('span', { class: 'key' }, [h('span', { class: 'sw ring' }), 'Local bus']),
      h('span', { class: 'key' }, [h('span', { class: 'sw', style: 'background:var(--mid)' }), 'Express bus, same stretches']),
      h('span', { class: 'key', text: 'Right: express speed advantage' }));
  }

  // ---- Robustness ----------------------------------------------------------------------------------------
  function renderCalendar() {
    const cal = $('#calendar'); cal.replaceChildren();
    ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].forEach((d) => cal.appendChild(h('div', { class: 'dow', text: d })));
    const inc = new Set(D.meta.service_days), exc = D.meta.excluded_weekdays;
    const first = new Date(`${D.meta.archive_first.slice(0, 10)}T12:00:00`), last = new Date(`${D.meta.archive_last.slice(0, 10)}T12:00:00`);
    const start = new Date(first); start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
    const end = new Date(last); end.setDate(end.getDate() + (6 - ((end.getDay() + 6) % 7)));
    const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
      const k = iso(d), wk = d.getDay() === 0 || d.getDay() === 6;
      let c = 'none', why = 'Not in the archive';
      if (d >= first && d <= last) {
        if (inc.has(k)) { c = 'in'; why = 'Included'; }
        else if (exc[k]) { c = k === '2026-10-12' ? 'hol' : 'out'; why = exc[k]; }
        else if (wk) { c = 'wkd'; why = 'Weekend (not scored)'; }
      }
      const label = `${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}: ${why}`;
      const cell = h('div', { class: `day ${c}`, text: String(d.getDate()), tabindex: c === 'none' ? '-1' : '0', 'aria-label': label });
      bindTip(cell, () => [label]);
      cal.appendChild(cell);
    }
    $('#calendar-legend').replaceChildren(
      h('span', { class: 'key' }, [h('span', { class: 'sw sq', style: 'background:var(--mid)' }), `Scored weekday (${inc.size})`]),
      h('span', { class: 'key' }, [h('span', { class: 'sw sq', style: 'background:var(--rush)' }), 'Collector outage: PM rush missing']),
      h('span', { class: 'key' }, [h('span', { class: 'sw sq', style: 'background:var(--rush-soft)' }), 'Holiday']),
      h('span', { class: 'key' }, [h('span', { class: 'sw sq', style: 'background:var(--band)' }), 'Weekend']));
    const sv = D.sensitivity.filter((x) => x.route === 'TOP20');
    const hol = sv.find((x) => /Oct 12/.test(x.variant));
    const holidayDelta = hol ? Math.abs(hol.peak_mph - sv[0].peak_mph).toFixed(2) : '—';
    $('#calendar-note').textContent = `From October 13 to 16 the public archive lost every afternoon from about 1:15–2:30 PM to midnight. Keeping their morning data would have made “rush hour” mostly mornings, so those days are left out. October 12 (Indigenous Peoples’ Day, schools closed) is left out as a holiday; including it changes the rush-hour result by ${holidayDelta} mph. Short gaps on other days, up to 26 minutes, only remove a few measurements and are kept.`;
  }
  function renderQA() {
    const c = D.system.counts_top20;
    const n = (x) => x.toLocaleString('en-US');
    const rows = [
      ['GPS records, 20 routes, 20 weekdays', n(c.raw_rows)],
      ['After removing repeated (frozen) fixes', n(c.dedup_fixes)],
      ['Trips', n(c.trips)],
      ['Consecutive-fix segments', n(c.pairs)],
      ['Segments kept for speed', n(c.pairs_kept)],
      ['Bus-hours / bus-miles measured', `${n(c.vehicle_hours_kept)} / ${n(c.miles_kept)}`],
      ['Observed time removed as terminal layover', pct(c.share_time_layover)],
      ['Observed time in gaps over 3 minutes', pct(c.share_time_long_gap)],
    ];
    $('#qa').replaceChildren(h('table', { class: 'mini' }, [h('tbody', {}, rows.map(([a, b]) => h('tr', {}, [h('td', { text: a }), h('td', { text: b })])))]));
  }
  function renderSensitivity() {
    const rows = D.sensitivity.filter((x) => x.route === 'TOP20');
    const ref = rows[0];
    const delta = (v, r) => { const d = v - r; return `${d >= 0 ? '+' : '−'}${Math.abs(d).toFixed(2)}`; };
    const label = (v) => v.replace('main (20 weekdays)', 'This page (20 weekdays)').replace(/^./, (c) => c.toUpperCase());
    $('#sensitivity').replaceChildren(h('table', { class: 'mini' }, [
      h('thead', {}, [h('tr', {}, [h('th', { text: 'Days used' }), h('th', { text: 'Rush, mph' }), h('th', { text: 'Midday, mph' })])]),
      h('tbody', {}, rows.map((r, i) => h('tr', {}, [h('td', { text: label(r.variant) }),
        h('td', { text: i ? delta(r.peak_mph, ref.peak_mph) : f1(r.peak_mph) }),
        h('td', { text: i ? delta(r.mid_mph, ref.mid_mph) : f1(r.mid_mph) })]))),
    ]));
  }
  function renderRules() {
    const c = D.system.counts_top20, n = (x) => x.toLocaleString('en-US');
    const rules = [
      ['Frozen GPS fixes.', `A bus whose GPS stalls repeats its last position on later polls. Repeated fix times are collapsed, removing ${n(c.raw_rows - c.dedup_fixes)} records on these routes.`],
      ['Trips.', 'A trip is one bus on one route pattern with one scheduled start. Distance is never compared across patterns, because each pattern measures from its own start.'],
      ['Layovers.', `Each trip is measured from the first fix more than 500 feet past its start to the first fix within 500 feet of its end. This removes ${pct(c.share_time_layover)} of observed time. Without it, speeds read about 11% too low. Trim distances from 250 to 2,000 feet change results by under 1%.`],
      ['Gaps.', `Segments longer than 3 minutes are not bridged (${pct(c.share_time_long_gap)} of time). Keeping them would lower speeds by about 1%.`],
      ['Bad position snaps.', 'Segments where the reported distance goes backward, or jumps further than the GPS points moved (more than twice the straight-line distance plus 1,500 feet), are dropped, with an 80 mph backstop. A blanket 50 mph cap was rejected because it would delete real Lake Shore Drive driving on the 146.'],
      ['Standstills.', 'Runs of 10 minutes or more with almost no movement in the middle of a route (breakdowns, holds) are dropped. Ordinary stop and signal time stays in.'],
      ['Connector patterns.', 'Patterns shorter than half of a route’s main pattern, such as garage pull-outs, are left out. They run at 13–14 mph and would flatter some routes by about 1%.'],
      ['Same segments.', `Route speeds use ~220 m segments with at least 20 measurements in each period, weighted by distance identically in every period. They cover ${pct(c.fixed_segment_coverage)} of the distance traveled.`],
      ['Comparison routes.', `“Other routes” are the ${(D.system.other_routes || []).length} frequent non-express routes outside the top 20 with at least 100 bus-hours in each of the morning, midday and evening windows. Rush-only routes, express routes and lightly served routes are left out.`],
      ['Holding spots.', 'Segments that average under 1 mph in any period are treated as places buses wait, not travel, and left out of route speeds (two segments on these routes).'],
      ['Ranking.', 'The top 20 are ranked by average weekday boardings from September 2025 through August 2026, the latest twelve months the CTA has published.'],
    ];
    $('#rules').replaceChildren(...rules.map(([a, b]) => h('li', {}, [h('b', { text: a }), ` ${b}`])));
  }
  function renderReproduce() {
    $('#commands').textContent = [
      '# 1. Install the skill, then download and verify 33 days of bus positions (about 1.1 GB)',
      'npx skills add MisterClean/ai-plugins --skill chicago-transit-duckdb',
      'python3 -m venv .venv && .venv/bin/pip install "duckdb==2.0.0" pytz pandas numpy matplotlib',
      '.venv/bin/python <skill-dir>/scripts/transit_archive.py ingest --db transit.duckdb \\',
      '    --raw-dir raw --kinds bus --days 33 --end 2026-10-30 --as-of 2026-10-31',
      '',
      '# 2. Build the scorecard (opens transit.duckdb read-only, fetches CTA ridership)',
      '.venv/bin/python -I scripts/bus-speed-scorecard/build.py --db transit.duckdb \\',
      '    --ridership data/sources/cta-bus-daily.csv --fetch-ridership --out data/bus-speed-scorecard',
      '',
      '# 3. Render the graphics',
      '.venv/bin/python -I scripts/bus-speed-scorecard/render_social.py --variant dumbbell \\',
      '    --data data/bus-speed-scorecard/scorecard.json --out images/cta-bus-speed-scorecard.png',
      '.venv/bin/python -I scripts/bus-speed-scorecard/render_map.py --cells data/bus-speed-scorecard/corridor_cells.csv \\',
      '    --data data/bus-speed-scorecard/scorecard.json --wards data/chicago-wards.geojson --out images/cta-bus-speed-map.png',
    ].join('\n');
    $('#sql').textContent = D.meta.sql || 'See scripts/bus-speed-scorecard/scorecard.sql';
    const base = linkBase();
    const files = [
      ['scorecard.json', 'Every figure on this page, with 95% intervals'],
      ['route_day_hour.csv', 'Base table: feet and seconds by route, day and hour (all routes)'],
      ['route_daily.csv', 'Daily rush and midday speeds, top 20'],
      ['route_hourly.csv', 'Weekday speed by hour, all routes'],
      ['corridor_cells.csv', 'Map cells by route and period'],
      ['pattern_bins.csv', 'Quarter-mile segments along each pattern'],
      ['patterns.csv', 'Route patterns and inclusion decisions'],
      ['qa_funnel.csv', 'What each cleaning rule removed, by route'],
      ['source_manifest.csv', 'Archive files with SHA-256 checksums'],
    ];
    $('#downloads').replaceChildren(...files.map(([f, d]) => h('li', {}, [h('a', { href: `${base}${BASE}${f}`, text: f }), ` · ${d}`])),
      h('li', {}, [h('a', { href: `${base}images/cta-bus-speed-scorecard.png`, text: 'Scorecard graphic (PNG)' }), ' · ', h('a', { href: `${base}images/cta-bus-speed-map.png`, text: 'Map (PNG)' })]),
      h('li', {}, [h('a', { href: 'https://github.com/MisterClean/cta-bus-speed-scorecard/tree/main/scripts/bus-speed-scorecard', text: 'Pipeline source on GitHub' })]));
    $('#manifest').replaceChildren(h('thead', {}, [h('tr', {}, ['Date', 'Rows', 'Bytes', 'SHA-256'].map((x) => h('th', { text: x })))]),
      h('tbody', {}, (D.meta.manifest || []).map((m) => h('tr', {}, [m.archive_date, m.rows.toLocaleString(), m.bytes.toLocaleString(), m.sha256].map((x) => h('td', { text: String(x) }))))));
    $('#build-note').textContent = `Built ${D.meta.generated_at.replace('T', ' ').replace('+00:00', ' UTC')} with ${D.meta.duckdb_version.startsWith('v') ? 'DuckDB ' + D.meta.duckdb_version : 'DuckDB ' + D.meta.duckdb_version}. Archive: ${D.meta.archive_files} daily bus files, ${D.meta.archive_first} to ${D.meta.archive_last}, ${D.meta.archive_rows.toLocaleString()} rows.`;
  }

  // ---- Wiring ----------------------------------------------------------------------------------------------
  function wireSeg(selector, attr, key, fn) {
    document.querySelectorAll(`${selector} [data-${attr}]`).forEach((b) => b.addEventListener('click', () => {
      state[key] = b.dataset[attr];
      document.querySelectorAll(`${selector} [data-${attr}]`).forEach((o) => o.setAttribute('aria-checked', String(o === b)));
      fn();
    }));
  }
  function drawResponsive() { renderDumbbell(); renderHourly(); renderHeatmap(); renderMap(); renderExpress(); }

  async function init() {
    try {
      const data = await load();
      D = data.scorecard; CELLS = data.cells; OUTLINE = data.outline;
      $('#report').hidden = false; $('#load-status').remove();
      bindNumbers(); renderTable(); renderCalendar(); renderQA(); renderSensitivity(); renderRules(); renderReproduce();
      drawResponsive();
      wireSeg('#rush', 'mode', 'mode', renderDumbbell);
      wireSeg('#map', 'period', 'period', renderMap);
      let last = window.innerWidth, timer;
      window.addEventListener('resize', () => {
        if (Math.abs(window.innerWidth - last) < 8) return;
        last = window.innerWidth; clearTimeout(timer); timer = setTimeout(drawResponsive, 120);
      });
    } catch (err) {
      $('#load-status').textContent = `The scorecard data didn’t load (${err.message}). Reload the page, or download scorecard.json from the data folder.`;
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
