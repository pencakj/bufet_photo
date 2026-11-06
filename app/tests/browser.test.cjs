const assert = require('node:assert/strict');
const { test } = require('node:test');
const { chromium } = require('playwright');

test('release camera tabs, archives, charts and mobile layout', { timeout: 120000 }, async () => {
    const browser = await chromium.launch({ headless: true });
    try {
        const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        await page.goto(process.env.APP_URL || 'http://localhost:8004/');
        await page.waitForFunction(() => document.querySelector('#heroImage').naturalWidth > 0);
        assert.equal(await page.getByRole('tab').count(), 8);
        assert.equal(await page.getByRole('tab').first().getAttribute('aria-selected'), 'true');

        const ids = ['rozcesti', 'pec', 'lucni-bouda', 'snezka', 'klinove-boudy', 'svaty-petr', 'bedrichov', 'bedriska'];
        for (const id of ids) {
            await page.locator(`#tab-${id}`).click();
            await page.waitForFunction(camera => {
                const image = document.querySelector('#heroImage');
                return image.getAttribute('src')?.includes(`camera=${camera}`) && image.complete && image.naturalWidth > 0;
            }, id);
            assert.equal(await page.locator(`#tab-${id}`).getAttribute('aria-selected'), 'true');
            assert.equal(await page.locator('#cameraPanel').getAttribute('aria-labelledby'), `tab-${id}`);
            assert.ok(Number((await page.locator('#totalCount').textContent()).replace(/\D/g, '')) > 0);
            await page.locator('#heroFigure').click();
            assert.ok((await page.locator('#lbImage').getAttribute('src')).includes(`camera=${id}`));
            await page.keyboard.press('Escape');
        }

        // Switching before fetches finish must never mix camera archives.
        await page.evaluate(() => {
            selectCamera('pec');
            selectCamera('lucni-bouda');
            selectCamera('snezka');
        });
        await page.waitForFunction(() => !state.loading && state.camera === 'snezka' && state.images.length > 0);
        assert.ok((await page.locator('#heroImage').getAttribute('src')).includes('camera=snezka'));
        const thumbnailUrls = await page.locator('.frame img').evaluateAll(images => images.map(image => image.dataset.src));
        assert.ok(thumbnailUrls.length > 0 && thumbnailUrls.every(url => url.includes('camera=snezka')));

        await page.locator('#sortToggle').click();
        await page.waitForFunction(() => !state.loading && state.order === 'asc');
        await page.locator('#themeToggle').click();
        await page.locator('#weatherChip').click();
        await page.waitForFunction(() => !!Chart.getChart(document.querySelector('#chart')));
        const axis = await page.evaluate(() => {
            const chart = Chart.getChart(document.querySelector('#chart'));
            const scale = chart.scales.y;
            const values = chart.data.datasets[0].data.filter(value => typeof value === 'number' && Number.isFinite(value));
            return {
                min: scale.min, max: scale.max,
                dataMin: Math.min(...values), dataMax: Math.max(...values),
                fixedMin: chart.config.options.scales.y.min,
                fixedMax: chart.config.options.scales.y.max,
            };
        });
        assert.equal(axis.fixedMin, undefined);
        assert.equal(axis.fixedMax, undefined);
        assert.ok(axis.min <= axis.dataMin && axis.max >= axis.dataMax, JSON.stringify(axis));
        assert.ok(axis.max - axis.min <= (axis.dataMax - axis.dataMin) * 2 + 10, JSON.stringify(axis));
        await page.keyboard.press('Escape');

        await page.setViewportSize({ width: 390, height: 844 });
        await page.locator('#tab-rozcesti').click();
        await page.locator('#tab-rozcesti').focus();
        await page.keyboard.press('End');
        assert.equal(await page.locator('#tab-bedriska').getAttribute('aria-selected'), 'true');
        await page.waitForFunction(() => !state.loading && state.camera === 'bedriska');
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
        assert.deepEqual(errors, []);
    } finally {
        await browser.close();
    }
});
