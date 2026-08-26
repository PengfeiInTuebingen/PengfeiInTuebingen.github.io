(() => {
  const loaderScript = document.currentScript;
  const mount = document.getElementById("dynamic-market-dashboard");
  if (!mount) return;

  const rawEndpoint = "https://raw.githubusercontent.com/PengfeiInTuebingen/PengfeiInTuebingen.github.io/gh-pages/markets/data/latest.json";
  const relativeEndpoint = loaderScript?.dataset.dataUrl || "./data/latest.json";
  const production = location.hostname === "pengfeiintuebingen.github.io";
  let currentData = null;

  const escapeHtml = (value) => String(value).replace(/[&<>"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;"
  })[char]);

  const finite = (value) => Number.isFinite(Number(value));
  const signed = (value, digits = 2, suffix = "") => {
    if (!finite(value)) return "待更新";
    const number = Number(value);
    return `${number > 0 ? "+" : ""}${number.toFixed(digits)}${suffix}`;
  };

  const formatDate = (value) => {
    if (!value) return "未知时点";
    const date = new Date(`${value}T00:00:00Z`);
    return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", {month: "short", day: "numeric", timeZone: "UTC"}).format(date);
  };

  const formatGenerated = (value) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "未知";
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
      hour12: false, timeZone: "Europe/Berlin", timeZoneName: "short"
    }).format(date);
  };

  const ageHours = (value) => Math.max(0, (Date.now() - new Date(value).getTime()) / 3600000);

  const formatCompact = (value, digits = 2) => {
    if (!finite(value)) return "待更新";
    return Number(value).toLocaleString("zh-CN", {minimumFractionDigits: digits, maximumFractionDigits: digits});
  };

  const sparkline = (history, color) => {
    const points = (history || []).filter((item) => finite(item[1])).slice(-45);
    if (points.length < 2) return "";
    const width = 180;
    const height = 42;
    const values = points.map((item) => Number(item[1]));
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;
    const coordinates = values.map((value, index) => {
      const x = (index / (values.length - 1)) * width;
      const y = height - 3 - ((value - min) / range) * (height - 6);
      return [x.toFixed(1), y.toFixed(1)];
    });
    const line = coordinates.map((item) => item.join(",")).join(" ");
    const area = `M ${coordinates[0][0]} ${height} L ${coordinates.map((item) => item.join(" ")).join(" L ")} L ${coordinates.at(-1)[0]} ${height} Z`;
    return `<svg class="dm-sparkline" style="--dm-color:${color}" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true"><path class="area" d="${area}"></path><polyline class="line" points="${line}"></polyline></svg>`;
  };

  const getSeries = (data, key) => data.series?.[key] || null;
  const getDerived = (data, key) => data.derived?.[key] || null;

  const cards = [
    {label: "美联储总资产", key: "WALCL", color: "#276aa1", value: (s) => `${formatCompact(s.value / 1_000_000, 3)}T`, change: (d) => signed(getDerived(d, "WALCL_WEEKLY_B")?.value, 1, "B / 周")},
    {label: "美债 10Y", key: "DGS10", color: "#7565cf", value: (s) => `${formatCompact(s.value, 3)}%`, change: (d, s) => signed((s.value - s.previous) * 100, 1, "bp")},
    {label: "10Y 实际利率", key: "DFII10", color: "#c64752", value: (s) => `${formatCompact(s.value, 2)}%`, change: (d, s) => signed((s.value - s.previous) * 100, 1, "bp")},
    {label: "10Y 盈亏平衡", key: "T10YIE", color: "#b97c1f", value: (s) => `${formatCompact(s.value, 2)}%`, change: (d, s) => signed((s.value - s.previous) * 100, 1, "bp")},
    {label: "VIX", key: "VIXCLS", color: "#b84d82", value: (s) => formatCompact(s.value, 2), change: (d, s) => signed((s.value / s.previous - 1) * 100, 2, "%")},
    {label: "高收益债 OAS", key: "BAMLH0A0HYM2", color: "#168c78", value: (s) => `${formatCompact(s.value, 2)}%`, change: (d, s) => signed((s.value - s.previous) * 100, 1, "bp")},
    {label: "美国 GDP", key: "A191RL1Q225SBEA", color: "#276aa1", value: (s) => `${formatCompact(s.value, 1)}%`, change: () => "环比年化"},
    {label: "核心 PCE 同比", key: "PCEPILFE", derived: "CORE_PCE_YOY", color: "#c64752", value: (s, d) => `${formatCompact(getDerived(d, "CORE_PCE_YOY")?.value, 2)}%`, change: () => "政策核心通胀"},
    {label: "USD/JPY", key: "FX_USDJPY", color: "#b97c1f", value: (s) => formatCompact(s.value, 2), change: (d) => signed(getDerived(d, "USDJPY_DAILY")?.value, 2, "%")},
    {label: "标普 500", key: "SP500", color: "#168c78", value: (s) => formatCompact(s.value, 2), change: (d) => signed(getDerived(d, "SP500_DAILY")?.value, 2, "%")},
  ];

  const loadingMarkup = () => `
    <section class="dm-section" id="dynamic-data">
      <div class="container">
        <div class="section-head"><div><div class="section-kicker">Dynamic data · Zero-token pipeline</div><h2>低成本动态数据脉冲</h2></div><p class="section-note">正在读取官方数据快照…</p></div>
        <div class="dm-grid dm-loading-grid">${Array.from({length: 10}, () => `<div class="dm-card"><div class="dm-skeleton label"></div><div class="dm-skeleton value"></div><div class="dm-skeleton chart"></div></div>`).join("")}</div>
      </div>
    </section>`;

  const statusTone = (data) => {
    if (data.pipeline?.success_count === 0) return "error";
    if (data.pipeline?.error_count > 0 || ageHours(data.generated_at) > 36) return "stale";
    return "";
  };

  const render = (data) => {
    const pipeline = data.pipeline || {};
    const tone = statusTone(data);
    const statusText = tone === "" ? "数据管道运行正常" : tone === "stale" ? "部分来源降级或数据偏旧" : "动态数据暂不可用";
    const cardMarkup = cards.map((card) => {
      const series = getSeries(data, card.key);
      if (!series) return "";
      const rawChange = card.change(data, series);
      const changeValue = parseFloat(rawChange);
      const changeClass = Number.isNaN(changeValue) ? "" : changeValue > 0 ? "positive" : changeValue < 0 ? "negative" : "";
      return `<article class="dm-card" style="--dm-color:${card.color}">
        <div class="dm-card-head"><span class="dm-card-label">${escapeHtml(card.label)}</span><span class="dm-source">${escapeHtml(series.source)}</span></div>
        <div class="dm-card-value">${card.value(series, data)}</div>
        <div class="dm-card-change ${changeClass}">${rawChange}</div>
        ${sparkline(series.history, card.color)}
        <div class="dm-card-foot"><span>${formatDate(series.date)}</span><span>${escapeHtml(series.id)}</span></div>
      </article>`;
    }).join("");
    const errorNote = pipeline.error_count > 0
      ? `<div class="dm-notice warning"><span>△</span><div><strong>${pipeline.error_count} 个来源使用降级处理。</strong> 页面保留最近一次有效值，不以空值覆盖；详细错误记录在数据 JSON 中。</div></div>`
      : `<div class="dm-notice"><span>ⓘ</span><div><strong>本模块不调用 AI，单次更新消耗 0 token。</strong> 黄金和白银现货仍保留报告快照；宏观、利率、风险、USD/JPY 与 CFTC 已自动化。</div></div>`;
    mount.innerHTML = `<section class="dm-section" id="dynamic-data"><div class="container">
      <div class="section-head"><div><div class="section-kicker">Dynamic data · Zero-token pipeline</div><h2>低成本动态数据脉冲</h2></div><p class="section-note">网页从 GitHub 数据快照读取；官方源更新后由定时任务重建，不需要 AI 重写整页。</p></div>
      <div class="dm-status-panel">
        <div class="dm-status-main"><span class="dm-status-light ${tone}"></span><div><strong>${statusText}</strong><span>生成于 ${formatGenerated(data.generated_at)} · 快照 ${escapeHtml(data.snapshot_id || "—")}</span></div></div>
        <div class="dm-status-stat"><span>成功数据源</span><strong>${pipeline.success_count || 0} / ${pipeline.source_count || 0}</strong></div>
        <div class="dm-status-stat"><span>CFTC 自动映射</span><strong>${data.cftc?.dynamic_count || 0} / ${data.cftc?.target_count || 10}</strong></div>
        <div class="dm-status-stat"><span>AI token</span><strong>${pipeline.ai_tokens_used || 0}</strong></div>
        <button class="dm-refresh" id="dmRefresh" type="button">重新读取</button>
      </div>
      ${errorNote}<div class="dm-grid">${cardMarkup}</div>
    </div></section>`;
    document.getElementById("dmRefresh")?.addEventListener("click", () => loadData(true));
  };

  const setQuote = (needle, value, changeText, changeValue, note) => {
    const card = [...document.querySelectorAll(".quote-card")].find((item) => item.querySelector(".quote-label")?.textContent.includes(needle));
    if (!card || (typeof value !== "string" && !finite(value))) return;
    card.querySelector(".quote-value").textContent = typeof value === "number" ? formatCompact(value, needle.includes("美债") ? 3 : 2) : value;
    const changeElement = card.querySelector(".change");
    if (changeElement && changeText) {
      changeElement.textContent = changeText;
      changeElement.className = `change ${Number(changeValue) >= 0 ? "positive" : "negative"}`;
    }
    card.querySelector(".quote-note").textContent = note;
    const label = card.querySelector(".quote-label");
    if (label && !label.querySelector(".dm-live-badge")) label.insertAdjacentHTML("beforeend", `<span class="dm-live-badge">AUTO</span>`);
    card.classList.add("dm-updated");
  };

  const patchQuotes = (data) => {
    const usdjpy = getSeries(data, "FX_USDJPY");
    const dgs10 = getSeries(data, "DGS10");
    const dgs30 = getSeries(data, "DGS30");
    const vix = getSeries(data, "VIXCLS");
    const spx = getSeries(data, "SP500");
    const ndx = getSeries(data, "NASDAQCOM");
    if (usdjpy) setQuote("USD/JPY", usdjpy.value, signed(getDerived(data, "USDJPY_DAILY")?.value, 2, "%"), getDerived(data, "USDJPY_DAILY")?.value, `ECB 参考汇率 · ${usdjpy.date}`);
    if (dgs10) setQuote("美债 10 年", `${formatCompact(dgs10.value, 3)}%`, signed((dgs10.value - dgs10.previous) * 100, 1, "bp"), dgs10.value - dgs10.previous, `FRED DGS10 · ${dgs10.date}`);
    if (dgs30) setQuote("美债 30 年", `${formatCompact(dgs30.value, 3)}%`, signed((dgs30.value - dgs30.previous) * 100, 1, "bp"), dgs30.value - dgs30.previous, `FRED DGS30 · ${dgs30.date}`);
    if (vix) setQuote("VIX", vix.value, signed((vix.value / vix.previous - 1) * 100, 2, "%"), vix.value - vix.previous, `FRED VIXCLS · ${vix.date}`);
    if (spx && ndx) {
      const combined = `${formatCompact(spx.value, 0)} / ${formatCompact(ndx.value, 0)}`;
      const changes = `${signed(getDerived(data, "SP500_DAILY")?.value, 2, "")} / ${signed(getDerived(data, "NASDAQ_DAILY")?.value, 2, "%")}`;
      setQuote("SPX / NDX", combined, changes, getDerived(data, "SP500_DAILY")?.value, `FRED 日线 · ${spx.date}`);
    }
  };

  const patchLayers = (data) => {
    Object.entries(data.layers || {}).forEach(([code, layer]) => {
      const card = [...document.querySelectorAll(".dp-layer-card")].find((item) => item.querySelector(".dp-layer-code")?.textContent.trim() === code);
      if (!card) return;
      Object.entries(layer.metrics || {}).forEach(([name, value]) => {
        const metric = [...card.querySelectorAll(".dp-metric")].find((item) => item.querySelector("span")?.textContent.trim() === name);
        if (metric) metric.querySelector("strong").textContent = value;
      });
      const title = card.querySelector(".dp-layer-title");
      if (layer.automated && title && !title.querySelector(".dm-live-badge")) title.insertAdjacentHTML("beforeend", `<span class="dm-live-badge">AUTO</span>`);
      if (layer.automated) {
        card.classList.add("dm-updated");
        const asof = card.querySelector(".dp-asof");
        if (asof) asof.textContent = `自动更新 · 数据包生成 ${formatGenerated(data.generated_at)}`;
      }
    });
  };

  const contractsText = (value) => `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toLocaleString("zh-CN")} 张`;

  const patchCftc = (data) => {
    const positions = data.cftc?.positions || [];
    const byName = new Map(positions.map((item) => [item.name, item]));
    document.querySelectorAll(".dp-bar-row").forEach((row) => {
      const label = row.querySelector(".dp-bar-label");
      const name = label?.firstChild?.nodeValue?.trim();
      const item = byName.get(name);
      if (!item) return;
      label.innerHTML = `${escapeHtml(item.name)} <small>(${signed(item.weekly_ratio_change, 2)})</small>`;
      const bar = row.querySelector(".dp-bar");
      bar.className = `dp-bar ${item.ratio >= 0 ? "positive" : "negative"}`;
      bar.style.setProperty("--dp-width", `${Math.min(50, Math.abs(item.ratio) * 1.55)}%`);
      row.querySelector(".dp-bar-value").textContent = signed(item.ratio, 2, "%");
      row.title = `${item.name}：净持仓/OI ${signed(item.ratio, 2, "%")}，周变动 ${signed(item.weekly_ratio_change, 2, "pct")}`;
      row.classList.add("dm-updated");
    });
    const longList = document.querySelector(".dp-position-block:not(.short) .dp-position-list");
    const shortList = document.querySelector(".dp-position-block.short .dp-position-list");
    document.querySelectorAll(".dp-position-row").forEach((row) => {
      const name = row.querySelector("span")?.textContent.trim();
      const item = byName.get(name);
      if (!item) return;
      row.className = `dp-position-row ${item.contracts >= 0 ? "long" : "short"}`;
      row.querySelector("strong").textContent = contractsText(item.contracts);
      (item.contracts >= 0 ? longList : shortList)?.appendChild(row);
    });
    const long = positions.filter((item) => item.contracts > 0).sort((a, b) => b.contracts - a.contracts)[0];
    const short = positions.filter((item) => item.contracts < 0).sort((a, b) => a.contracts - b.contracts)[0];
    const summaries = document.querySelectorAll("#cftc-cross-asset .dp-summary-card strong");
    if (summaries[0] && long) summaries[0].textContent = `${long.name} ${contractsText(long.contracts)}`;
    if (summaries[1] && short) summaries[1].textContent = `${short.name} ${contractsText(short.contracts)}`;
    if (summaries[2]) summaries[2].textContent = `报告日 ${data.cftc?.report_date || "待更新"}`;
    const note = document.querySelector("#cftc-cross-asset .section-note");
    if (note) note.textContent = `${positions.length} 类资产已由 CFTC 官方合并持仓文件自动更新；其余小众合约继续保留截图快照。`;
  };

  const patchLibrary = (data) => {
    const seriesIds = new Set(Object.keys(data.series || {}));
    const cftcNames = new Set((data.cftc?.positions || []).map((item) => item.name));
    document.querySelectorAll(".dp-data-row").forEach((row) => {
      const source = row.querySelector(".dp-source-code")?.textContent || "";
      const name = row.querySelector("td strong")?.textContent || "";
      const sourceMatch = [...seriesIds].some((id) => source.includes(id));
      const cftcMatch = name.startsWith("CFTC") && [...cftcNames].some((item) => name.includes(item));
      if (!sourceMatch && !cftcMatch) return;
      const status = row.querySelector(".dp-status");
      if (status) {
        status.className = "dp-status connected";
        status.textContent = "自动更新";
      }
    });
  };

  const patchPage = (data) => {
    patchQuotes(data);
    patchLayers(data);
    patchCftc(data);
    patchLibrary(data);
    const meta = document.querySelector(".hero .meta-row");
    if (meta && !meta.querySelector("[data-dynamic-meta]")) meta.insertAdjacentHTML("beforeend", `<span class="pill" data-dynamic-meta><span class="dot"></span>动态数据 ${formatGenerated(data.generated_at)} · 0 token</span>`);
    window.marketDashboardData = data;
  };

  const endpoints = (force) => {
    const bucket = force ? Date.now() : Math.floor(Date.now() / 300000);
    const cacheKey = `v=${bucket}`;
    const relative = `${relativeEndpoint}${relativeEndpoint.includes("?") ? "&" : "?"}${cacheKey}`;
    return production ? [`${rawEndpoint}?${cacheKey}`, relative] : [relative, `${rawEndpoint}?${cacheKey}`];
  };

  const fetchFirst = async (urls) => {
    const errors = [];
    for (const url of urls) {
      try {
        const response = await fetch(url, {cache: "no-store"});
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
        const data = await response.json();
        if (data.schema_version !== 1 || !data.series) throw new Error("invalid schema");
        return data;
      } catch (error) {
        errors.push(`${url}: ${error.message}`);
      }
    }
    throw new Error(errors.join(" | "));
  };

  const loadData = async (force = false) => {
    const button = document.getElementById("dmRefresh");
    if (button) { button.disabled = true; button.textContent = "读取中…"; }
    try {
      const data = await fetchFirst(endpoints(force));
      currentData = data;
      render(data);
      patchPage(data);
    } catch (error) {
      if (currentData) {
        render(currentData);
      } else {
        mount.innerHTML = `<section class="dm-section" id="dynamic-data"><div class="container"><div class="section-head"><div><div class="section-kicker">Dynamic data</div><h2>低成本动态数据脉冲</h2></div></div><div class="dm-error-box"><strong>动态数据暂时无法读取。</strong><br>原有静态简报仍可正常使用；下次打开页面会自动重试。<br><small>${escapeHtml(error.message)}</small></div></div></section>`;
      }
    }
  };

  mount.innerHTML = loadingMarkup();
  loadData();
})();
