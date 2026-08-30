(() => {
  const mount = document.getElementById("decision-pyramid-extension");
  if (!mount) return;

  const esc = (value) => String(value).replace(/[&<>"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;"
  })[char]);

  const layers = [
    {
      code: "L1", title: "流动性", weight: 30, color: "#276aa1", signal: "边际收紧", score: 65,
      contribution: "黄金 +16.5｜白银 +10.5",
      metrics: [["美联储总资产", "6.746 万亿美元"], ["周度变化", "−143 亿美元"], ["ON RRP", "3.8 亿美元"], ["10Y−2Y 利差", "+0.42pct"]],
      asof: "本期口径：Fed/FRED，2026-08-19 至 08-24"
    },
    {
      code: "L2", title: "经济周期", weight: 25, color: "#b97c1f", signal: "分化 / 制造偏弱", score: 56,
      contribution: "黄金 +6.3｜白银 −2.5",
      metrics: [["美国 Q2 GDP", "+1.5% 年化"], ["中国 Q2 GDP", "+4.3% 同比"], ["中国制造业 PMI", "49.2"], ["欧元区 PMI", "51.4"]],
      asof: "GDP 为本期/截图口径；PMI 为用户图表样本，非实时"
    },
    {
      code: "L3", title: "通胀水平", weight: 20, color: "#c64752", signal: "粘性 / 风险偏上", score: 72,
      contribution: "黄金 +11.0｜白银 +9.0",
      metrics: [["美国总 PCE", "3.7%"], ["10Y 盈亏平衡", "2.32%"], ["10Y 实际利率", "2.40%"], ["下一验证", "自动财经日历"]],
      asof: "本期口径：BEA/FRED；PCE 为 2026-06 数据"
    },
    {
      code: "L4", title: "大类资产", weight: 15, color: "#7565cf", signal: "贵金属支持", score: 69,
      contribution: "黄金 +9.0｜白银 +5.3",
      metrics: [["美债 10Y", "4.658%"], ["美债 30Y", "5.191%"], ["美元指数", "98.87"], ["SPX / NDX", "+0.35 / +0.77%"]],
      asof: "本期口径：IBKR 延迟行情，2026-08-25"
    },
    {
      code: "L5", title: "资金情绪", weight: 7, color: "#b84d82", signal: "偏多但需验证", score: 62,
      contribution: "黄金 +1.4｜白银 +1.1",
      metrics: [["VIX", "加载后更新"], ["美国 HY OAS", "加载后更新"], ["白银管理资金净多", "动态加载"], ["跨资产 CFTC", "动态加载"]],
      asof: "VIX/OAS 与 CFTC 均由最新数据包更新"
    },
    {
      code: "L6", title: "政策与地缘", weight: 3, color: "#168c78", signal: "风险溢价支撑", score: 67,
      contribution: "黄金 +1.7｜白银 +1.1",
      metrics: [["美联储目标区间", "3.50–3.75%"], ["日本政策利率", "1.00%"], ["长债买回", "流动性干预"], ["地缘风险", "中东 / 伊朗"]],
      asof: "本期政策与事件监测口径，非量化预测"
    }
  ];

  const catalog = {
    L1: [
      ["美联储资产负债表", "FRED H.4.1", "周度", "connected", "本期已引用"],
      ["中国央行资产负债表", "PBOC", "月度", "catalog", "全球流动性"],
      ["欧洲央行资产负债表", "ECB", "周度", "catalog", "全球流动性"],
      ["日本央行资产负债表", "FRED / BOJ", "月度", "catalog", "全球流动性"],
      ["美国国债总额", "FRED GFDEBTN", "季度", "catalog", "财政供给"],
      ["美国债务 / GDP", "FRED GFDEGDQ188S", "季度", "catalog", "债务可持续性"],
      ["美国联邦利息支出", "FRED A091RC1Q027SBEA", "季度", "catalog", "财政压力"],
      ["美联储政策利率", "FRED FEDFUNDS", "月度", "connected", "本期已引用"],
      ["美联储点阵图", "FOMC", "季度", "event", "政策路径"],
      ["美联储主席讲话 / SEP", "Federal Reserve", "事件/半年", "event", "政策文本"],
      ["美国 M2 同比", "FRED WM2NS", "月度", "catalog", "货币水位"],
      ["中国 M1 / M2 剪刀差", "PBOC", "月度", "snapshot", "截图指标"],
      ["美国银行准备金余额", "FRED TOTRESNS", "月度", "catalog", "银行流动性"],
      ["ON RRP 用量", "FRED RRPONTSYD", "日度", "connected", "本期已引用"],
      ["TGA 账户", "FRED WDTGAL", "周度", "catalog", "财政抽水/放水"],
      ["美国联邦预算赤字", "FRED FYFSD", "年度", "catalog", "财政脉冲"],
      ["美国债务上限风险", "News / Treasury", "事件", "event", "尾部风险"],
      ["中国社会融资规模", "PBOC", "月度", "catalog", "信用总量"],
      ["中国信贷分项", "PBOC", "月度", "catalog", "信用结构"],
      ["社融：人民币贷款", "PBOC", "月度", "catalog", "信用结构"],
      ["社融：政府债券", "PBOC / MOF", "月度", "catalog", "财政信用"],
      ["社融：企业债券", "PBOC", "月度", "catalog", "企业信用"],
      ["社融：股票融资", "PBOC", "月度", "catalog", "权益融资"],
      ["美国消费者信贷", "FRB G.19", "月度", "catalog", "居民信用"],
      ["科技企业融资", "Earnings / Filings", "季度", "event", "AI 资本开支"],
      ["10Y−2Y 利差", "FRED DGS10−DGS2", "日度", "connected", "本期已引用"],
      ["SOFR−3M 利差", "FRED", "日度", "catalog", "美元融资压力"],
      ["政策利率−2Y 利差", "FEDFUNDS−DGS2", "日度", "catalog", "政策定价"],
      ["政策利率−10Y 利差", "FEDFUNDS−DGS10", "日度", "catalog", "期限结构"]
    ],
    L2: [
      ["美国 ISM 制造业 PMI", "ISM", "月度", "catalog", "制造业景气"],
      ["美国 ISM 服务业 PMI", "ISM", "月度", "catalog", "服务业景气"],
      ["中国官方 PMI", "NBS", "月度", "snapshot", "截图指标 49.2"],
      ["欧元区 PMI", "S&P Global", "月度", "snapshot", "截图指标 51.4"],
      ["全球 GDP 同比", "World Bank", "年度", "catalog", "全球周期"],
      ["美国 GDP", "FRED GDP / BEA", "季度", "connected", "本期已引用"],
      ["中国 GDP", "NBS", "季度", "snapshot", "截图/本期口径"],
      ["美国非农就业", "BLS PAYEMS", "月度", "catalog", "劳动力需求"],
      ["美国非农就业（2022+）", "BLS / JEC", "月度", "catalog", "后疫情比较"],
      ["美国失业率", "FRED UNRATE", "月度", "catalog", "劳动力松紧"],
      ["美国时薪", "FRED CES0500000003", "月度", "catalog", "工资通胀"],
      ["JOLTS 职位空缺", "FRED JTSJOL", "月度", "catalog", "招聘需求"]
    ],
    L3: [
      ["美国 CPI", "FRED CPIAUCSL", "月度", "catalog", "总通胀"],
      ["美国 PCE", "FRED PCEPI / BEA", "月度", "connected", "本期已引用"],
      ["美国核心 PCE", "FRED PCEPILFE", "月度", "catalog", "政策核心指标"],
      ["美国制造业 PPI", "FRED PCUOMFGOMFG", "月度", "catalog", "投入成本"],
      ["半导体 PPI", "FRED PCU33443344", "月度", "snapshot", "截图指标"],
      ["中国 CPI / PPI", "NBS", "月度", "catalog", "中国价格周期"],
      ["通胀盈亏平衡", "FRED T5YIE / T5YIFR", "日度", "connected", "本期已引用"]
    ],
    L4: [
      ["美债 10Y / 2Y 利差", "Market / FRED", "日度", "connected", "本期已引用"],
      ["美债 30Y", "Market DGS30", "日度", "connected", "本期已引用"],
      ["美债 10Y", "Market DGS10", "日度", "connected", "本期已引用"],
      ["美债 2Y", "Market DGS2", "日度", "catalog", "政策预期"],
      ["日本 10Y", "Market / BOJ", "日度", "catalog", "日元定价"],
      ["中国 10Y", "Market / CCDC", "日度", "catalog", "人民币利率"],
      ["AAA / BBB 信用利差", "ICE BofA", "日度", "catalog", "信用风险"],
      ["纳斯达克综合指数", "Market", "日度", "connected", "科技风险偏好"],
      ["日经 225", "Market", "日度", "catalog", "日本风险资产"],
      ["韩国 KOSPI", "Market", "日度", "catalog", "半导体周期"],
      ["上证指数", "Market", "日度", "catalog", "中国风险资产"],
      ["创业板", "Market", "日度", "catalog", "中国成长股"],
      ["富时中国 A50", "Market", "日度", "catalog", "中国蓝筹"],
      ["美股 AI 巨头", "Filings / Market", "季度/日度", "event", "AI 主线"],
      ["黄金", "COMEX / Spot", "日度", "connected", "本期核心资产"],
      ["白银", "COMEX / Spot", "日度", "connected", "本期核心资产"],
      ["比特币", "Market", "日度", "catalog", "替代流动性资产"]
    ],
    L5: [
      ["CFTC 黄金持仓", "CFTC COT", "周度", "catalog", "CFTC 官方周报；动态接入"],
      ["CFTC 白银持仓", "CFTC COT", "周度", "connected", "本期已引用"],
      ["CFTC 铂金持仓", "CFTC COT", "周度", "catalog", "CFTC 官方周报；动态接入"],
      ["CFTC 钯金持仓", "CFTC COT", "周度", "catalog", "CFTC 官方周报；动态接入"],
      ["CFTC 铜持仓", "CFTC COT", "周度", "catalog", "CFTC 官方周报；动态接入"],
      ["CFTC 钴持仓", "CFTC COT", "周度", "catalog", "CFTC 官方周报；动态接入"],
      ["CFTC 氢氧化锂持仓", "CFTC COT", "周度", "catalog", "CFTC 官方周报；动态接入"],
      ["CFTC 铝持仓", "CFTC COT", "周度", "catalog", "CFTC 官方周报；动态接入"],
      ["CFTC 布伦特原油持仓", "CFTC COT", "周度", "catalog", "CFTC 官方周报；动态接入"],
      ["CFTC 低硫柴油持仓", "CFTC COT", "周度", "catalog", "CFTC 官方周报；动态接入"],
      ["CFTC 高硫燃料油持仓", "CFTC COT", "周度", "catalog", "CFTC 官方周报；动态接入"],
      ["CFTC 日元持仓", "CFTC COT", "周度", "catalog", "CFTC 官方周报；动态接入"],
      ["CFTC 纳斯达克100持仓", "CFTC COT", "周度", "catalog", "CFTC 官方周报；动态接入"],
      ["CFTC 美债30Y持仓", "CFTC COT", "周度", "catalog", "CFTC 官方周报；动态接入"],
      ["CFTC 美债2Y持仓", "CFTC COT", "周度", "catalog", "CFTC 官方周报；动态接入"],
      ["CFTC 美债10Y持仓", "CFTC COT", "周度", "catalog", "CFTC 官方周报；动态接入"],
      ["VIX 恐慌指数", "CBOE / FRED", "日度", "connected", "本期已引用"],
      ["美股保证金融资", "FINRA", "月度", "catalog", "杠杆情绪"],
      ["韩国融资余额", "KRX", "日度", "catalog", "区域杠杆"],
      ["A股融资融券余额", "Exchange / User data", "日度", "catalog", "A股杠杆"],
      ["A股融资买入", "Exchange / User data", "日度", "catalog", "增量融资"],
      ["A股融资余额占比", "Exchange / User data", "日度", "catalog", "杠杆强度"],
      ["全球股票基金资金流", "EPFR", "周度", "catalog", "机构资金流"],
      ["北向 / 南向资金", "Exchange", "日度", "catalog", "跨境资金流"]
    ],
    L6: [
      ["美国联邦债务", "Treasury / FRED", "日度/季度", "catalog", "财政约束"],
      ["美国利息支出", "BEA / Treasury", "季度", "catalog", "财政约束"],
      ["美联储利率与前瞻", "FOMC", "会议/事件", "connected", "本期已引用"],
      ["日本央行利率与购债", "BOJ", "会议/事件", "connected", "本期已引用"],
      ["汇率干预状态", "MOF / Fed / News", "事件", "event", "日元尾部风险"],
      ["地缘政治风险", "Official / News", "事件", "event", "中东与能源溢价"]
    ]
  };

  const meta = {
    L1: ["流动性", "权重 30%", "#276aa1"],
    L2: ["经济周期", "权重 25%", "#b97c1f"],
    L3: ["通胀水平", "权重 20%", "#c64752"],
    L4: ["大类资产", "权重 15%", "#7565cf"],
    L5: ["资金情绪", "权重 7%", "#b84d82"],
    L6: ["政策与地缘", "权重 3%", "#168c78"]
  };

  const statusLabels = {
    connected: ["本期引用", "connected"], snapshot: ["截图快照", "snapshot"],
    catalog: ["监测目录", "catalog"], event: ["事件监测", "event"]
  };

  const layersHtml = layers.map((layer) => `
    <article class="dp-layer-card" style="--dp-layer:${layer.color};--dp-score:${layer.score}%">
      <div class="dp-layer-head">
        <div class="dp-layer-title"><span class="dp-layer-code">${layer.code}</span>${layer.title}</div>
        <span class="dp-weight">权重 ${layer.weight}%</span>
      </div>
      <div class="dp-layer-scoreline"><span class="dp-score-word">${layer.signal}</span><span class="dp-contribution">${layer.contribution}</span></div>
      <div class="dp-layer-track" aria-hidden="true"><span></span></div>
      <div class="dp-metrics">${layer.metrics.map(([name, value]) => `<div class="dp-metric"><span>${name}</span><strong>${value}</strong></div>`).join("")}</div>
      <p class="dp-asof">${layer.asof}</p>
    </article>`).join("");

  const groupsHtml = Object.entries(catalog).map(([code, rows], index) => {
    const [title, weight, color] = meta[code];
    const body = rows.map(([name, source, cadence, status, note]) => {
      const [label, cls] = statusLabels[status];
      const haystack = `${code} ${title} ${name} ${source} ${cadence} ${note}`.toLowerCase();
      return `<tr class="dp-data-row" data-layer="${code}" data-search="${esc(haystack)}">
        <td><strong>${name}</strong></td><td class="dp-source-code">${source}</td><td>${cadence}</td>
        <td><span class="dp-status ${cls}">${label}</span></td><td>${note}</td></tr>`;
    }).join("");
    return `<details class="dp-layer-group" data-layer-group="${code}" style="--dp-group:${color}" ${index === 0 ? "open" : ""}>
      <summary><span class="dp-group-code">${code}</span><span class="dp-group-title"><strong>${title}</strong><span>${weight}</span></span><span class="dp-group-count">${rows.length} 项</span></summary>
      <div class="dp-table-wrap"><table class="dp-data-table"><thead><tr><th>指标参数</th><th>数据源 / 代码</th><th>频率</th><th>状态</th><th>用途 / 口径</th></tr></thead><tbody>${body}</tbody></table></div>
    </details>`;
  }).join("");

  mount.className = "dp-extension";
  mount.innerHTML = `
    <!-- The calendar is rendered dynamically by dynamic-market.js. -->

    <section class="dp-section dp-anchor" id="indicators">
      <div class="container">
        <div class="section-head"><div><div class="section-kicker">Decision pyramid · Six layers</div><h2>六层指标塔：从流动性到政策</h2></div><p class="section-note">权重 30 / 25 / 20 / 15 / 7 / 3。每层先显示本期最有解释力的 4 个参数，再进入完整指标库。</p></div>
        <div class="dp-provenance"><span>ⓘ</span><div><strong>口径说明：</strong>“本期口径”来自当前 2026-08-25 简报；“截图指标”仅转录用户提供图片中的样本，并明确标为非实时。黄金六层贡献合计约 +46，白银约 +24，与首页综合评分一致。</div></div>
        <div class="dp-layer-grid">${layersHtml}</div>
      </div>
    </section>

    <!-- CFTC source breakdown is rendered by dynamic-market.js from the latest official data bundle. -->

    <section class="dp-section dp-anchor" id="data-library">
      <div class="container">
        <div class="section-head"><div><div class="section-kicker">Indicator library · 95 series</div><h2>六层数据明细库</h2></div><p class="section-note">覆盖截图中可见的 L1–L5 参数，并补齐 L6 政策事件。目录状态不等同于实时数据接口。</p></div>
        <div class="dp-library-shell">
          <div class="dp-toolbar">
            <label><span class="dp-mini-label">搜索指标</span><input class="dp-search" id="dpSearch" type="search" placeholder="例如：PCE、CFTC、美债10Y、RRP…" autocomplete="off"></label>
            <div><span class="dp-mini-label">筛选层级</span><div class="dp-filters" role="group" aria-label="按层级筛选"><button class="dp-filter" data-layer-filter="all" aria-pressed="true">全部</button>${Object.keys(catalog).map((code) => `<button class="dp-filter" data-layer-filter="${code}" aria-pressed="false">${code}</button>`).join("")}</div></div>
          </div>
          <div class="dp-library-meta"><span id="dpResultCount">95 / 95 项</span><span>本期引用 = 已进入本页分析；截图快照 = 仅保留报告日数值；监测目录 = 已纳入框架、待后续接入。</span></div>
          <div id="dpCatalogGroups">${groupsHtml}</div>
          <div class="dp-no-results" id="dpNoResults">没有匹配的指标，请尝试缩短关键词。</div>
        </div>
      </div>
    </section>`;

  const search = document.getElementById("dpSearch");
  const filters = [...mount.querySelectorAll("[data-layer-filter]")];
  const rows = [...mount.querySelectorAll(".dp-data-row")];
  const groups = [...mount.querySelectorAll("[data-layer-group]")];
  const resultCount = document.getElementById("dpResultCount");
  const noResults = document.getElementById("dpNoResults");
  let activeLayer = "all";

  const applyFilters = () => {
    const query = search.value.trim().toLowerCase();
    let visibleTotal = 0;
    groups.forEach((group) => {
      const groupLayer = group.dataset.layerGroup;
      let visibleInGroup = 0;
      group.querySelectorAll(".dp-data-row").forEach((row) => {
        const layerMatch = activeLayer === "all" || row.dataset.layer === activeLayer;
        const searchMatch = !query || row.dataset.search.includes(query);
        const visible = layerMatch && searchMatch;
        row.hidden = !visible;
        if (visible) visibleInGroup += 1;
      });
      group.hidden = visibleInGroup === 0;
      group.querySelector(".dp-group-count").textContent = `${visibleInGroup} 项`;
      if (query && visibleInGroup > 0) group.open = true;
      visibleTotal += visibleInGroup;
    });
    resultCount.textContent = `${visibleTotal} / ${rows.length} 项`;
    noResults.classList.toggle("visible", visibleTotal === 0);
  };

  search.addEventListener("input", applyFilters);
  filters.forEach((button) => button.addEventListener("click", () => {
    activeLayer = button.dataset.layerFilter;
    filters.forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
    applyFilters();
  }));
})();
