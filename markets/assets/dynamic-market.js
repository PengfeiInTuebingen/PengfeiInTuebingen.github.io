(() => {
  const loaderScript = document.currentScript;
  const mount = document.getElementById("dynamic-market-dashboard");
  if (!mount) return;

  const rawEndpoint = "https://raw.githubusercontent.com/PengfeiInTuebingen/PengfeiInTuebingen.github.io/gh-pages/markets/data/latest.json";
  const apiEndpoint = "https://api.github.com/repos/PengfeiInTuebingen/PengfeiInTuebingen.github.io/contents/markets/data/latest.json?ref=gh-pages";
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
    const date = new Date(value.includes("T") ? value : `${value}T00:00:00Z`);
    if (Number.isNaN(date.getTime())) return value;
    const options = value.includes("T")
      ? {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Europe/Berlin"}
      : {month: "short", day: "numeric", timeZone: "UTC"};
    return new Intl.DateTimeFormat("zh-CN", options).format(date);
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

  const dayKey = (value) => {
    const date = new Date(String(value).includes("T") ? value : `${value}T00:00:00Z`);
    return Number.isNaN(date.getTime()) ? "" : new Intl.DateTimeFormat("en-CA", {timeZone: "Europe/Berlin", year: "numeric", month: "2-digit", day: "2-digit"}).format(date);
  };

  const normalizePoints = (history) => (history || []).map((item) => ({stamp: item[0], value: Number(item[1])})).filter((item) => item.stamp && Number.isFinite(item.value));

  const trendPoints = (history, mode) => {
    const points = normalizePoints(history);
    if (mode === "today" && points.length) {
      const latestDay = dayKey(points.at(-1).stamp);
      const sameDay = points.filter((point) => dayKey(point.stamp) === latestDay);
      return sameDay;
    }
    return points.slice(-32);
  };

  const normalizeCandles = (history) => (history || []).map((item) => ({
    stamp: item.time || item.stamp,
    open: Number(item.open), high: Number(item.high), low: Number(item.low), close: Number(item.close), volume: Number(item.volume_usd ?? item.volume),
  })).filter((item) => item.stamp && [item.open, item.high, item.low, item.close].every(Number.isFinite));

  const candleWindow = (history, mode) => {
    const points = normalizeCandles(history);
    if (mode === "today" && points.length) {
      const latestDay = dayKey(points.at(-1).stamp);
      return points.filter((point) => dayKey(point.stamp) === latestDay);
    }
    return points.slice(-32);
  };

  const buildTrendInstruments = (data) => {
    const cryptoAssets = data.flow_positioning?.crypto?.assets || {};
    const spotAssets = data.flow_positioning?.crypto?.spot_assets || {};
    const instruments = [];
    for (const symbol of ["BTC", "ETH"]) {
      const spot = spotAssets[symbol];
      const futures = cryptoAssets[symbol];
      const source = spot || futures;
      if (!source) continue;
      const ohlcv = spot?.ohlcv_history?.length >= 2 ? spot.ohlcv_history : (futures?.ohlcv_history || []);
      const oi = futures?.oi_history || [];
      const volume = spot?.volume_history?.length ? spot.volume_history : (futures?.volume_history || []);
      if (!ohlcv.length && !oi.length && !volume.length) continue;
      instruments.push({
        id: `crypto-${symbol}`,
        label: symbol,
        subtitle: spot ? "Coinbase 现货" : "Binance 永续",
        source: spot ? "Coinbase" : (futures.aggregated ? "CoinGlass OI · Binance价格" : "Binance"),
        color: symbol === "BTC" ? "#0f8b78" : "#6274c5",
        unit: "USD",
        value: spot?.price_usd ?? futures?.price_usd,
        change: spot?.price_change_24h_pct ?? futures?.price_change_24h_pct,
        ohlcv, oi, volume,
      });
    }
    const addSeries = (id, label, subtitle, key, color, unit) => {
      const series = data.series?.[key];
      if (!series?.history?.length) return;
      instruments.push({id, label, subtitle, source: series.source || "公开源", color, unit, value: series.value, change: null, history: series.history, ohlcv: [], oi: [], volume: []});
    };
    addSeries("gold", "黄金", "XAU/USD 现货", "SPOT_XAUUSD", "#bd861f", "USD/oz");
    addSeries("silver", "白银", "XAG/USD 现货", "SPOT_XAGUSD", "#718096", "USD/oz");
    addSeries("brent", "Brent", "北海原油", "DCOILBRENTEU", "#8d5e33", "USD/bbl");
    addSeries("wti", "WTI", "美国原油", "DCOILWTICO", "#5f6d4c", "USD/bbl");
    return instruments;
  };

  const trendRows = (instrument, metric, period) => {
    let rows;
    if (metric === "price") {
      const candles = normalizeCandles(instrument.ohlcv);
      rows = candles.length >= 2
        ? candles.map((item) => ({...item, value: item.close}))
        : (instrument.history || []).map((item) => ({stamp: item[0], value: Number(item[1])})).filter((item) => Number.isFinite(item.value));
    } else if (metric === "oi") {
      rows = (instrument.oi || []).map((item) => ({stamp: item[0], value: Number(item[1])})).filter((item) => Number.isFinite(item.value));
    } else {
      const candles = normalizeCandles(instrument.ohlcv);
      rows = instrument.volume?.length
        ? instrument.volume.map((item) => ({stamp: item[0], value: Number(item[1])})).filter((item) => Number.isFinite(item.value))
        : candles.map((item) => ({stamp: item.stamp, value: item.volume})).filter((item) => Number.isFinite(item.value));
    }
    rows = rows.filter((item) => item.stamp);
    if (!rows.length) return [];
    const latest = new Date(rows.at(-1).stamp).getTime();
    const days = {"1W": 7, "1M": 30, "ALL": 3650};
    if (period === "1D") {
      const latestDay = dayKey(rows.at(-1).stamp);
      rows = rows.filter((item) => dayKey(item.stamp) === latestDay);
    } else {
      const cutoff = latest - (days[period] || 1) * 86400000;
      rows = rows.filter((item) => new Date(item.stamp).getTime() >= cutoff);
    }
    return rows.slice(-180);
  };

  const trendChart = (instrument, metric, period) => {
    const rows = trendRows(instrument, metric, period);
    if (rows.length < 2) return `<div class="dm-interactive-empty">${metric === "price" ? "价格样本不足" : "该资产暂未提供此项历史数据"}</div>`;
    const width = 900;
    const height = 330;
    const left = 56;
    const right = 18;
    const top = 20;
    const priceBottom = 224;
    const volumeBase = 286;
    const plotWidth = width - left - right;
    const candles = metric === "price" && rows.every((item) => Number.isFinite(item.open) && Number.isFinite(item.high) && Number.isFinite(item.low) && Number.isFinite(item.close));
    const values = candles ? rows.flatMap((item) => [item.low, item.high]) : rows.map((item) => item.value);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || Math.max(Math.abs(max) * .01, 1);
    const x = (index) => left + (index / (rows.length - 1)) * plotWidth;
    const y = (value) => priceBottom - ((value - min) / range) * (priceBottom - top);
    const barWidth = Math.max(2.5, Math.min(12, plotWidth / rows.length * .66));
    const grid = [0, 1, 2, 3, 4].map((index) => {
      const yy = top + (priceBottom - top) * index / 4;
      const value = max - range * index / 4;
      return `<line class="dm-interactive-grid" x1="${left}" y1="${yy.toFixed(1)}" x2="${width-right}" y2="${yy.toFixed(1)}"></line><text class="dm-interactive-axis" x="${left-8}" y="${(yy+4).toFixed(1)}" text-anchor="end">${escapeHtml(formatCompact(value, value >= 100 ? 0 : 2))}</text>`;
    }).join("");
    const volumeValues = rows.map((item) => Number.isFinite(item.volume) ? item.volume : item.value);
    const maxVolume = Math.max(...volumeValues.map((value) => Math.abs(value)), 1);
    const volumeBars = metric === "price" && candles ? rows.map((item, index) => {
      const volume = Number.isFinite(item.volume) ? item.volume : 0;
      const heightBar = Math.max(1, volume / maxVolume * 44);
      const positive = item.close >= item.open;
      return `<rect class="dm-interactive-volume ${positive ? "positive" : "negative"}" x="${(x(index)-barWidth/2).toFixed(1)}" y="${(volumeBase-heightBar).toFixed(1)}" width="${barWidth.toFixed(1)}" height="${heightBar.toFixed(1)}" rx="2"><title>${escapeHtml(formatDate(item.stamp))} · 成交量 ${escapeHtml(formatUsd(volume))}</title></rect>`;
    }).join("") : "";
    const candleMarkup = candles ? rows.map((item, index) => {
      const candleX = x(index);
      const high = y(item.high);
      const low = y(item.low);
      const bodyTop = y(Math.max(item.open, item.close));
      const bodyBottom = y(Math.min(item.open, item.close));
      const bodyHeight = Math.max(1.5, bodyBottom - bodyTop);
      const direction = item.close >= item.open ? "positive" : "negative";
      return `<line class="dm-interactive-wick ${direction}" x1="${candleX.toFixed(1)}" y1="${high.toFixed(1)}" x2="${candleX.toFixed(1)}" y2="${low.toFixed(1)}"></line><rect class="dm-interactive-candle ${direction}" x="${(candleX-barWidth/2).toFixed(1)}" y="${bodyTop.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${bodyHeight.toFixed(1)}" rx="1"><title>${escapeHtml(formatDate(item.stamp))} · O ${item.open} · H ${item.high} · L ${item.low} · C ${item.close}</title></rect>`;
    }).join("") : "";
    const linePoints = rows.map((item, index) => `${x(index).toFixed(1)},${y(item.value).toFixed(1)}`).join(" ");
    const lineMarkup = candles ? "" : `<path class="dm-interactive-area" style="--dm-color:${instrument.color}" d="M ${left} ${priceBottom} L ${rows.map((item,index) => `${x(index).toFixed(1)} ${y(item.value).toFixed(1)}`).join(" L ")} L ${width-right} ${priceBottom} Z"></path><polyline class="dm-interactive-line" style="--dm-color:${instrument.color}" points="${linePoints}"></polyline>`;
    const labels = [0, Math.floor((rows.length-1)/2), rows.length-1].map((index) => `<text class="dm-interactive-axis" x="${x(index).toFixed(1)}" y="${height-12}" text-anchor="${index === 0 ? "start" : index === rows.length-1 ? "end" : "middle"}">${escapeHtml(formatDate(rows[index].stamp))}</text>`).join("");
    const metricLabel = metric === "price" ? "价格" : metric === "oi" ? "持仓量" : "成交量";
    return `<svg class="dm-interactive-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(instrument.label)} ${metricLabel}图">${grid}<line class="dm-interactive-baseline" x1="${left}" y1="${volumeBase}" x2="${width-right}" y2="${volumeBase}"></line>${lineMarkup}${candleMarkup}${volumeBars}${labels}<text class="dm-interactive-axis" x="${left}" y="${volumeBase+16}">成交量</text></svg><div class="dm-interactive-chart-note">${candles ? "蜡烛为 OHLC；下方柱体为成交量，悬停可查看单根数据" : `${metricLabel}历史序列；源端未提供 OHLC，显示折线`}</div>`;
  };

  const renderDailyTrends = (data) => {
    const instruments = buildTrendInstruments(data);
    if (!instruments.length) return "";
    const initial = instruments.find((item) => item.id === "crypto-BTC") || instruments[0];
    const metricButtons = (item, active) => [
      ["price", "价格", true],
      ["oi", "持仓量", item.oi?.length >= 2],
      ["volume", "成交量", item.volume?.length >= 2 || normalizeCandles(item.ohlcv).some((row) => Number.isFinite(row.volume))],
    ].map(([key, label, enabled]) => `<button type="button" class="dm-trend-control ${active === key ? "active" : ""}" data-trend-metric="${key}" ${enabled ? "" : "disabled"}>${label}</button>`).join("");
    const assets = instruments.map((item) => `<button type="button" class="dm-trend-asset ${item.id === initial.id ? "active" : ""}" data-trend-asset="${item.id}"><span class="dm-trend-asset-dot" style="--dm-color:${item.color}"></span>${escapeHtml(item.label)}<small>${escapeHtml(item.subtitle)}</small></button>`).join("");
    const periods = [["1D", "1日"], ["1W", "1周"], ["1M", "1月"], ["ALL", "全部"]].map(([key, label], index) => `<button type="button" class="dm-trend-control ${index === 0 ? "active" : ""}" data-trend-period="${key}">${label}</button>`).join("");
    return `<section class="dm-interactive-trends" id="dynamic-trends" data-trend-selected="${initial.id}" data-trend-period="1D" data-trend-metric="price">
      <div class="dm-subhead"><div><span>Interactive chart · CoinGlass-style controls</span><h3>价格、持仓量与成交量</h3></div><time>数据按实际时间戳显示 · 15 分钟刷新</time></div>
      <div class="dm-trend-toolbar"><div class="dm-trend-asset-list">${assets}</div><div class="dm-trend-control-group" aria-label="指标切换">${metricButtons(initial, "price")}</div><div class="dm-trend-control-group" aria-label="时间周期">${periods}</div></div>
      <div class="dm-interactive-head"><div><strong id="dmTrendTitle">${escapeHtml(initial.label)} · ${escapeHtml(initial.subtitle)}</strong><span id="dmTrendMeta">${escapeHtml(initial.source)} · 价格</span><small id="dmTrendWindow">1日 · ${trendRows(initial, "price", "1D").length} 个观测</small></div><b id="dmTrendValue">${finite(initial.value) ? `$${formatCompact(initial.value, initial.unit === "USD" ? 2 : 2)}` : "待更新"}</b></div>
      <div class="dm-interactive-chart">${trendChart(initial, "price", "1D")}</div>
      <p class="dm-flow-note">CoinGlass 聚合权限启用时，持仓量/成交量使用多交易所聚合；否则显示 Binance 永续代理。金银与原油没有统一的实时交易所 OHLC，因此保留公开现货价格序列，不把变动代理冒充成交量。</p>
    </section>`;
  };

  const wireTrendControls = (data) => {
    const panel = document.querySelector(".dm-interactive-trends");
    if (!panel) return;
    const instruments = buildTrendInstruments(data);
    const periodLabels = {"1D": "1日", "1W": "1周", "1M": "1月", "ALL": "全部"};
    const state = {asset: panel.dataset.trendSelected || instruments[0]?.id, period: panel.dataset.trendPeriod || "1D", metric: panel.dataset.trendMetric || "price"};
    const update = () => {
      const instrument = instruments.find((item) => item.id === state.asset) || instruments[0];
      if (!instrument) return;
      const hasVolume = instrument.volume?.length >= 2 || normalizeCandles(instrument.ohlcv).some((row) => Number.isFinite(row.volume));
      if (state.metric === "oi" && instrument.oi?.length < 2) state.metric = "price";
      if (state.metric === "volume" && !hasVolume) state.metric = "price";
      const rows = trendRows(instrument, state.metric, state.period);
      panel.dataset.trendSelected = instrument.id;
      panel.dataset.trendPeriod = state.period;
      panel.dataset.trendMetric = state.metric;
      panel.querySelector(".dm-interactive-chart").innerHTML = trendChart(instrument, state.metric, state.period);
      panel.querySelector("#dmTrendTitle").textContent = `${instrument.label} · ${instrument.subtitle}`;
      panel.querySelector("#dmTrendMeta").textContent = `${instrument.source} · ${state.metric === "price" ? "价格" : state.metric === "oi" ? "持仓量" : "成交量"}`;
      panel.querySelector("#dmTrendWindow").textContent = `${periodLabels[state.period] || state.period} · ${rows.length} 个观测${rows.length >= 2 ? ` · ${formatDate(rows[0].stamp)} – ${formatDate(rows.at(-1).stamp)}` : ""}`;
      panel.querySelector("#dmTrendValue").textContent = finite(instrument.value) ? `$${formatCompact(instrument.value, 2)}` : "待更新";
      panel.querySelectorAll("[data-trend-asset]").forEach((button) => {
        button.classList.toggle("active", button.dataset.trendAsset === state.asset);
        button.setAttribute("aria-pressed", button.dataset.trendAsset === state.asset ? "true" : "false");
      });
      panel.querySelectorAll("[data-trend-period]").forEach((button) => {
        button.classList.toggle("active", button.dataset.trendPeriod === state.period);
        button.setAttribute("aria-pressed", button.dataset.trendPeriod === state.period ? "true" : "false");
      });
      panel.querySelectorAll("[data-trend-metric]").forEach((button) => {
        button.classList.toggle("active", button.dataset.trendMetric === state.metric);
        if (button.dataset.trendMetric === "oi") button.disabled = instrument.oi?.length < 2;
        if (button.dataset.trendMetric === "volume") button.disabled = !hasVolume;
        button.setAttribute("aria-pressed", button.dataset.trendMetric === state.metric ? "true" : "false");
      });
    };
    panel.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-trend-asset], button[data-trend-period], button[data-trend-metric]");
      if (!button || button.disabled) return;
      if (button.dataset.trendAsset) state.asset = button.getAttribute("data-trend-asset");
      if (button.dataset.trendPeriod) state.period = button.getAttribute("data-trend-period");
      if (button.dataset.trendMetric) state.metric = button.getAttribute("data-trend-metric");
      update();
    });
    update();
  };

  const getSeries = (data, key) => data.series?.[key] || null;
  const getDerived = (data, key) => data.derived?.[key] || null;

  const cards = [
    {label: "黄金现货 XAU/USD", key: "SPOT_XAUUSD", color: "#bd861f", value: (s) => `$${formatCompact(s.value, 2)}`, change: (d) => `${signed(getDerived(d, "XAU_15M")?.value, 2, "%")} / 15m`},
    {label: "白银现货 XAG/USD", key: "SPOT_XAGUSD", color: "#718096", value: (s) => `$${formatCompact(s.value, 3)}`, change: (d) => `${signed(getDerived(d, "XAG_15M")?.value, 2, "%")} / 15m`},
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
    {label: "Brent 原油", key: "DCOILBRENTEU", color: "#8d5e33", value: (s) => `$${formatCompact(s.value, 2)}`, change: (d) => signed(getDerived(d, "BRENT_DAILY")?.value, 2, "%")},
    {label: "WTI 原油", key: "DCOILWTICO", color: "#5f6d4c", value: (s) => `$${formatCompact(s.value, 2)}`, change: (d) => signed(getDerived(d, "WTI_DAILY")?.value, 2, "%")},
  ];

  const loadingMarkup = () => `
    <section class="dm-section" id="dynamic-data">
      <div class="container">
        <div class="section-head"><div><div class="section-kicker">Dynamic data · Zero-token pipeline</div><h2>低成本动态数据脉冲</h2></div><p class="section-note">正在读取官方数据快照…</p></div>
        <div class="dm-grid dm-loading-grid">${Array.from({length: 12}, () => `<div class="dm-card"><div class="dm-skeleton label"></div><div class="dm-skeleton value"></div><div class="dm-skeleton chart"></div></div>`).join("")}</div>
      </div>
    </section>`;

  const statusTone = (data) => {
    if (data.pipeline?.success_count === 0) return "error";
    if (data.pipeline?.error_count > 0 || ageHours(data.generated_at) > 1) return "stale";
    return "";
  };

  const scoreClass = (score) => Number(score) >= 10 ? "support" : Number(score) <= -10 ? "pressure" : "neutral";

  const renderConclusion = (data) => {
    const conclusion = data.daily_conclusion;
    if (!conclusion?.assets) return "";
    const assets = Object.values(conclusion.assets).map((asset) => {
      const drivers = (asset.drivers || []).slice(0, 4).map((driver) =>
        `<li><span class="dm-driver-direction ${driver.direction === "支持" ? "support" : driver.direction === "压制" ? "pressure" : "neutral"}">${escapeHtml(driver.direction)}</span><span>${escapeHtml(driver.fact)}</span></li>`
      ).join("");
      return `<article class="dm-conclusion-card ${scoreClass(asset.score)}">
        <div class="dm-conclusion-card-head"><div><span>${escapeHtml(asset.label)}</span><strong>${escapeHtml(asset.stance)}</strong></div><b>${Number(asset.score) > 0 ? "+" : ""}${Number(asset.score)}</b></div>
        <ul class="dm-driver-list">${drivers}</ul>
        <p>${escapeHtml(asset.interpretation)}</p>
      </article>`;
    }).join("");
    return `<section class="dm-conclusion" id="daily-conclusion">
      <div class="dm-subhead"><div><span>Daily conclusion · transparent rules</span><h3>每日规则结论 · 截至 ${escapeHtml(conclusion.date || formatDate(conclusion.as_of))}</h3></div><time>数据观测 ${formatGenerated(conclusion.as_of)}</time></div>
      <div class="dm-conclusion-lead"><strong>${escapeHtml(conclusion.headline)}</strong><p>${escapeHtml(conclusion.summary)}</p></div>
      <div class="dm-conclusion-grid">${assets}</div>
      <div class="dm-method-note"><strong>判定边界：</strong>${escapeHtml(conclusion.risk_note)}<br><span>${escapeHtml(conclusion.method_note)}</span></div>
    </section>`;
  };

  const formatUsd = (value) => {
    if (!finite(value)) return "待更新";
    const amount = Number(value);
    const absolute = Math.abs(amount);
    if (absolute >= 1e12) return `$${(amount / 1e12).toFixed(2)}T`;
    if (absolute >= 1e9) return `$${(amount / 1e9).toFixed(2)}B`;
    if (absolute >= 1e6) return `$${(amount / 1e6).toFixed(1)}M`;
    return `$${formatCompact(amount, 0)}`;
  };

  const formatOz = (value) => {
    if (!finite(value)) return "待更新";
    const amount = Number(value);
    if (Math.abs(amount) >= 1e9) return `${(amount / 1e9).toFixed(2)}B oz`;
    if (Math.abs(amount) >= 1e6) return `${(amount / 1e6).toFixed(2)}M oz`;
    return `${formatCompact(amount, 0)} oz`;
  };

  const renderInventoryCard = (item) => {
    const change = item.total_net_change_oz;
    const changeClass = finite(change) ? (Number(change) >= 0 ? "positive" : "negative") : "";
    return `<article class="dm-flow-card dm-inventory-card">
      <div class="dm-flow-card-head"><div><span class="dm-flow-kicker">CME warehouse · ${escapeHtml(item.metal === "gold" ? "Gold" : "Silver")}</span><h4>${escapeHtml(item.label || "COMEX 库存")}</h4></div><span class="dm-source">${escapeHtml(item.source || "CME")}</span></div>
      <div class="dm-flow-stats">
        <div><span>Registered 可交割</span><strong>${formatOz(item.registered_oz)}</strong><small>${formatCompact(item.registered_contract_equivalents, 0)} 张合约等值</small></div>
        <div><span>Eligible 合格</span><strong>${formatOz(item.eligible_oz)}</strong><small>不代表已签发仓单</small></div>
        <div><span>Pledged 已质押</span><strong>${formatOz(item.pledged_oz)}</strong><small>若源表提供</small></div>
        <div><span>Registered 占比</span><strong>${finite(item.registered_share_pct) ? `${Number(item.registered_share_pct).toFixed(2)}%` : "待更新"}</strong><small>占 Registered + Eligible</small></div>
      </div>
      <div class="dm-flow-meta"><span>合计 ${formatOz(item.total_oz)}</span><span class="${changeClass}">日变动 ${signed(change, 0, " oz")}</span><span>报告 ${formatDate(item.report_date)} · 活动 ${formatDate(item.activity_date)}</span></div>
      <p class="dm-flow-note">${escapeHtml(item.definition_note || "Registered 为已签发仓单库存；Eligible 为符合规格但未签发仓单。")}</p>
    </article>`;
  };

  const renderCryptoCard = (item, key, aggregate) => {
    const oiChange = item.open_interest_change_24h_pct;
    const funding = item.funding_rate_pct;
    const priceChange = item.price_change_24h_pct;
    return `<article class="dm-flow-card dm-crypto-card">
      <div class="dm-flow-card-head"><div><span class="dm-flow-kicker">${escapeHtml(key)} perpetual</span><h4>${escapeHtml(item.label || `${key} 永续合约`)}</h4></div><span class="dm-source">${aggregate ? "CoinGlass" : "Binance"}</span></div>
      <div class="dm-flow-stats">
        <div><span>持仓量 OI</span><strong>${formatUsd(item.open_interest_usd)}</strong><small class="${Number(oiChange) >= 0 ? "positive" : "negative"}">24h ${signed(oiChange, 2, "%")}</small></div>
        <div><span>成交量 24h</span><strong>${formatUsd(item.volume_24h_usd)}</strong><small>USDT 合约</small></div>
        <div><span>资金费率</span><strong>${signed(funding, 4, "%")}</strong><small>按最新观测</small></div>
        <div><span>价格 24h</span><strong>${finite(item.price_usd) ? `$${formatCompact(item.price_usd, 2)}` : "待更新"}</strong><small class="${Number(priceChange) >= 0 ? "positive" : "negative"}">${signed(priceChange, 2, "%")}</small></div>
      </div>
      <div class="dm-flow-meta"><span>观测 ${formatGenerated(item.observed_at)}</span><span>${escapeHtml(item.scope || "")}</span></div>
      <p class="dm-flow-note">${escapeHtml(item.note || "持仓量、成交量和资金费率均需结合交易所口径解读。")}</p>
    </article>`;
  };

  const renderSpotCard = (item, key) => {
    const range = finite(item.day_low) && finite(item.day_high) ? `${formatCompact(item.day_low, 2)} – ${formatCompact(item.day_high, 2)}` : "待更新";
    const price = finite(item.price_usd) ? `$${formatCompact(item.price_usd, 2)}` : "待更新";
    const changeClass = Number(item.price_change_24h_pct) >= 0 ? "positive" : "negative";
    return `<article class="dm-flow-card dm-spot-card">
      <div class="dm-flow-card-head"><div><span class="dm-flow-kicker">Coinbase spot · 7×24</span><h4>${escapeHtml(item.label || `${key} Coinbase 现货`)}</h4></div><span class="dm-source">Coinbase</span></div>
      <div class="dm-flow-stats"><div><span>现货价格</span><strong>${price}</strong><small class="${changeClass}">24h ${signed(item.price_change_24h_pct, 2, "%")}</small></div><div><span>24h 成交额估算</span><strong>${formatUsd(item.volume_24h_usd)}</strong><small>USD 现货</small></div><div><span>24h 区间</span><strong>${range}</strong><small>低 – 高</small></div><div><span>最新观测</span><strong>${formatGenerated(item.observed_at)}</strong><small>柏林时间换算</small></div></div>
      <p class="dm-flow-note">${escapeHtml(item.note || "Coinbase 现货市场 7×24 更新；不包含永续持仓量。")}</p>
    </article>`;
  };


  const renderCftcTrend = (data) => {
    const categories = ["生产商/贸易商", "掉期商", "管理资金", "其他报告商", "非报告商"];
    const colors = {"生产商/贸易商": "#c64752", "掉期商": "#276aa1", "管理资金": "#168c78", "其他报告商": "#b97c1f", "非报告商": "#7565cf"};
    const sourceHistory = data.cftc?.history || {};
    const metals = [["黄金", sourceHistory["黄金"] || []], ["白银", sourceHistory["白银"] || []]]
      .map(([label, history]) => [label, history.filter((item) => item?.date && item.categories && categories.every((category) => Number.isFinite(Number(item.categories[category])))).slice(-10)])
      .filter(([, history]) => history.length >= 2);
    if (!metals.length) {
      return `<section class="dm-cftc-trend" id="cftc-cross-asset"><div class="dm-subhead"><div><span>Positioning · official CFTC</span><h3>资金来源与持仓结构</h3></div><time>历史样本待首次同步</time></div><div class="dm-cftc-empty">CFTC 历史数据暂未完整读取；不会用插值或截图值代替真实持仓。</div></section>`;
    }
    const chart = (label, rows) => {
      const values = rows.flatMap((item) => categories.map((category) => Number(item.categories[category])));
      const maxAbs = Math.max(...values.map((value) => Math.abs(value)), 1);
      const width = 700;
      const height = 238;
      const left = 55;
      const right = 10;
      const top = 14;
      const bottom = 190;
      const baseline = (top + bottom) / 2;
      const scale = ((bottom - top) / 2) / maxAbs;
      const step = (width - left - right) / rows.length;
      const barWidth = Math.max(5, Math.min(12, step / 7));
      const groupWidth = categories.length * barWidth + (categories.length - 1) * 2;
      const bars = rows.map((row, rowIndex) => categories.map((category, categoryIndex) => {
        const value = Number(row.categories[category]);
        const heightBar = Math.max(1.5, Math.abs(value) * scale);
        const x = left + rowIndex * step + (step - groupWidth) / 2 + categoryIndex * (barWidth + 2);
        const y = value >= 0 ? baseline - heightBar : baseline;
        const title = `${label} · ${row.date} · ${category} · ${value > 0 ? "+" : ""}${Math.round(value).toLocaleString("zh-CN")} 张`;
        return `<rect class="dm-cftc-bar" x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${heightBar.toFixed(1)}" rx="2" fill="${colors[category]}"><title>${escapeHtml(title)}</title></rect>`;
      }).join("")).join("");
      const maxLabel = Math.round(maxAbs).toLocaleString("zh-CN");
      const labels = rows.map((row, index) => {
        if (index % 2 === 1 && index !== rows.length - 1) return "";
        return `<text class="dm-cftc-axis" x="${(left + index * step + step / 2).toFixed(1)}" y="${height - 20}" text-anchor="middle">${escapeHtml(row.date.slice(5))}</text>`;
      }).join("");
      const grid = `<line class="dm-cftc-gridline" x1="${left}" y1="${top}" x2="${width - right}" y2="${top}"></line><line class="dm-cftc-zero" x1="${left}" y1="${baseline}" x2="${width - right}" y2="${baseline}"></line><line class="dm-cftc-gridline" x1="${left}" y1="${bottom}" x2="${width - right}" y2="${bottom}"></line><text class="dm-cftc-axis" x="${left - 8}" y="${top + 4}" text-anchor="end">+${maxLabel}</text><text class="dm-cftc-axis" x="${left - 8}" y="${baseline + 4}" text-anchor="end">0</text><text class="dm-cftc-axis" x="${left - 8}" y="${bottom + 4}" text-anchor="end">−${maxLabel}</text>`;
      const latest = rows.at(-1);
      const latestRows = categories.map((category) => `<span><i style="--dm-color:${colors[category]}"></i>${escapeHtml(category)} <strong>${Number(latest.categories[category]).toLocaleString("zh-CN")} 张</strong></span>`).join("");
      return `<article class="dm-cftc-bar-card"><div class="dm-cftc-bar-head"><h4>${escapeHtml(label)} · 五类来源</h4><span>报告 ${escapeHtml(latest.date)}</span></div><div class="dm-cftc-chart-wrap"><svg class="dm-cftc-chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(label)} CFTC 五类资金来源分组柱状图">${grid}${bars}${labels}</svg></div><div class="dm-cftc-latest">${latestRows}</div></article>`;
    };
    const allDates = metals.flatMap(([, rows]) => rows.map((item) => item.date)).sort();
    const latestDate = allDates.at(-1);
    const legend = categories.map((category) => `<span><i style="--dm-color:${colors[category]}"></i>${escapeHtml(category)}</span>`).join("");
    return `<section class="dm-cftc-trend" id="cftc-cross-asset">
      <div class="dm-subhead"><div><span>Positioning · official CFTC</span><h3>资金来源与持仓结构 · 分组柱状图</h3></div><time>报告截至 ${escapeHtml(latestDate)} · 近 10 次周报</time></div>
      <div class="dm-cftc-callout"><strong>一簇 = 一次 CFTC 周报：</strong>每种颜色代表一个持仓来源，正值为净多、负值为净空。图中是合约净持仓，不是美元资金流；黄金和白银各自使用独立纵轴。</div>
      <div class="dm-cftc-bar-grid">${metals.map(([label, rows]) => chart(label, rows)).join("")}</div>
      <div class="dm-cftc-legend">${legend}</div>
      <p class="dm-flow-note">生产商/贸易商、掉期商、管理资金、其他报告商与非报告商均按 CFTC Disaggregated Futures-and-Options Combined 的多头减空头计算；不把净持仓/OI 与合约张数混为一谈。数据源：<a href="${escapeHtml(data.cftc?.history_source_url || data.cftc?.source_url || "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm")}" target="_blank" rel="noopener">CFTC 官方历史文件 ↗</a></p>
    </section>`;
  };

  const dailyChangeMap = (history, mode = "return") => {
    const grouped = new Map();
    (history || []).forEach((item) => {
      const stamp = item?.[0];
      const value = Number(item?.[1]);
      if (!stamp || !Number.isFinite(value)) return;
      const day = dayKey(stamp);
      if (day) grouped.set(day, value);
    });
    const ordered = [...grouped.entries()].sort((a, b) => a[0].localeCompare(b[0]));
    const changes = new Map();
    for (let index = 1; index < ordered.length; index += 1) {
      const [day, value] = ordered[index];
      const previous = ordered[index - 1][1];
      if (!Number.isFinite(previous) || previous === 0) continue;
      const change = mode === "difference" ? value - previous : value / previous - 1;
      if (Number.isFinite(change)) changes.set(day, change);
    }
    return changes;
  };

  const pairCorrelation = (left, right) => {
    const days = [...left.keys()].filter((day) => right.has(day)).sort();
    const values = days.map((day) => [left.get(day), right.get(day)]).filter(([a, b]) => Number.isFinite(a) && Number.isFinite(b));
    if (values.length < 5) return {value: null, n: values.length};
    const mean = (column) => values.reduce((sum, row) => sum + row[column], 0) / values.length;
    const meanLeft = mean(0);
    const meanRight = mean(1);
    let numerator = 0;
    let leftSum = 0;
    let rightSum = 0;
    values.forEach(([a, b]) => {
      const da = a - meanLeft;
      const db = b - meanRight;
      numerator += da * db;
      leftSum += da * da;
      rightSum += db * db;
    });
    const denominator = Math.sqrt(leftSum * rightSum);
    return {value: denominator ? numerator / denominator : 0, n: values.length};
  };

  const renderCrossAssetCorrelation = (data) => {
    const definitions = [
      {id: "gold", label: "黄金", key: "SPOT_XAUUSD", mode: "return", color: "#bd861f"},
      {id: "silver", label: "白银", key: "SPOT_XAGUSD", mode: "return", color: "#718096"},
      {id: "dollar", label: "美元指数", key: "DTWEXBGS", mode: "return", color: "#276aa1"},
      {id: "real", label: "10Y 实际利率", key: "DFII10", mode: "difference", color: "#c64752"},
      {id: "nominal", label: "美债 10Y", key: "DGS10", mode: "difference", color: "#7565cf"},
      {id: "brent", label: "Brent", key: "DCOILBRENTEU", mode: "return", color: "#8d5e33"},
      {id: "wti", label: "WTI", key: "DCOILWTICO", mode: "return", color: "#5f6d4c"},
      {id: "usdjpy", label: "USD/JPY", key: "FX_USDJPY", mode: "return", color: "#b97c1f"},
      {id: "vix", label: "VIX", key: "VIXCLS", mode: "return", color: "#b84d82"},
    ];
    const changes = new Map();
    const crossHistories = data.cross_asset?.histories || {};
    definitions.forEach((definition) => {
      const history = crossHistories[definition.id] || data.series?.[definition.key]?.history;
      changes.set(definition.id, dailyChangeMap(history, definition.mode));
    });
    const storedGoldSilver = data.cross_asset?.gold_silver;
    const goldSilver = storedGoldSilver && Object.prototype.hasOwnProperty.call(storedGoldSilver, "value")
      ? {value: storedGoldSilver.value, n: storedGoldSilver.n || 0}
      : pairCorrelation(changes.get("gold"), changes.get("silver"));
    const drivers = definitions.filter((definition) => !["gold", "silver"].includes(definition.id));
    const cells = (rowDefinition) => drivers.map((column) => {
      const stored = data.cross_asset?.matrix?.[rowDefinition.id]?.[column.id];
      const result = stored && Object.prototype.hasOwnProperty.call(stored, "value")
        ? {value: stored.value, n: stored.n || 0}
        : pairCorrelation(changes.get(rowDefinition.id), changes.get(column.id));
      const value = result.value;
      const intensity = value === null ? 0 : Math.min(.72, .14 + Math.abs(value) * .58);
      const background = value === null ? "transparent" : value >= 0 ? `rgba(22,140,120,${intensity})` : `rgba(189,74,83,${intensity})`;
      const foreground = value !== null && Math.abs(value) > .58 ? "#fff" : "var(--ink)";
      return `<td class="dm-correlation-cell ${value === null ? "insufficient" : value >= 0 ? "positive" : "negative"}" style="--dm-cell-bg:${background};--dm-cell-fg:${foreground}"><strong>${value === null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(2)}`}</strong><small>n=${result.n}</small></td>`;
    }).join("");
    const header = drivers.map((definition) => `<th scope="col"><span style="--dm-color:${definition.color}"></span>${escapeHtml(definition.label)}</th>`).join("");
    const row = (definition) => `<tr><th scope="row"><span style="--dm-color:${definition.color}"></span>${escapeHtml(definition.label)}</th>${cells(definition)}</tr>`;
    const latestMove = (key, mode) => {
      const changesForSeries = dailyChangeMap(data.series?.[key]?.history, mode);
      return changesForSeries.size ? [...changesForSeries.values()].at(-1) : null;
    };
    const goldMove = latestMove("SPOT_XAUUSD", "return");
    const silverMove = latestMove("SPOT_XAGUSD", "return");
    const dollarMove = latestMove("DTWEXBGS", "return");
    const realMove = latestMove("DFII10", "difference");
    const oilMove = latestMove("DCOILWTICO", "return");
    const readItems = [
      `<span><b>金银联动</b>${goldSilver.value === null ? `样本累积中（n=${goldSilver.n}，至少需要 5 个共同交易日）` : `r=${goldSilver.value.toFixed(2)}；${goldSilver.value >= .45 ? "同涨同跌较明显" : goldSilver.value <= -.25 ? "短期出现分化" : "联动偏弱"}`}</span>`,
      `<span><b>美元 / 实际利率</b>${dollarMove !== null || realMove !== null ? `美元 ${dollarMove === null ? "待更新" : signed(dollarMove * 100, 2, "%")}；实际利率 ${realMove === null ? "待更新" : signed(realMove * 100, 1, "bp")}。两者同时上行通常压制贵金属估值。` : "等待共同观测"}</span>`,
      `<span><b>原油背景</b>${oilMove !== null ? `WTI 日变动 ${signed(oilMove * 100, 2, "%")}；油价上行会抬升通胀预期，也可能强化利率压力。` : "等待共同观测"}</span>`,
    ].join("");
    const observed = [data.series?.SPOT_XAUUSD?.observed_at, data.series?.DFII10?.date, data.series?.DCOILWTICO?.date].filter(Boolean).sort().at(-1) || data.generated_at;
    return `<section class="dm-correlation" id="cross-asset-correlation">
      <div class="dm-subhead"><div><span>Cross-asset relationships · rolling daily changes</span><h3>黄金、白银与宏观驱动的相关性</h3></div><time>截至 ${escapeHtml(formatDate(data.cross_asset?.as_of || observed))} · 最多 90 个共同观测日</time></div>
      <div class="dm-correlation-callout"><strong>先看方向，再看系数：</strong>表格是共同日期的 Pearson 相关系数；价格/指数使用日收益率，利率使用日变动。正值代表同向，负值代表反向；n 是实际共同观测数，样本不足时不显示系数。</div>
      <div class="dm-correlation-table-wrap"><table class="dm-correlation-table"><thead><tr><th scope="col">对象 ↓ / 驱动 →</th>${header}</tr></thead><tbody>${row(definitions[0])}${row(definitions[1])}</tbody></table></div>
      <div class="dm-correlation-read">${readItems}</div>
      <p class="dm-flow-note">这是统计上的同步关系，不等于因果关系。金银公开现货历史正在按 15 分钟快照累积；在共同交易日达到 5 个之前，页面会显示样本累积中而不是编造相关系数。观测时间：${escapeHtml(formatGenerated(data.generated_at))}。</p>
    </section>`;
  };

  const renderFlowPositioning = (data) => {
    const flow = data.flow_positioning || {};
    const inventory = flow.cme_inventory?.metals || {};
    const crypto = flow.crypto || {};
    const cryptoAssets = crypto.assets || {};
    const spotAssets = crypto.spot_assets || {};
    const inventoryCards = [inventory.gold, inventory.silver].filter(Boolean).map(renderInventoryCard).join("");
    const cryptoCards = Object.entries(cryptoAssets).map(([key, item]) => renderCryptoCard(item, key, crypto.aggregated)).join("");
    const spotCards = Object.entries(spotAssets).map(([key, item]) => renderSpotCard(item, key)).join("");
    if (!inventoryCards && !cryptoCards && !spotCards && !Object.keys(data.series || {}).length) return "";
    const exchange = crypto.exchange_totals || {};
    const etf = crypto.etf || {};
    const extras = (finite(exchange.open_interest_usd) || finite(exchange.volume_24h_usd) || finite(exchange.liquidation_24h_usd) || finite(etf.aum_usd))
      ? `<div class="dm-flow-summary"><span>CoinGlass 市场合计（若已启用）</span><strong>OI ${formatUsd(exchange.open_interest_usd)} · 成交 ${formatUsd(exchange.volume_24h_usd)} · 清算 ${formatUsd(exchange.liquidation_24h_usd)}</strong><small>BTC ETF AUM ${formatUsd(etf.aum_usd)} · 持仓 ${finite(etf.btc_holdings) ? formatCompact(etf.btc_holdings, 0) + " BTC" : "待更新"}</small></div>`
      : "";
    const sourceNote = crypto.aggregated ? "CoinGlass 聚合永续 OI/资金费率已启用；Coinbase 现货价格/K线独立按 7×24 更新。" : "当前为 Binance USDⓈ-M 单交易所永续代理 + Coinbase 7×24 现货；配置 COINGLASS_API_KEY 后自动切换多交易所聚合。";
    return `<section class="dm-flow" id="dynamic-flow">
      <div class="dm-subhead"><div><span>Cross-asset confirmation · positioning</span><h3>跨资产关系与资金确认</h3></div><time>更新于 ${formatGenerated(flow.updated_at || crypto.checked_at || data.generated_at)}</time></div>
      ${renderCrossAssetCorrelation(data)}
      ${renderCftcTrend(data)}
      ${extras}
      <details class="dm-flow-details"><summary>展开资金、持仓与库存原始明细</summary><div class="dm-flow-grid">${inventoryCards}${cryptoCards}${spotCards}</div></details>
      <p class="dm-flow-note dm-flow-source-note"><strong>口径：</strong>${escapeHtml(sourceNote)} ${escapeHtml(flow.scope_note || "库存与衍生品指标是背景信号，不直接替代现货与 CFTC 结论。")}</p>
    </section>`;
  };

  const renderCalendar = (data) => {
    const calendar = data.calendar;
    const events = (calendar?.events || []).slice(0, 4);
    if (!events.length) return "";
    const rows = events.map((event) => {
      const detail = [event.forecast ? `预期 ${event.forecast}` : "", event.previous ? `前值 ${event.previous}` : ""].filter(Boolean).join(" · ");
      return `<article class="dm-event">
        <time>${formatDate(event.timestamp)}</time>
        <span class="dm-country">${escapeHtml(event.country)}</span>
        <div class="dm-event-copy"><strong>${escapeHtml(event.title)}</strong><span>${detail ? escapeHtml(detail) + " · " : ""}<a href="${escapeHtml(event.source_url)}" target="_blank" rel="noopener">${escapeHtml(event.source)}</a>${event.official ? " · 官方" : ""}</span></div>
        <span class="dm-impact ${event.impact?.toLowerCase()}">${escapeHtml(event.impact)}</span>
      </article>`;
    }).join("");
    return `<section class="dm-calendar dm-calendar-compact" id="dynamic-calendar">
      <div class="dm-subhead"><div><span>Economic calendar · Europe/Berlin</span><h3>自动财经日历</h3></div><time>检查于 ${formatGenerated(calendar.checked_at)}</time></div>
      <div class="dm-event-list">${rows}</div>
      <p class="dm-calendar-note">${escapeHtml(calendar.coverage_note || "")}</p>
    </section>`;
  };

  const renderTopBriefing = (data) => {
    const conclusion = renderConclusion(data);
    const calendar = renderCalendar(data);
    if (!conclusion && !calendar) return "";
    return `<div class="dm-top-briefing">${conclusion ? `<div>${conclusion}</div>` : ""}${calendar ? `<div>${calendar}</div>` : ""}</div>`;
  };

  const renderCloseAnalysis = (data) => {
    const analysis = data.post_close_analysis;
    const bar = analysis?.daily_bar;
    if (!analysis || !bar) return "";
    const metrics = analysis.metrics || {};
    const levels = analysis.levels || {};
    const silver = analysis.silver || {};
    const oil = analysis.oil || {};
    const thorson = analysis.thorson || {};
    const pattern = analysis.pattern || {};
    const scenarios = (analysis.scenarios || []).map((item) => {
      const tone = item.rank === "A" ? "a" : item.rank === "B" ? "b" : "c";
      return `<article class="dm-scenario ${tone}"><div class="dm-scenario-head"><span>优先级 ${escapeHtml(item.rank || "?")}</span><strong>${escapeHtml(item.priority || "")}</strong></div><h4>${escapeHtml(item.title || "情景待定义")}</h4><p><b>触发：</b>${escapeHtml(item.trigger || "待更新")}</p><p><b>失效：</b>${escapeHtml(item.invalidation || "待更新")}</p><small>观察位：${escapeHtml(item.watch || "待更新")}</small></article>`;
    }).join("");
    const sourceLinks = (Array.isArray(analysis.source_url) ? analysis.source_url : [analysis.source_url]).filter(Boolean).slice(0, 3).map((url) => `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">公开来源</a>`).join(" · ");
    const money = (value, digits = 2) => finite(value) ? `$${formatCompact(value, digits)}` : "待更新";
    return `<section class="dm-close-analysis" id="close-analysis">
      <div class="dm-subhead"><div><span>Close analysis · one-page read</span><h3>收盘形态：先看黄金，再看确认信号</h3></div><time>${escapeHtml(analysis.as_of || "待更新")} · ${escapeHtml(analysis.basis || "")}</time></div>
      <div class="dm-close-lead"><strong>${escapeHtml(pattern.label || "形态待确认")} · ${escapeHtml(pattern.bias || "方向待确认")}</strong><p>实体占日内区间 ${finite(metrics.body_pct) ? `${formatCompact(metrics.body_pct, 1)}%` : "待更新"}，收盘位于区间 ${finite(metrics.close_location_pct) ? `${formatCompact(metrics.close_location_pct, 1)}%` : "待更新"}；${escapeHtml(pattern.confirmation || "等待下一根日线确认")}</p></div>
      <div class="dm-close-compact-grid">
        <article class="dm-close-focus"><div class="dm-close-focus-head"><div><span>London spot · XAU/USD</span><h4>黄金关键价位</h4></div><b>${money(bar.close)}</b></div><div class="dm-close-kpis"><span>支撑 1 <strong>${money(levels.support_1)}</strong></span><span>中位 <strong>${money(levels.midpoint)}</strong></span><span>压力 1 <strong>${money(levels.resistance_1)}</strong></span><span>压力 2 <strong>${money(levels.resistance_2)}</strong></span></div><p>O/H/L/C：${money(bar.open)} / ${money(bar.high)} / ${money(bar.low)} / ${money(bar.close)}。连续收盘跌破支撑才升级为趋势性转弱。</p></article>
        <article class="dm-close-focus"><div class="dm-close-focus-head"><div><span>Cross-asset confirmation</span><h4>白银与能源</h4></div><b>${escapeHtml(silver.stance || "待更新")}</b></div><div class="dm-close-kpis"><span>白银 <strong>${money(silver.value, 3)}</strong><small>${signed(silver.session_change, 2, "%")}</small></span><span>Brent <strong>${money(oil.brent)}</strong><small>${signed(oil.brent_change, 2, "%")}</small></span><span>WTI <strong>${money(oil.wti)}</strong><small>${signed(oil.wti_change, 2, "%")}</small></span></div><p>${escapeHtml(silver.note || "白银对实际利率与工业周期更敏感。")} ${escapeHtml(oil.stance || "油价用于校验通胀与需求背景。")}</p></article>
      </div>
      <div class="dm-close-confirmations"><div><b>外部观点</b><span>${escapeHtml(thorson.label || "AG Thorson")}：${escapeHtml(thorson.summary || "暂无公开观点摘要")}</span></div><div><b>读法</b><span>形态只决定短线偏向；白银、油价与实际利率负责确认或削弱，不单独替代黄金价格触发条件。</span></div></div>
      <div class="dm-scenario-grid">${scenarios}</div>
      <p class="dm-close-note"><strong>数据纪律：</strong>${escapeHtml(analysis.data_quality || "日线与现货源的交易日界线可能不同；不把变动代理标成真实成交量。")} ${sourceLinks ? `· ${sourceLinks}` : ""}</p>
    </section>`;
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
        <div class="dm-card-foot"><span>${formatDate(series.observed_at || series.date)}</span><span>${escapeHtml(series.id)}</span></div>
      </article>`;
    }).join("");
    const errorNote = pipeline.error_count > 0
      ? `<div class="dm-notice warning"><span>△</span><div><strong>${pipeline.error_count} 个来源使用降级处理。</strong> 页面保留最近一次有效值，不以空值覆盖；详细错误记录在数据 JSON 中。</div></div>`
      : `<div class="dm-notice"><span>ⓘ</span><div><strong>每 15 分钟刷新金银现货与快数据，AI token 为 0。</strong> 金银为公开聚合指示中间价，不是券商可成交报价；慢速宏观数据按自身发布频率缓存。</div></div>`;
    mount.innerHTML = `<section class="dm-section" id="dynamic-data"><div class="container">
      <div class="section-head"><div><div class="section-kicker">15-minute data · Zero-token pipeline</div><h2>低成本动态市场中枢</h2></div><p class="section-note">每 15 分钟检查快数据；规则引擎同步更新结论与事件风险，不需要 AI 重写整页。</p></div>
      <div class="dm-status-panel">
        <div class="dm-status-main"><span class="dm-status-light ${tone}"></span><div><strong>${statusText}</strong><span>生成于 ${formatGenerated(data.generated_at)} · 下次计划 ${formatGenerated(pipeline.next_scheduled_at)}</span></div></div>
        <div class="dm-status-stat"><span>可用数据源</span><strong>${pipeline.success_count || 0} / ${pipeline.source_count || 0}</strong></div>
        <div class="dm-status-stat"><span>CFTC 自动映射</span><strong>${data.cftc?.dynamic_count || 0} / ${data.cftc?.target_count || 10}</strong></div>
        <div class="dm-status-stat"><span>AI token</span><strong>${pipeline.ai_tokens_used || 0}</strong></div>
        <button class="dm-refresh" id="dmRefresh" type="button">重新读取</button>
      </div>
      ${errorNote}${renderTopBriefing(data)}<p class="dm-source-line"><strong>动态来源：</strong>金银公开现货 API；BTC/ETH 现货 Coinbase 7×24；永续 OI/资金费率 Binance 或 CoinGlass；宏观 FRED/ECB；库存 CME。页面不读取 IBKR 实时行情，所有结论均显示各自观测日期。</p><div class="dm-grid">${cardMarkup}</div>
      ${renderDailyTrends(data)}
      ${renderCloseAnalysis(data)}
      ${renderFlowPositioning(data)}
    </div></section>`;
    wireTrendControls(data);
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
    const xau = getSeries(data, "SPOT_XAUUSD");
    const xag = getSeries(data, "SPOT_XAGUSD");
    const usdjpy = getSeries(data, "FX_USDJPY");
    const dgs10 = getSeries(data, "DGS10");
    const dgs30 = getSeries(data, "DGS30");
    const vix = getSeries(data, "VIXCLS");
    const spx = getSeries(data, "SP500");
    const ndx = getSeries(data, "NASDAQCOM");
    if (xau) setQuote("黄金现货", xau.value, `${signed(getDerived(data, "XAU_15M")?.value, 2, "%")} / 15m`, getDerived(data, "XAU_15M")?.value, `${xau.source} 指示中间价 · ${formatGenerated(xau.observed_at)}`);
    if (xag) setQuote("白银现货", xag.value, `${signed(getDerived(data, "XAG_15M")?.value, 2, "%")} / 15m`, getDerived(data, "XAG_15M")?.value, `${xag.source} 指示中间价 · ${formatGenerated(xag.observed_at)}`);
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
    const conclusion = data.daily_conclusion;
    const briefDate = conclusion?.date || data.generated_at?.slice(0, 10) || "动态更新";
    document.title = `黄金 · 白银 · 日元每日简报｜${briefDate}`;
    const description = document.querySelector('meta[name="description"]');
    if (description) description.content = `${briefDate} 黄金、白银与日元动态市场简报；金银参考价与规则结论每15分钟检查。`;
    const eyebrow = document.querySelector(".hero .eyebrow");
    if (eyebrow) eyebrow.textContent = "Daily briefing · Dynamic";
    const firstPill = document.querySelector(".hero .meta-row .pill");
    if (firstPill) firstPill.innerHTML = `<span class="dot"></span>动态数据 ${formatGenerated(data.generated_at)}`;
    const nextEvent = data.calendar?.next_event;
    if (nextEvent) {
      const eventCard = document.querySelector(".hero .event-card");
      const eventTitle = eventCard?.querySelector("h2");
      const eventTime = eventCard?.querySelector(".event-time");
      const eventNote = eventCard?.querySelector(".event-note");
      if (eventTitle) eventTitle.textContent = nextEvent.title;
      if (eventTime) eventTime.textContent = `${formatGenerated(nextEvent.timestamp)} · ${nextEvent.country} · ${nextEvent.impact}`;
      if (eventNote) eventNote.textContent = `自动日历下一事件；${nextEvent.forecast ? `预期 ${nextEvent.forecast}，` : ""}${nextEvent.previous ? `前值 ${nextEvent.previous}。` : "公布前后注意跳空与点差扩大。"}`;
      window.setNextEventTime?.(nextEvent.timestamp);
    }
    const footerDate = document.querySelector("footer .footer-inner span:first-child");
    if (footerDate) footerDate.textContent = `Metals & Yen Daily · ${briefDate} · 15-minute data`;
    const meta = document.querySelector(".hero .meta-row");
    if (meta && !meta.querySelector("[data-dynamic-meta]")) meta.insertAdjacentHTML("beforeend", `<span class="pill" data-dynamic-meta><span class="dot"></span>15分钟数据 ${formatGenerated(data.generated_at)} · 0 token</span>`);
    window.marketDashboardData = data;
  };

  const endpoints = (force) => {
    const bucket = force ? Date.now() : Math.floor(Date.now() / 300000);
    const cacheKey = `v=${bucket}`;
    const relative = `${relativeEndpoint}${relativeEndpoint.includes("?") ? "&" : "?"}${cacheKey}`;
    const api = `${apiEndpoint}&${cacheKey}`;
    return production ? [api, relative, `${rawEndpoint}?${cacheKey}`] : [relative, api, `${rawEndpoint}?${cacheKey}`];
  };

  const fetchFirst = async (urls) => {
    const errors = [];
    for (const url of urls) {
      try {
        const response = await fetch(url, {cache: "no-store"});
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
        let data = await response.json();
        if (url.startsWith("https://api.github.com/") && data.content) {
          const bytes = Uint8Array.from(atob(data.content.replace(/\s/g, "")), (char) => char.charCodeAt(0));
          data = JSON.parse(new TextDecoder().decode(bytes));
        }
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
