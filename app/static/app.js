// Krkonoše Live v3 — camera-scoped alpine archive

const state = {
    camera: 'rozcesti',
    cameras: new Map(),
    generation: 0,
    controller: null,
    todayCount: 0,
    images: [],
    offset: 0,
    batch: 50,
    total: 0,
    hasMore: true,
    loading: false,
    order: localStorage.getItem('kl_order_v2') || 'desc',
    currentIndex: 0,
    metric: 'temp',
    metricWindow: 24,
    weatherRecords: [],
    weatherStation: null,
    weatherRequest: 0,
    weatherHistoryRequest: 0,
    weatherRetry: null,
    renderedChapters: new Map(), // day -> {head, grid} elements
};

const metricConfig = {
    temp: { title: 'Temperature', unit: '°C', color: '#b45309' },
    hum: { title: 'Humidity', unit: '%', color: '#2563eb', min: 0, max: 100 },
    wspd: { title: 'Wind speed', unit: ' m/s', color: '#7c3aed', min: 0, max: null },
    bar: { title: 'Atmospheric pressure', unit: ' hPa', color: '#0891b2', min: null, max: null },
    rain: { title: 'Rainfall', unit: ' mm', color: '#0284c7', min: 0, max: null },
    solarrad: { title: 'Solar radiation', unit: ' W/m²', color: '#f59e0b', min: 0, max: null },
    uvi: { title: 'UV index', unit: '', color: '#dc2626', min: 0, max: 12 },
};

let chart = null;
let chartLibraries = null;
let chartsReady = false;

function loadChartScript(src, integrity) {
    return new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = src;
        script.integrity = integrity;
        script.crossOrigin = 'anonymous';
        script.onload = resolve;
        script.onerror = () => { script.remove(); reject(new Error('Chart library unavailable')); };
        document.head.appendChild(script);
    });
}

function ensureChartLibraries() {
    if (!chartLibraries) {
        chartLibraries = (async () => {
            await loadChartScript('https://cdn.jsdelivr.net/npm/chart.js@4.6.1/dist/chart.umd.min.js', 'sha384-Emf5ZVIUiarAdhkgtqK+5/Z5qIvM6QoVrS+qAVtfyZVuD5lIHrac0me485+Antp0');
            await loadChartScript('https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js', 'sha384-cVMg8E3QFwTvGCDuK+ET4PD341jF3W8nO1auiXfuZNQkzbUUiBGLsIQUE+b1mxws');
            chartsReady = true;
        })().catch(error => { chartLibraries = null; throw error; });
    }
    return chartLibraries;
}

// Theme
function initTheme() {
    const saved = localStorage.getItem('kl_theme_v2');
    const prefers = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const theme = saved || (prefers ? 'dark' : 'light');
    document.documentElement.setAttribute('data-theme', theme);
}

function toggleTheme() {
    const cur = document.documentElement.getAttribute('data-theme') || 'light';
    const next = cur === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('kl_theme_v2', next);
}

// Helpers
const $ = (id) => document.getElementById(id);

function formatDate(iso) {
    const d = new Date(iso + 'T00:00:00');
    return d.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
}

function formatTimeOnly(ts) { return ts.split(' ')[1]; }

// Weather chip
async function loadWeather() {
    if (state.weatherRetry) clearTimeout(state.weatherRetry);
    const camera = state.camera;
    const request = ++state.weatherRequest;
    try {
        const r = await fetch(`/api/weather/current?camera=${encodeURIComponent(camera)}`);
        if (!r.ok) throw new Error('Weather unavailable');
        const j = await r.json();
        if (request !== state.weatherRequest || camera !== state.camera) return;
        state.weatherStation = j.station;
        showWeatherStation(j.station, [
            j.observed_at ? `Čas dat: ${weatherTime(j.observed_at)}` : 'Čekám na data ze zdroje.',
            j.stale ? 'Pozor: data chybí nebo jsou starší než 2 hodiny.' : '',
            j.error || '',
        ].filter(Boolean).join(' · '));
        $('weatherChip').hidden = !j.data;
        if (j.success && j.data) renderWeatherChip(j.data);
        updateMetricAvailability(j.available_metrics || []);
        if (!j.data) {
            state.weatherRetry = setTimeout(() => { if (state.camera === camera) loadWeather(); }, 30000);
        }
    } catch (e) {
        if (request !== state.weatherRequest || camera !== state.camera) return;
        $('weatherChip').hidden = true;
        showWeatherStation(state.weatherStation, 'Počasí nyní není dostupné.');
    }
}

function weatherTime(value) {
    return new Date(value).toLocaleString('cs-CZ', { timeZone: 'Europe/Prague' });
}

function showWeatherStation(station, status = '') {
    if (!station) {
        $('weatherStationNote').textContent = status || 'Načítám zdroj počasí…';
        $('weatherSource').hidden = true;
        return;
    }
    const label = station.kind === 'model' ? 'Modelový odhad' : 'Měření';
    $('weatherStationNote').textContent = `${label}: ${station.name} · ${station.note} ${status}`;
    $('weatherSource').textContent = `Zdroj: ${station.attribution} ↗`;
    $('weatherSource').href = station.url;
    $('weatherSource').hidden = false;
    $('weatherChip').title = `${label}: ${station.name}`;
    $('readerStation').textContent = `${label} · ${station.name} · ${station.provider}`;
}

function updateMetricAvailability(metrics) {
    document.querySelectorAll('#metricPills .pill').forEach(button => {
        button.disabled = !metrics.includes(button.dataset.metric);
        button.title = button.disabled ? 'Zdroj tento údaj pro dané období neposkytuje.' : '';
    });
    if (!metrics.includes(state.metric)) state.metric = 'temp';
    document.querySelectorAll('#metricPills .pill').forEach(button => {
        button.classList.toggle('active', button.dataset.metric === state.metric);
    });
}

function renderWeatherChip(d) {
    const chip = $('weatherChip');
    $('chipTemp').textContent = '—';
    $('chipMin').textContent = '—';
    $('chipMax').textContent = '—';
    $('chipHum').textContent = d.humidity != null ? d.humidity + '%' : '—';
    $('chipWind').textContent = d.wind_speed != null ? d.wind_speed.toFixed(1) + ' m/s' : '—';
    $('chipWindArrow').hidden = d.wind_dir == null;
    if (d.temp && d.temp.current != null) {
        $('chipTemp').textContent = d.temp.current.toFixed(1) + '°';
        $('chipMin').textContent = d.temp.min.toFixed(1) + '°';
        $('chipMax').textContent = d.temp.max.toFixed(1) + '°';
    }
    if (d.humidity != null) $('chipHum').textContent = d.humidity + '%';
    if (d.wind_speed != null) $('chipWind').textContent = d.wind_speed.toFixed(1) + ' m/s';
    if (d.wind_dir != null) {
        $('chipWindArrow').style.transform = `rotate(${d.wind_dir}deg)`;
    }
    chip.hidden = false;
}

// Camera tabs
function imageUrl(filename, camera = state.camera) {
    return `/images/${encodeURIComponent(filename)}?camera=${encodeURIComponent(camera)}`;
}

function thumbUrl(filename, camera = state.camera) {
    return `/thumbnails/${encodeURIComponent(filename)}?camera=${encodeURIComponent(camera)}`;
}

function previewUrl(filename, width, camera = state.camera) {
    return `/previews/${encodeURIComponent(filename)}?camera=${encodeURIComponent(camera)}&width=${width}&v=1`;
}

async function loadCameras() {
    try {
        const response = await fetch('/api/cameras');
        if (!response.ok) throw new Error('Camera status unavailable');
        const data = await response.json();
        state.cameras = new Map(data.cameras.map(camera => [camera.id, camera]));
        updateCameraInfo();
        // A tab opened before its first capture should recover without a reload.
        if (!state.images.length && !state.loading && state.cameras.get(state.camera)?.total > 0) {
            resetArchive();
            loadMore();
        }
    } catch (error) {
        $('cameraStatus').textContent = 'Camera status unavailable; archive remains accessible.';
    }
}

function updateCameraInfo() {
    const camera = state.cameras.get(state.camera);
    if (!camera) return;
    $('heroPlace').textContent = camera.location;
    $('cameraSource').textContent = `Source: ${camera.provider} ↗`;
    $('cameraSource').href = camera.source_page;
    const latest = camera.latest ? `Last capture: ${camera.latest.formatted_time}` : 'Waiting for the first capture';
    $('cameraStatus').textContent = camera.last_error
        ? `${latest} · ${camera.last_error}`
        : `${latest}${camera.read_only ? ' · Shared production archive (read-only)' : ''}`;
}

function selectCamera(camera) {
    if (camera === state.camera) return;
    state.camera = camera;
    document.querySelectorAll('.camera-tab').forEach(tab => {
        const selected = tab.dataset.camera === camera;
        tab.classList.toggle('active', selected);
        tab.setAttribute('aria-selected', String(selected));
        tab.tabIndex = selected ? 0 : -1;
    });
    $('cameraPanel').setAttribute('aria-labelledby', `tab-${camera}`);
    closeLightbox();
    closeReader();
    state.weatherHistoryRequest += 1;
    state.weatherRecords = [];
    if (chart) { chart.destroy(); chart = null; }
    state.weatherStation = state.cameras.get(camera)?.weather || null;
    $('weatherChip').hidden = true;
    showWeatherStation(state.weatherStation, 'Načítám data…');
    loadWeather();
    resetArchive();
    updateCameraInfo();
    loadMore();
}

// Image archive: generation IDs prevent stale responses after tab/sort changes.
async function loadMore() {
    if (state.loading || !state.hasMore) return;
    state.loading = true;
    const generation = state.generation;
    state.controller = new AbortController();
    $('loading').hidden = false;
    try {
        const r = await fetch(`/api/images?camera=${encodeURIComponent(state.camera)}&offset=${state.offset}&limit=${state.batch}&order=${state.order}`, { signal: state.controller.signal });
        if (!r.ok) throw new Error('Archive unavailable');
        const j = await r.json();
        if (generation !== state.generation) return;
        state.total = j.total;
        state.todayCount = j.today_count;
        updateNumbers();
        if (j.images && j.images.length) {
            state.images.push(...j.images);
            state.offset += j.images.length;
            state.hasMore = j.has_more;
            if (state.images.length === j.images.length) renderHero(state.images[0]);
            renderNewImages(j.images);
        } else {
            state.hasMore = false;
            if (!state.images.length) {
                $('heroPlate').textContent = 'Waiting for capture';
                $('archiveMessage').textContent = 'No photographs yet. The first capture will appear after collection completes.';
                $('archiveMessage').hidden = false;
            }
        }
    } catch (e) {
        if (generation !== state.generation || e.name === 'AbortError') return;
        console.error('Failed to load images:', e);
        $('archiveMessage').textContent = 'Could not load this archive. Switch tabs or refresh to retry.';
        $('archiveMessage').hidden = false;
    } finally {
        if (generation === state.generation) {
            state.loading = false;
            $('loading').hidden = true;
        }
    }
}

function updateNumbers() {
    $('totalCount').textContent = state.total.toLocaleString('cs-CZ');
    $('todayCount').textContent = (state.todayCount || 0).toLocaleString('cs-CZ');
}

function renderHero(img) {
    const heroImg = $('heroImage');
    heroImg.style.opacity = 0;
    heroImg.alt = `Photograph from ${img.formatted_time}`;
    heroImg.onload = () => {
        heroImg.style.opacity = 1;
    };
    heroImg.onerror = () => {
        heroImg.onerror = null;
        heroImg.removeAttribute('srcset');
        heroImg.src = imageUrl(img.path);
    };
    heroImg.fetchPriority = 'high';
    heroImg.decoding = 'async';
    heroImg.sizes = '(max-width: 700px) calc(100vw - 32px), 1200px';
    heroImg.srcset = `${previewUrl(img.path, 640)} 640w, ${previewUrl(img.path, 1280)} 1280w`;
    heroImg.src = previewUrl(img.path, 1280);
    $('heroTime').textContent = img.formatted_time;
    $('heroPlate').textContent = state.order === 'desc' ? 'Most recent' : 'Earliest';
    $('heroNum').textContent = (state.total || '—').toString();
    $('heroFigure').onclick = () => openLightbox(0);
}

function renderNewImages(images) {
    const archive = $('archive');

    images.forEach((img) => {
        let chapter = state.renderedChapters.get(img.day);
        if (!chapter) {
            chapter = createChapter(img.day);
            state.renderedChapters.set(img.day, chapter);
            archive.appendChild(chapter.root);
        }

        const frame = document.createElement('button');
        frame.className = 'frame';
        frame.type = 'button';
        const globalIndex = state.images.indexOf(img);
        frame.onclick = () => openLightbox(globalIndex);

        const el = document.createElement('img');
        el.dataset.src = thumbUrl(img.thumb_path);
        el.dataset.original = imageUrl(img.path);
        el.dataset.filename = img.path;
        el.dataset.camera = state.camera;
        el.alt = img.formatted_time;
        el.loading = 'lazy';

        const time = document.createElement('span');
        time.className = 'frame-time';
        time.textContent = formatTimeOnly(img.formatted_time);

        frame.appendChild(el);
        frame.appendChild(time);
        chapter.grid.appendChild(frame);
        chapter.count += 1;
        chapter.counter.textContent = `${chapter.count} frame${chapter.count === 1 ? '' : 's'}`;

        thumbObserver.observe(el);
    });
}

function createChapter(day) {
    const root = document.createElement('section');
    root.className = 'chapter';

    const head = document.createElement('div');
    head.className = 'chapter-head';

    const date = document.createElement('h4');
    date.className = 'chapter-date';
    date.textContent = formatDate(day);

    const counter = document.createElement('span');
    counter.className = 'chapter-count';
    counter.textContent = '1 frame';

    head.appendChild(date);
    head.appendChild(counter);

    const grid = document.createElement('div');
    grid.className = 'chapter-grid';

    root.appendChild(head);
    root.appendChild(grid);

    return { root, grid, counter, count: 0 };
}

const thumbObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
        if (entry.isIntersecting) {
            const img = entry.target;
            img.src = img.dataset.src;
            img.onload = () => img.classList.add('loaded');
            img.onerror = () => {
                // Only one generation attempt; read-only archives fall back to JPEG.
                img.onerror = null;
                fetch(`/api/generate-thumbnail/${encodeURIComponent(img.dataset.filename)}?camera=${encodeURIComponent(img.dataset.camera)}`)
                    .then(response => {
                        img.src = response.ok ? img.dataset.src + '&retry=' + Date.now() : img.dataset.original;
                    }).catch(() => { img.src = img.dataset.original; });
            };
            thumbObserver.unobserve(img);
        }
    }
}, { rootMargin: '300px' });

const sentinelObserver = new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting) loadMore();
}, { rootMargin: '400px' });

// Sort
function toggleSort() {
    state.order = state.order === 'desc' ? 'asc' : 'desc';
    localStorage.setItem('kl_order_v2', state.order);
    applySortLabel();
    resetArchive();
    loadMore();
}

function applySortLabel() {
    $('sortLabel').textContent = state.order === 'desc' ? 'Newest first' : 'Oldest first';
    $('sortArrow').textContent = state.order === 'desc' ? '↓' : '↑';
}

function resetArchive() {
    if (state.controller) state.controller.abort();
    state.generation += 1;
    state.loading = false;
    state.total = 0;
    state.todayCount = 0;
    updateNumbers();
    thumbObserver.disconnect();
    state.images = [];
    state.offset = 0;
    state.hasMore = true;
    state.renderedChapters.clear();
    $('archive').innerHTML = '';
    $('archiveMessage').hidden = true;
    $('heroImage').removeAttribute('src');
    $('heroImage').removeAttribute('srcset');
    $('heroImage').alt = '';
    $('heroImage').style.opacity = 0;
    $('heroFigure').onclick = null;
    $('heroTime').textContent = '—';
    $('heroNum').textContent = '—';
    $('heroPlate').textContent = 'Loading…';
}

// Lightbox
function openLightbox(index) {
    state.currentIndex = index;
    const img = state.images[index];
    if (!img) return;
    $('lbImage').src = imageUrl(img.path);
    $('lbCaption').textContent = img.formatted_time;
    $('lightbox').hidden = false;
    document.body.style.overflow = 'hidden';
}

function closeLightbox() {
    $('lightbox').hidden = true;
    document.body.style.overflow = '';
}

function navigate(dir) {
    const n = state.images.length;
    if (!n) return;
    state.currentIndex = (state.currentIndex + dir + n) % n;
    const img = state.images[state.currentIndex];
    $('lbImage').src = imageUrl(img.path);
    $('lbCaption').textContent = img.formatted_time;
}

// Weather reader
async function openReader() {
    $('reader').hidden = false;
    document.body.style.overflow = 'hidden';
    $('readerCoverage').textContent = 'Načítám graf…';
    try {
        await ensureChartLibraries();
    } catch (error) {
        $('readerCoverage').textContent = 'Knihovnu grafů se nepodařilo načíst. Zavřete a otevřete graf pro opakování.';
        return;
    }
    if ($('reader').hidden) return;
    await loadWeatherRange(state.metricWindow);
}

function closeReader() {
    $('reader').hidden = true;
    document.body.style.overflow = '';
}

async function loadWeatherRange(hours) {
    state.metricWindow = hours;
    const camera = state.camera;
    const request = ++state.weatherHistoryRequest;
    state.weatherRecords = [];
    if (chart) { chart.destroy(); chart = null; }
    $('readerCoverage').textContent = 'Načítám historii…';
    try {
        const r = await fetch(`/api/weather/history?camera=${encodeURIComponent(camera)}&hours=${hours}`);
        if (!r.ok) throw new Error('Weather history unavailable');
        const j = await r.json();
        if (request !== state.weatherHistoryRequest || camera !== state.camera) return;
        state.weatherStation = j.station;
        state.weatherRecords = j.success ? j.data : [];
        const metrics = Object.keys(metricConfig).filter(metric => state.weatherRecords.some(row => typeof row[metric] === 'number'));
        updateMetricAvailability(metrics);
        $('readerStation').textContent = `${j.station.kind === 'model' ? 'Modelový odhad' : 'Měření'} · ${j.station.name}`;
        $('readerCoverage').textContent = j.coverage_start
            ? `Dostupná data: ${weatherTime(j.coverage_start)} – ${weatherTime(j.coverage_end)}. Chybějící měření se nedoplňují odhadem.`
            : 'Pro toto období zatím nejsou dostupná data.';
    } catch (e) {
        if (request !== state.weatherHistoryRequest || camera !== state.camera) return;
        state.weatherRecords = [];
        $('readerCoverage').textContent = 'Historii počasí se nepodařilo načíst.';
    }
    renderChart();
}

function renderChart() {
    if (!chartsReady) return;
    const cfg = { ...metricConfig[state.metric] };
    if (state.metric === 'rain' && state.weatherStation) {
        cfg.title = state.weatherStation.rain_interval_minutes
            ? `Rainfall / ${state.weatherStation.rain_interval_minutes} min` : 'Rainfall (station counter)';
    }
    if (state.metric === 'bar' && state.weatherStation && state.weatherStation.id !== 'bufet') cfg.title = 'Station pressure';
    $('readerTitle').textContent = cfg.title;
    const ctx = $('chart').getContext('2d');
    if (chart) chart.destroy();

    const data = state.weatherRecords;
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const axisColor = isDark ? '#a8a29e' : '#78716c';
    const gridColor = isDark ? 'rgba(245,240,230,0.06)' : 'rgba(28,25,23,0.06)';

    chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.map(d => new Date(d.timestamp)),
            datasets: [{
                label: `${cfg.title}${cfg.unit ? ' (' + cfg.unit.trim() + ')' : ''}`,
                data: data.map(d => typeof d[state.metric] === 'number' ? d[state.metric] : null),
                borderColor: cfg.color,
                backgroundColor: cfg.color + '22',
                fill: true,
                tension: 0.35,
                pointRadius: 0,
                pointHoverRadius: 4,
                borderWidth: 2,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: axisColor, font: { family: 'JetBrains Mono' } } },
                tooltip: {
                    backgroundColor: isDark ? '#1c1917' : '#ffffff',
                    titleColor: isDark ? '#f5f0e6' : '#1c1917',
                    bodyColor: isDark ? '#c5bda8' : '#57534e',
                    borderColor: isDark ? '#2f2a22' : '#d6c9ae',
                    borderWidth: 1,
                    padding: 10,
                    titleFont: { family: 'JetBrains Mono', size: 13 },
                    bodyFont: { family: 'Inter', size: 12 },
                }
            },
            scales: {
                x: {
                    type: 'time',
                    time: { displayFormats: { hour: 'HH:mm', day: 'd MMM' } },
                    ticks: { color: axisColor, font: { family: 'JetBrains Mono', size: 10 } },
                    grid: { color: gridColor }
                },
                y: {
                    min: cfg.min,
                    max: cfg.max,
                    grace: state.metric === 'temp' ? '10%' : 0,
                    ticks: { color: axisColor, font: { family: 'JetBrains Mono', size: 10 }, callback: v => v + cfg.unit },
                    grid: { color: gridColor }
                }
            }
        }
    });
}

// Bind
function bind() {
    const tabs = [...document.querySelectorAll('.camera-tab')];
    tabs.forEach((tab, index) => {
        tab.addEventListener('click', () => selectCamera(tab.dataset.camera));
        tab.addEventListener('keydown', event => {
            let next;
            if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
            else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
            else if (event.key === 'Home') next = 0;
            else if (event.key === 'End') next = tabs.length - 1;
            else return;
            event.preventDefault();
            tabs[next].focus();
            selectCamera(tabs[next].dataset.camera);
        });
    });
    $('themeToggle').addEventListener('click', toggleTheme);
    $('sortToggle').addEventListener('click', toggleSort);
    $('weatherChip').addEventListener('click', openReader);

    $('lbClose').addEventListener('click', closeLightbox);
    $('lbPrev').addEventListener('click', () => navigate(-1));
    $('lbNext').addEventListener('click', () => navigate(1));
    $('lightbox').addEventListener('click', (e) => { if (e.target.id === 'lightbox') closeLightbox(); });

    $('readerClose').addEventListener('click', closeReader);
    $('reader').addEventListener('click', (e) => { if (e.target.id === 'reader') closeReader(); });

    document.querySelectorAll('#metricPills .pill').forEach(b => {
        b.addEventListener('click', () => {
            document.querySelectorAll('#metricPills .pill').forEach(x => x.classList.remove('active'));
            b.classList.add('active');
            state.metric = b.dataset.metric;
            renderChart();
        });
    });

    document.querySelectorAll('#rangePills .pill').forEach(b => {
        b.addEventListener('click', async () => {
            document.querySelectorAll('#rangePills .pill').forEach(x => x.classList.remove('active'));
            b.classList.add('active');
            await loadWeatherRange(parseInt(b.dataset.hours, 10));
        });
    });

    document.addEventListener('keydown', (e) => {
        if (!$('lightbox').hidden) {
            if (e.key === 'Escape') closeLightbox();
            if (e.key === 'ArrowLeft') navigate(-1);
            if (e.key === 'ArrowRight') navigate(1);
        } else if (!$('reader').hidden) {
            if (e.key === 'Escape') closeReader();
        }
    });
}

// Boot
initTheme();
document.addEventListener('DOMContentLoaded', () => {
    bind();
    applySortLabel();
    loadWeather();
    setInterval(loadWeather, 300000);
    loadCameras();
    setInterval(loadCameras, 60000);
    loadMore();
    sentinelObserver.observe($('sentinel'));
});
