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
        await page.waitForFunction(() => typeof Chart !== 'undefined' && !!Chart.getChart(document.querySelector('#chart')));
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

test('weather follows camera mappings, missing sensors and request races', { timeout: 120000 }, async () => {
    const browser = await chromium.launch({ headless: true });
    try {
        const page = await browser.newPage();
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        await page.goto(process.env.APP_URL || 'http://localhost:8004/');
        for (const [camera, station] of [
            ['rozcesti', 'bufet'], ['pec', 'pec'], ['bedrichov', 'pec'], ['bedriska', 'pec'],
            ['klinove-boudy', 'bufet'], ['lucni-bouda', 'lucni'], ['snezka', 'snezka'], ['svaty-petr', 'plan'],
        ]) {
            await page.locator(`#tab-${camera}`).click();
            await page.waitForFunction(id => state.weatherStation?.id === id
                && !document.querySelector('#weatherChip').hidden
                && document.querySelector('#weatherStationNote').textContent.includes('Čas dat:'), station);
            const note = await page.locator('#weatherStationNote').textContent();
            if (station === 'plan') assert.ok(note.includes('Modelový odhad'));
            else assert.ok(note.includes('Měření:'));
            if (['bedrichov', 'bedriska', 'klinove-boudy'].includes(camera)) assert.ok(note.includes('Sdílená stanice'));
            await page.locator('#weatherChip').click();
            await page.waitForFunction(() => typeof Chart !== 'undefined' && !!Chart.getChart(document.querySelector('#chart')));
            const label = await page.locator('#readerStation').textContent();
            if (station === 'pec') assert.ok(label.includes('Pec pod Sněžkou'));
            if (station === 'snezka') {
                assert.equal(await page.locator('[data-metric="uvi"]').isDisabled(), true);
                assert.equal(await page.locator('[data-metric="bar"]').isDisabled(), true);
            }
            await page.keyboard.press('Escape');
        }

        // Delayed Pec data must not overwrite a newer Luční bouda selection.
        let release;
        const gate = new Promise(resolve => { release = resolve; });
        let entered;
        const intercepted = new Promise(resolve => { entered = resolve; });
        await page.route('**/api/weather/current?camera=pec', async route => {
            entered();
            await gate;
            await route.continue();
        });
        await page.locator('#tab-pec').click();
        await intercepted;
        await page.locator('#tab-lucni-bouda').click();
        await page.waitForFunction(() => state.weatherStation?.id === 'lucni' && !document.querySelector('#weatherChip').hidden);
        const response = page.waitForResponse(r => r.url().includes('/api/weather/current?camera=pec'));
        release();
        await response;
        assert.equal(await page.evaluate(() => state.weatherStation.id), 'lucni');
        assert.ok((await page.locator('#weatherStationNote').textContent()).includes('Luční bouda'));

        await page.route('**/api/weather/current?camera=bedriska', route => route.fulfill({ status: 500, body: '{}' }));
        await page.locator('#tab-bedriska').click();
        await page.waitForFunction(() => document.querySelector('#weatherStationNote').textContent.includes('není dostupné'));
        assert.equal(await page.locator('#weatherChip').isHidden(), true);
        assert.ok((await page.locator('#weatherStationNote').textContent()).includes('Pec pod Sněžkou'));
        assert.deepEqual(errors, []);
    } finally {
        await browser.close();
    }
});

test('photos use responsive previews without waiting for chart CDN', { timeout: 60000 }, async () => {
    const browser = await chromium.launch({ headless: true });
    try {
        const page = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 });
        const requests = [];
        const errors = [];
        page.on('request', request => requests.push(request.url()));
        page.on('pageerror', error => errors.push(error.message));
        await page.route('**/cdn.jsdelivr.net/**', route => route.abort());
        await page.goto(process.env.APP_URL || 'http://localhost:8004/');
        await page.waitForFunction(() => {
            const image = document.querySelector('#heroImage');
            return image.complete && image.naturalWidth > 0 && image.style.opacity === '1';
        });
        const src = await page.locator('#heroImage').evaluate(image => image.currentSrc);
        assert.ok(src.includes('/previews/') && src.includes('width=640'), src);
        assert.equal(requests.some(url => new URL(url).hostname === 'cdn.jsdelivr.net'), false);
        assert.equal(requests.some(url => new URL(url).pathname.startsWith('/images/')), false);
        await page.locator('#heroFigure').click();
        await page.waitForFunction(() => document.querySelector('#lbImage').complete && document.querySelector('#lbImage').naturalWidth > 0);
        assert.ok((await page.locator('#lbImage').getAttribute('src')).startsWith('/images/'));
        await page.keyboard.press('Escape');
        await page.locator('#weatherChip').click();
        await page.waitForFunction(() => document.querySelector('#readerCoverage').textContent.includes('nepodařilo načíst'));
        assert.deepEqual(errors, []);
    } finally {
        await browser.close();
    }
});
