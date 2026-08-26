(() => {
  const script = document.currentScript;
  const mount = document.getElementById("a-share-dashboard");
  if (!mount) return;

  const relativeEndpoint = script?.dataset.dataUrl || "../data/a_share.json";
  const rawEndpoint = "https://raw.githubusercontent.com/PengfeiInTuebingen/PengfeiInTuebingen.github.io/gh-pages/markets/data/a_share.json";
  const production = location.hostname === "pengfeiintuebingen.github.io";

  const escapeHtml = (value) => String(value ?? "").replace(/[&<>\"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;"
  })[char]);
  const finite = (value) => Number.isFinite(Number(value));
  const compact = (value, digits = 2) => finite(value) ? Number(value).toLocaleString("zh-CN", {minimumFractionDigits: digits, maximumFractionDigits: digits}) : "—";
  const money = (value) => finite(value) ? `${Number(value) > 0 ? "+" : ""}${compact(value, 1)}亿` : "—";
  const pct = (value) => finite(value) ? `${Number(value) > 0 ? "+" : ""}${compact(value, 2)}%` : "—";
  const flowTone = (value) => finite(value) ? (Number(value) >= 0 ? "positive" : "negative") : "";
  const checkedText = (value) => {
    if (!value) return "未注明";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat("zh-CN", {month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Shanghai"}).format(date);
  };
  const statusMap = {
    CONTINUOUS_GREEN: ["连续流入", "positive"],
    PROVISIONAL_GREEN: ["观察绿灯", "provisional"],
    ONE_DAY_SPIKE: ["单日异动", "warning"],
    REBOUND_ONLY: ["反抽", "warning"],
    RED: ["连续流出", "negative"],
    RED_STRONG: ["持续撤退", "negative"],
    UNKNOWN: ["UNKNOWN", "unknown"],
  };

  const render = (snapshot) => {
    const status = (code) => statusMap[code] || [code || "UNKNOWN", "unknown"];
    const indexRows = (snapshot.index_flows || []).map((item) => `<div class="a-index"><div><span>${escapeHtml(item.name)}</span><small>${finite(item.price) ? `点位 ${compact(item.price, 2)} · ${pct(item.change_pct)}` : "行情待更新"}</small></div><div><strong class="${flowTone(item.main_net_flow_billion_cny)}">${money(item.main_net_flow_billion_cny)}</strong><small>${finite(item.turnover_billion_cny) ? `成交 ${compact(item.turnover_billion_cny, 1)}亿` : "成交额待更新"}</small></div></div>`).join("");
    const sectorRows = (snapshot.sectors || []).map((item) => {
      const [label, tone] = status(item.continuity);
      return `<tr class="${tone === "unknown" ? "is-unknown" : ""}"><td><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.label || "")}</small></td><td class="${flowTone(item.today_billion_cny)}">${money(item.today_billion_cny)}</td><td class="${flowTone(item.five_day_billion_cny)}">${money(item.five_day_billion_cny)}</td><td>${finite(item.market_cap_trillion_cny) ? `${compact(item.market_cap_trillion_cny, 2)}万亿` : "—"}</td><td>${pct(item.today_to_cap_pct)}</td><td>${pct(item.five_day_to_cap_pct)}</td><td><span class="status ${tone}">${escapeHtml(label)}</span></td></tr>`;
    }).join("");
    const conclusionCards = (snapshot.conclusions || []).map((item, index) => `<article class="conclusion ${escapeHtml(item.tone || "neutral")}"><span>结论 ${index + 1}</span><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.body)}</p></article>`).join("");
    const watchRows = (snapshot.watchlist || []).map((item) => {
      const [label, tone] = status(item.status);
      return `<tr><td><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.sector || "")}</small></td><td><span class="status ${tone}">${escapeHtml(label)}</span><small>${escapeHtml(item.actionability || "")}</small></td><td>${escapeHtml(item.reason || "")}</td><td>${escapeHtml(item.missing || "")}</td></tr>`;
    }).join("");
    const framework = (snapshot.framework || []).map((item, index) => `<span><b>${index + 1}</b>${escapeHtml(item)}</span>`).join("");
    const statusLabel = snapshot.data_status === "LIVE" ? "自动抓取" : snapshot.data_status === "PARTIAL" ? "自动抓取 · 部分回退" : "回退快照";
    const freshness = snapshot.freshness || {};
    const errorNote = Number(freshness.error_count || (snapshot.errors || []).length) > 0 ? ` · ${Number(freshness.error_count || (snapshot.errors || []).length)} 个源请求待重试` : "";
    mount.innerHTML = `<section class="a-share-section" id="a-share-analysis"><div class="container"><div class="a-share-panel">
      <div class="a-subhead"><div><span>A-share flow &amp; price-volume rules · V0.3</span><h2>A股资金流与量价观察</h2></div><time>数据截至 ${escapeHtml(snapshot.snapshot_date)} · 更新 ${escapeHtml(checkedText(snapshot.checked_at))}</time></div>
      <div class="a-source-note"><strong>${statusLabel} · ${escapeHtml(snapshot.observation_finality || "未注明")}</strong><span>${escapeHtml((snapshot.source_note || "") + errorNote)}</span></div>
      <div class="a-kpis"><div><span>沪深成交额</span><strong>${finite(snapshot.market?.turnover_trillion_cny) ? `${compact(snapshot.market.turnover_trillion_cny, 2)}万亿` : "—"}</strong></div><div><span>四指数主力净额合计</span><strong class="positive">${money(snapshot.market?.main_net_flow_billion_cny)}</strong></div><div><span>结构判定</span><strong>${escapeHtml(snapshot.market?.structure_label || "待判定")}</strong></div></div>
      <div class="a-index-grid">${indexRows}</div>
      <div class="a-subhead"><div><span>Today × 5-day × market-cap ratio</span><h3>板块三维资金表</h3></div><small>单位：净额 = 亿元；市值 = 万亿元</small></div>
      <div class="table-wrap"><table class="a-table"><thead><tr><th>板块</th><th>今日净额</th><th>5日净额</th><th>市值</th><th>今日/市值</th><th>5日/市值</th><th>连续性</th></tr></thead><tbody>${sectorRows}</tbody></table></div>
      <div class="conclusion-grid">${conclusionCards}</div>
      <div class="a-subhead" id="watchlist"><div><span>Watchlist gates · no auto-trading</span><h3>个股接回卡</h3></div><small>UNKNOWN 不等于 0；需个股 OHLCV 与确认/证伪位</small></div>
      <div class="table-wrap"><table class="a-table"><thead><tr><th>标的</th><th>状态 / 权限</th><th>规则读法</th><th>缺失证据</th></tr></thead><tbody>${watchRows}</tbody></table></div>
      <div class="framework"><strong>分析链</strong>${framework}</div>
      <p class="rules-note">规则边界：资金流是价格结构的置信度修正项，不单独生成方向；板块连续流入但广度或主动流向分裂时，分裂状态优先。页面由定时任务自动读取公开行情；源暂时不可用时保留最近有效值并标注回退，UNKNOWN 不触发交易动作。</p>
    </div></div></section>`;
    const source = document.querySelector("[data-a-source]");
    if (source) source.textContent = `数据源：${snapshot.source || "未注明"} · ${snapshot.snapshot_date} · ${statusLabel} · 更新 ${checkedText(snapshot.checked_at)}`;
  };

  const endpointList = () => {
    const key = `v=${Math.floor(Date.now() / 300000)}`;
    const local = `${relativeEndpoint}${relativeEndpoint.includes("?") ? "&" : "?"}${key}`;
    return production ? [`${rawEndpoint}?${key}`, local] : [local, `${rawEndpoint}?${key}`];
  };

  const load = async () => {
    for (const url of endpointList()) {
      try {
        const response = await fetch(url, {cache: "no-store"});
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
        const data = await response.json();
        if (data.schema_version !== 1 || data.data_type !== "a_share_snapshot") throw new Error("invalid A-share snapshot");
        render(data);
        return;
      } catch (error) {
        // Try the next source; the error is shown only if both sources fail.
      }
    }
    mount.innerHTML = `<section class="a-share-section"><div class="container"><div class="error"><strong>A股快照暂时无法读取。</strong><br>请稍后刷新页面。</div></div></section>`;
  };

  load();
})();
