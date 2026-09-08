# 持仓与原油库存

独立页面：`/markets/positioning/`。市场主页仅增加导航入口，原行情、相关性及 CFTC 历史模块不变。

## 数据与口径

- CFTC 官方当前 Disaggregated / TFF **期货与期权合并**文件。按精确市场代码与名称匹配 29 个品种。
- 商品比较管理资金（Managed Money）；金融品种比较杠杆基金（Leveraged Funds）。五类明细保留原始多、空和净持仓。
- 净持仓 = 多头 − 空头；净/OI = 净持仓 ÷ 同一市场未平仓量；周度比率变化单位为百分点。
- NYMEX Brent Last Day 不代表 ICE 布伦特全市场，CME 加密合约不代表全市场加密仓位，铝 MWP 为升水合约。
- EIA WPSR Table 4 提供商业原油、SPR、库欣、汽油和馏分油库存（百万桶）；Table 9 提供炼厂利用率及原油加工/进口/出口（原表千桶/日转百万桶/日）。
- EIA 变化由同表相邻两周水平计算；由于源数据已四舍五入，与官方使用未舍入数据计算的变化可有 0.001 差异。库欣是商业库存子集，不能相加。
- WorkBuddy 仅为四板块框架参考，不从其中复制过期数值、身份分类或投资结论。

## 自动更新

现有 GitHub Actions 每 15 分钟尝试运行。研究数据仅每 **12 小时**检查官方源，周报自身并非实时数据。页面打开后每 15 分钟重新读取已缓存文件；不调用 AI，不消耗模型 token。

`report_date` / `week_ending` 是观测日期，`published_at` 是 EIA 页面核验的发布日期，`fetched_at` 是成功读取时间，`checked_at` 是最近尝试时间。来源失败保留最近成功值和原日期，标记 stale；首次失败 unavailable；不会以零替换未知值。当前报告超出正常周报窗口也会提示过旧。

## 验证与维护

```sh
python -m unittest discover -s tests -p 'test_*.py'
python scripts/update_research_data.py --force
python -m http.server 8766 --bind 127.0.0.1
# 已安装 Playwright 的环境：
node tests/positioning.browser.cjs
```

可设置 `MARKET_SITE_ROOT` 指向输出仓库；浏览器测试支持 `PLAYWRIGHT_MODULE`、`CHROME_PATH`、`SITE_URL` 与 `SCREENSHOT_DIR`。无需账号、API 密钥或付费订阅。部署只需 gh-pages 的普通非强制提交；更新脚本原子写入 `markets/data/research.json`，来源缓存互不覆盖。

本页描述持仓和库存，不是现金流统计或交易建议。没有新增价格图，原站 TradingView 行情约束保持不变。
