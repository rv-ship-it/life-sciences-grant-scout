let allOpportunities = [];
let filteredOpportunities = [];

async function init() {
    try {
        const resp = await fetch('data/opportunities.json?t=' + Date.now());
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();

        allOpportunities = data.opportunities || [];
        renderSummary(data);
        populateFilterDropdowns(allOpportunities);
        applyFilters();
    } catch (e) {
        document.getElementById('results').innerHTML =
            '<div class="loading">No data found. Run the pipeline first or click Refresh.</div>';
    }

    // Check if a refresh is already running (e.g. page reloaded mid-refresh)
    try {
        const statusResp = await fetch('/api/status');
        const status = await statusResp.json();
        if (status.state === 'running') {
            setRefreshingState(true);
            showRefreshOverlay('Refresh in progress...', 'Please wait.');
            startPolling();
        }
    } catch (e) {
        // Status endpoint not available -- ignore
    }
}

function renderSummary(data) {
    const opps = data.opportunities || [];
    document.getElementById('stat-total').textContent = data.count || opps.length;
    document.getElementById('stat-priority').textContent =
        opps.filter(o => o.high_priority).length;
    document.getElementById('stat-startup').textContent =
        opps.filter(o => o.startup_eligible).length;
    document.getElementById('stat-consortium').textContent =
        opps.filter(o => o.consortium_eligible).length;
    document.getElementById('stat-date').textContent = data.generated_at || '--';
}

function populateFilterDropdowns(opps) {
    const sources = [...new Set(opps.map(o => o.source))].sort();
    populateSelect('filter-source', sources);

    const topics = [...new Set(opps.flatMap(o => o.matched_topics || []))].sort();
    populateSelect('filter-topic', topics);
}

function populateSelect(id, values) {
    const select = document.getElementById(id);
    const defaultOption = select.options[0];
    select.innerHTML = '';
    select.appendChild(defaultOption);
    values.forEach(v => {
        const opt = document.createElement('option');
        opt.value = v;
        opt.textContent = v;
        select.appendChild(opt);
    });
}

function renderResults(opps) {
    const container = document.getElementById('results');
    if (opps.length === 0) {
        container.innerHTML = '<div class="loading">No matching grants found.</div>';
        return;
    }
    container.innerHTML = opps.map(renderCard).join('');
}

function renderCard(opp) {
    const badges = [];
    if (opp.high_priority) badges.push('<span class="badge badge-priority">HIGH PRIORITY</span>');
    if (opp.startup_eligible) badges.push('<span class="badge badge-startup">STARTUP</span>');
    if (opp.consortium_eligible) badges.push('<span class="badge badge-consortium">CONSORTIUM</span>');

    const deadlineStr = opp.deadline || 'Rolling/TBD';
    const awardStr = opp.award_ceiling
        ? `${opp.currency || 'USD'} ${Number(opp.award_ceiling).toLocaleString()}`
        : '';
    const topics = (opp.matched_topics || []).slice(0, 4).join(', ');
    const desc = (opp.description || '').substring(0, 200);

    const scoreColor = opp.combined_score > 60 ? '#22c55e'
        : opp.combined_score > 30 ? '#eab308' : '#9ca3af';

    const escapedId = opp.id.replace(/'/g, "\\'");

    return `
    <div class="card" onclick="showModal('${escapedId}')">
        <div class="card-header">
            <div class="badges">${badges.join(' ')}</div>
            <div class="score-bar">
                <div class="score-fill" style="width:${Math.min(opp.combined_score, 100)}%;background:${scoreColor}"></div>
                <span class="score-label">${opp.combined_score}</span>
            </div>
        </div>
        <h3 class="card-title">${escapeHtml(opp.title)}</h3>
        <div class="card-meta">
            <span>${escapeHtml(opp.source)}</span> &middot;
            <span>${escapeHtml(opp.agency)}</span> &middot;
            <span>Deadline: ${escapeHtml(deadlineStr)}</span>
            ${awardStr ? ` &middot; <span>${escapeHtml(awardStr)}</span>` : ''}
        </div>
        ${topics ? `<div class="card-topics">${escapeHtml(topics)}</div>` : ''}
        <p class="card-desc">${escapeHtml(desc)}${desc.length >= 200 ? '...' : ''}</p>
    </div>`;
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function updateResultCount(count) {
    document.getElementById('result-count').textContent = `${count} results`;
}

// Wire up event listeners
document.addEventListener('DOMContentLoaded', () => {
    init();

    document.getElementById('search-box').addEventListener('input', applyFilters);
    document.getElementById('filter-source').addEventListener('change', applyFilters);
    document.getElementById('filter-topic').addEventListener('change', applyFilters);
    document.getElementById('filter-eligibility').addEventListener('change', applyFilters);
    document.getElementById('sort-by').addEventListener('change', applyFilters);
    document.getElementById('filter-priority').addEventListener('change', applyFilters);
    document.getElementById('modal-close').addEventListener('click', closeModal);
    document.getElementById('detail-modal').addEventListener('click', (e) => {
        if (e.target.classList.contains('modal-overlay')) closeModal();
    });
    document.getElementById('refresh-btn').addEventListener('click', refreshData);
});

// --- Refresh functionality ---

let refreshPollingInterval = null;

function refreshData() {
    setRefreshingState(true);
    showRefreshOverlay('Fetching grants from all sources...', 'This may take 1-2 minutes.');

    fetch('/api/refresh', { method: 'POST' })
        .then(resp => resp.json())
        .then(data => {
            if (data.state === 'running') {
                startPolling();
            }
        })
        .catch(err => {
            hideRefreshOverlay();
            setRefreshingState(false);
            alert('Failed to start refresh: ' + err.message);
        });
}

function startPolling() {
    if (refreshPollingInterval) return;
    refreshPollingInterval = setInterval(checkRefreshStatus, 3000);
}

function stopPolling() {
    if (refreshPollingInterval) {
        clearInterval(refreshPollingInterval);
        refreshPollingInterval = null;
    }
}

function checkRefreshStatus() {
    fetch('/api/status')
        .then(resp => resp.json())
        .then(data => {
            if (data.state === 'done') {
                stopPolling();
                hideRefreshOverlay();
                setRefreshingState(false);
                init();
            } else if (data.state === 'error') {
                stopPolling();
                hideRefreshOverlay();
                setRefreshingState(false);
                alert('Refresh failed: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(() => {});
}

function setRefreshingState(active) {
    const btn = document.getElementById('refresh-btn');
    btn.disabled = active;
    btn.classList.toggle('refreshing', active);
    btn.querySelector('.refresh-text').textContent = active ? 'Refreshing...' : 'Refresh';
}

function showRefreshOverlay(title, subtitle) {
    let overlay = document.getElementById('refresh-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'refresh-overlay';
        overlay.className = 'refresh-overlay';
        overlay.innerHTML = '<div class="spinner"></div><div class="refresh-message"><strong></strong><span></span></div>';
        document.body.appendChild(overlay);
    }
    overlay.querySelector('strong').textContent = title;
    overlay.querySelector('span').textContent = subtitle || '';
    overlay.classList.add('active');
}

function hideRefreshOverlay() {
    const overlay = document.getElementById('refresh-overlay');
    if (overlay) overlay.classList.remove('active');
}
