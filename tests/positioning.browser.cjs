const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const data = require('../markets/data/research.json');
const url = process.env.SITE_URL || 'http://127.0.0.1:8766/markets/positioning/';

(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) });
  try {
    for (const width of [1440, 390]) {
      const page = await browser.newPage({ viewport: { width, height: 980 } });
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      await page.goto(url, { waitUntil: 'networkidle' });
      await page.waitForSelector('[data-product]');
      assert.equal(await page.locator('#sectorTabs button').count(), 4);
      assert.equal(await page.locator('.inventory-card').count(), 5);
      assert.equal(await page.locator('.balance-card').count(), 4);
      for (const board of data.cftc.boards) {
        await page.locator(`[data-sector="${board.id}"]`).click();
        assert.equal(await page.locator('[data-product]').count(), board.products.length);
        for (const p of board.products) {
          await page.locator(`[data-product="${p.id}"]`).click();
          assert.equal(await page.locator('#productDetail h2').textContent(), p.name);
        }
      }
      await page.locator('[data-sector="metals"]').click();
      await page.locator('[data-product="gold"]').click();
      const dimensions = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth,
        negatives: [...document.querySelectorAll('.bar.negative')].map(x => x.getBoundingClientRect().width),
        negativeDown: [...document.querySelectorAll('.inv-fill.down')].every(x => Math.abs(x.getBoundingClientRect().top - (x.parentElement.getBoundingClientRect().top + x.parentElement.clientHeight / 2)) < 2),
        positiveUp: [...document.querySelectorAll('.inv-fill.up')].every(x => Math.abs(x.getBoundingClientRect().bottom - (x.parentElement.getBoundingClientRect().top + x.parentElement.clientHeight / 2)) < 2) }));
      assert(dimensions.scroll <= width + 1, `overflow ${JSON.stringify(dimensions)}`);
      assert(dimensions.negatives.every(x => x > 0), 'negative CFTC bars visible');
      assert(dimensions.negativeDown && dimensions.positiveUp, 'inventory zero baseline direction');
      await page.screenshot({ path: path.join(process.env.SCREENSHOT_DIR || '/private/tmp', `positioning-${width}.png`), fullPage: true });
      await page.locator('#themeToggle').click();
      assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');
      // Data values are untrusted; names must remain text, not HTML.
      await page.evaluate(d => {
        d.cftc.boards[0].products[0].name = '<img src=x onerror="window.injected=true">';
        d.cftc.boards[0].products[0].categories[0].name = '<script>bad()</script>';
        d.cftc.boards[0].products[0].source_url = 'javascript:alert(1)';
        window.PositioningResearch.render(d);
      }, structuredClone(data));
      assert.equal(await page.locator('#boardList img, #productDetail script').count(), 0);
      assert.equal(await page.locator('a[href^="javascript:"]').count(), 0);
      await page.evaluate(() => window.PositioningResearch.render({ cftc: {status: 'unavailable'}, eia: {status: 'unavailable'} }));
      assert.equal(await page.locator('[data-product]').count(), 0);
      assert.equal(await page.locator('.inv-fill').count(), 0);
      assert.deepEqual(errors, []);
      console.log(`PASS ${width}px: tabs/products, inventory sign, no overflow, escaped data, nulls, dark mode`);
      await page.close();
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
