const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

function render(metric, values) {
    let config;
    const context = vm.createContext({
        localStorage: { getItem: () => null, setItem: () => {} },
        window: { matchMedia: () => ({ matches: false }) },
        document: {
            documentElement: { setAttribute() {}, getAttribute: () => 'light' },
            addEventListener() {},
            getElementById: () => ({ getContext: () => ({}) }),
        },
        IntersectionObserver: class {},
        Chart: class {
            constructor(ctx, options) { config = options; }
        },
    });
    vm.runInContext(readFileSync(join(__dirname, '../static/app.js'), 'utf8'), context);
    context.metric = metric;
    context.records = values.map((value, i) => ({
        timestamp: `2026-11-06T${String(i).padStart(2, '0')}:00:00`,
        [metric]: value,
    }));
    vm.runInContext('chartsReady = true; state.metric = metric; state.weatherRecords = records; renderChart();', context);
    return config;
}

test('temperature uses automatic limits and padding for every data range', () => {
    for (const values of [[-5, 0, 5], [18, 22], [-15, -10], [4, 4], [0], [], [null, 3]]) {
        const config = render('temp', values);
        const axis = config.options.scales.y;
        assert.equal(axis.min, undefined);
        assert.equal(axis.max, undefined);
        assert.equal(axis.grace, '10%');
        assert.deepEqual(Array.from(config.data.datasets[0].data), values);
        assert.equal(axis.ticks.callback(5), '5°C');
    }
});

test('other metrics retain their existing axis limits', () => {
    for (const [metric, min, max] of [
        ['hum', 0, 100], ['wspd', 0, null], ['bar', null, null],
        ['rain', 0, null], ['solarrad', 0, null], ['uvi', 0, 12],
    ]) {
        const axis = render(metric, [1, 2]).options.scales.y;
        assert.equal(axis.min, min);
        assert.equal(axis.max, max);
        assert.equal(axis.grace, 0);
    }
});
