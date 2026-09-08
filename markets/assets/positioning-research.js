(() => {
  'use strict';
  const $ = (selector) => document.querySelector(selector);
  const state = { sector: 'metals', data: {}, selected: null };
  const labels = { metals: '金属', financial: '金融', energy: '能源', agriculture: '农产品', agri: '农产品' };
  const valid = (value) => typeof value === 'number' && Number.isFinite(value);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const number = (value, places = 0) => valid(value) ? value.toLocaleString('zh-CN', { maximumFractionDigits: places, minimumFractionDigits: places }) : '未知';
  const signed = (value, places = 0) => valid(value) ? `${value > 0 ? '+' : ''}${number(value, places)}` : '未知';
  const href = (url) => { try { const u = new URL(url); return u.protocol === 'https:' ? u.href : ''; } catch { return ''; } };
  const link = (url, label = '官方来源 ↗') => href(url) ? `<a href="${esc(href(url))}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>` : '';
  const time = (value) => value ? esc(value.replace('T', ' ').replace('Z', ' UTC')) : '未核验';
  const family = (value) => value === 'tff' ? '金融期货分类报告' : '商品分类报告';

  function status(block, name, observation) {
    const age = observation ? (Date.now() - Date.parse(`${observation}T00:00:00Z`)) / 86400000 : Infinity;
    const good = block.status === 'ok' && age <= 13;
    const text = good ? '已核验周报' : observation ? '保留旧值 / 部分数据缺失' : '暂不可用';
    return `<div class="source-status ${good ? '' : 'warning'}"><strong>${esc(name)} · ${text}</strong><span>观测截至 ${esc(observation || '未知')}</span><small>上次成功读取 ${time(block.fetched_at)}<br>最近检查 ${time(block.checked_at)}</small>${block.error ? `<details><summary>查看来源提示</summary><p>${esc(block.error)}</p></details>` : ''}</div>`;
  }

  function renderCftc() {
    const boards = state.data.cftc?.boards || [];
    const order = ['metals', 'financial', 'energy', 'agriculture', 'agri'];
    const sorted = [...boards].sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));
    if (!sorted.some(b => b.id === state.sector)) state.sector = sorted[0]?.id;
    $('#sectorTabs').innerHTML = sorted.map(b => `<button type="button" class="tab" role="tab" aria-selected="${b.id === state.sector}" data-sector="${esc(b.id)}">${esc(labels[b.id] || b.name)}</button>`).join('');
    $('#sectorTabs').querySelectorAll('button').forEach(button => {
      button.onclick = () => { state.sector = button.dataset.sector; state.selected = null; renderCftc(); $('#sectorTabs').querySelector('[aria-selected="true"]')?.focus({ preventScroll: true }); };
    });
    const board = sorted.find(b => b.id === state.sector);
    const products = [...(board?.products || [])].sort((a, b) => (b.net_oi_pct ?? -Infinity) - (a.net_oi_pct ?? -Infinity));
    if (!products.length) {
      $('#boardList').innerHTML = '<p class="empty">没有已核验品种；缺失不等于持仓为零。</p>';
      $('#productDetail').innerHTML = '<h2>持仓明细待更新</h2>';
      return;
    }
    const max = Math.max(1, ...products.filter(p => valid(p.net_oi_pct)).map(p => Math.abs(p.net_oi_pct)));
    $('#boardList').innerHTML = `<p class="method">观察群体：<strong>${esc(board.cohort || products[0].cohort)}</strong> · 期货＋期权合并 · 比率周变化使用“百分点”，并非资金流量。</p><div class="chart-axis"><span>−${number(max, 1)}%</span><span>0</span><span>+${number(max, 1)}%</span></div>` + products.map(p => {
      const known = valid(p.net_oi_pct), width = known ? Math.abs(p.net_oi_pct) / max * 50 : 0;
      return `<button type="button" class="board-row" data-product="${esc(p.id)}" aria-pressed="${state.selected === p.id}"><span class="instrument">${esc(p.name)}<span class="sub">${esc(p.cohort)} · 净 ${signed(p.net)} 张</span></span><span class="bar-wrap">${known ? `<span class="bar ${p.net_oi_pct >= 0 ? 'positive' : 'negative'}" style="width:${width}%" title="${esc(p.name)} 净持仓/OI ${number(p.net_oi_pct, 2)}%"></span>` : '<span class="unknown">未知</span>'}</span><span class="bar-value">${known ? signed(p.net_oi_pct, 2) + '%' : '未知'}<span class="sub">${signed(p.net_oi_change_pp, 2)} 个百分点 / 周</span></span></button>`;
    }).join('');
    const current = products.find(p => p.id === state.selected) || products.find(p => p.id === 'gold') || products[0];
    choose(current);
    $('#boardList').querySelectorAll('[data-product]').forEach(button => { button.onclick = () => choose(products.find(p => p.id === button.dataset.product)); });
  }

  function choose(product) {
    state.selected = product.id;
    $('#boardList').querySelectorAll('[data-product]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.product === product.id)));
    const cats = product.categories || [];
    const max = Math.max(1, ...cats.flatMap(c => [c.long, c.short]).filter(valid));
    const bar = (value, css) => valid(value) ? `<span class="cat-bar ${css}" style="height:${value / max * 100}px" title="${number(value)} 张"></span>` : '<span class="unknown">未知</span>';
    $('#productDetail').innerHTML = `<div class="section-head"><div><p class="kicker">${esc(family(product.report_family))} · ${esc(product.cohort)}</p><h2>${esc(product.name)}</h2></div><p class="hint">观测日 ${esc(product.report_date)} · 单位：张</p></div><p class="method">${esc(product.market_name)} · ${link(product.source_url)}<br>市场未平仓量 ${number(product.open_interest)} 张（周变 ${signed(product.oi_change)}）；观察群体净头寸 ${signed(product.net)} 张（周变 ${signed(product.net_change)}）。</p><p class="analysis-note">${esc(product.interpretation)}</p><div class="legend"><span><i class="long"></i>多头合约</span><span><i class="short"></i>空头合约</span><span>五组使用相同纵轴：0—${number(max)} 张</span></div><div class="detail-bars">${cats.map(c => `<article class="category"><h3 class="category-name">${esc(c.name)}</h3><div class="cat-bars">${bar(c.long, 'l')}${bar(c.short, 's')}</div><div class="cat-label"><span>多 ${number(c.long)}</span><span>空 ${number(c.short)}</span></div></article>`).join('')}</div><div class="table-scroll"><table class="data-table"><caption>当前持仓与本周变化，单位：张</caption><thead><tr><th>参与者</th><th>多头</th><th>空头</th><th>净持仓</th><th>净持仓周变</th></tr></thead><tbody>${cats.map(c => `<tr><th scope="row">${esc(c.name)}</th><td>${number(c.long)}</td><td>${number(c.short)}</td><td>${signed(c.net)}</td><td>${signed(c.net_change)}</td></tr>`).join('')}</tbody></table></div><p class="method">管理资金与杠杆基金属于不同分类体系；非报告持仓不等于“散户”。分类依据交易者主要业务，不揭示每笔交易动机；净持仓变化不是美元资金流。</p>`;
  }

  function renderEia() {
    const eia = state.data.eia || {}, metrics = eia.metrics || [];
    const stockIds = ['commercial_crude', 'spr', 'cushing', 'gasoline', 'distillate'];
    const stock = stockIds.map(id => metrics.find(m => m.id === id)).filter(Boolean);
    const max = Math.max(.001, ...stock.map(m => m.change).filter(valid).map(Math.abs));
    $('#eiaDate').textContent = `观测周末 ${eia.week_ending || '未知'} · 发布 ${eia.published_at || '未核验'}${eia.next_release_at ? ' · 下次发布 ' + eia.next_release_at : ''}`;
    $('#inventoryList').innerHTML = stock.length ? stock.map(m => {
      const known = valid(m.change), height = known ? Math.abs(m.change) / max * 50 : 0;
      return `<article class="inventory-card" data-metric="${esc(m.id)}"><h3>${esc(m.label)}</h3><div class="inv-bar" title="统一纵轴 ±${number(max, 3)} 百万桶；上增库、下去库"><small class="zero-label">0</small>${known ? `<span class="inv-fill ${m.change >= 0 ? 'up' : 'down'}" style="height:${height}%" title="周变化 ${signed(m.change, 3)} 百万桶"></span>` : '<span class="unknown">未知</span>'}</div><div class="inv-value">${signed(m.change, 3)}</div><span class="unit">百万桶 / 周 · ${known ? m.change > 0 ? '增库' : m.change < 0 ? '去库' : '不变' : '缺失'}</span><p class="change">库存 ${number(m.value, 3)} 百万桶<br>上周 ${number(m.previous, 3)} 百万桶<br>${link(m.source_url, 'EIA 数据 ↗')}</p></article>`;
    }).join('') : '<p class="empty">库存数据暂不可用，未生成推断。</p>';
    const flows = metrics.filter(m => !stockIds.includes(m.id));
    $('#balanceCards').innerHTML = flows.map(m => `<article class="balance-card"><h3>${esc(m.label)}</h3><strong>${number(m.value, m.unit === '%' ? 1 : 3)}</strong> <span class="unit">${esc(m.unit)}</span><div class="change">周变 ${signed(m.change, m.unit === '%' ? 1 : 3)} ${m.unit === '%' ? '个百分点' : esc(m.unit)}<br>${link(m.source_url)}</div></article>`).join('');
    const find = (id) => metrics.find(m => m.id === id);
    const crude = find('commercial_crude'), cushing = find('cushing'), exports = find('exports'), runs = find('runs');
    const notes = [];
    if (valid(crude?.change)) notes.push(`事实：商业原油库存${crude.change < 0 ? '减少' : crude.change > 0 ? '增加' : '不变'} ${number(Math.abs(crude.change), 3)} 百万桶。`);
    if (valid(crude?.change) && valid(cushing?.change) && crude.change * cushing.change < 0) notes.push('推断：商业库存与库欣变动方向相反，地区供需并非一致，不能只看总库存下结论。');
    if (valid(exports?.change) && valid(runs?.change)) notes.push(`核对：原油出口周变 ${signed(exports.change, 3)} 百万桶/日，炼厂加工量周变 ${signed(runs.change, 3)} 百万桶/日；这两项会影响库存，但不足以独立证明最终需求增强。`);
    notes.push(...(eia.notes || []));
    notes.push('分析边界：库欣是商业库存子集，不能重复相加；SPR 分列。单周去库不等于油价必涨，需看连续性、成品油需求和供给变化。');
    $('#eiaNotes').innerHTML = notes.map(note => `<p>${esc(note)}</p>`).join('');
  }

  function render(data) {
    state.data = data || {};
    const cftc = state.data.cftc || {}, eia = state.data.eia || {};
    $('#statusLine').innerHTML = status(cftc, 'CFTC', cftc.report_date) + status(eia, 'EIA', eia.week_ending);
    renderCftc(); renderEia();
    if (href(cftc.source_url)) $('#cftcSource').href = href(cftc.source_url);
    if (href(eia.source_url)) $('#eiaSource').href = href(eia.source_url);
  }
  async function load() {
    try {
      const response = await fetch('../data/research.json', { cache: 'no-store' });
      if (!response.ok) throw Error(`数据文件返回 ${response.status}`);
      render(await response.json());
    } catch (error) {
      if (!state.data.cftc) render({});
      $('#statusLine').insertAdjacentHTML('beforeend', `<p class="warning">读取失败：${esc(error.message)}。可稍后重新载入；已有数值如仍显示，不代表本次更新成功。</p>`);
    }
  }
  window.PositioningResearch = { render, load };
  $('#themeToggle').onclick = () => { document.documentElement.dataset.theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'; };
  load();
  setInterval(() => { if (!document.hidden) load(); }, 15 * 60 * 1000);
})();
