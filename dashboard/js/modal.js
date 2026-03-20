function showModal(oppId) {
    const opp = allOpportunities.find(o => o.id === oppId);
    if (!opp) return;

    const topicBreakdown = (opp.topic_scores || [])
        .filter(ts => ts.score > 0)
        .sort((a, b) => b.score - a.score)
        .map(ts => `<li><strong>${escapeHtml(ts.topic_name)}</strong>: ${ts.score} pts
                     <span class="keyword-hits">(${(ts.keyword_hits || []).map(escapeHtml).join(', ')})</span></li>`)
        .join('');

    const modal = document.getElementById('detail-modal');
    const deadlineStr = opp.deadline || 'Rolling/TBD';
    const awardStr = opp.award_ceiling
        ? `${opp.currency || 'USD'} ${Number(opp.award_ceiling).toLocaleString()}`
        : 'Not specified';

    const semanticLine = opp.semantic_score != null
        ? `, Semantic: ${opp.semantic_score}`
        : '';

    modal.querySelector('.modal-body').innerHTML = `
        <h2>${escapeHtml(opp.title)}</h2>
        <div class="score-detail">
            <strong>Combined Score: ${opp.combined_score}/100</strong>
            (Keyword: ${opp.keyword_score}${semanticLine})
            ${opp.high_priority ? '<span class="badge badge-priority">HIGH PRIORITY</span>' : ''}
        </div>
        <table class="meta-table">
            <tr><td>Source</td><td>${escapeHtml(opp.source)}</td></tr>
            <tr><td>Agency</td><td>${escapeHtml(opp.agency)}</td></tr>
            <tr><td>Type</td><td>${escapeHtml(opp.activity_type)}</td></tr>
            <tr><td>Posted</td><td>${opp.posted_date || 'N/A'}</td></tr>
            <tr><td>Deadline</td><td>${escapeHtml(deadlineStr)}</td></tr>
            <tr><td>Award</td><td>${escapeHtml(awardStr)}</td></tr>
            <tr><td>Startup Eligible</td><td>${opp.startup_eligible ? '<strong>Yes</strong>' : 'No'}</td></tr>
            <tr><td>Consortium</td><td>${opp.consortium_eligible ? '<strong>Yes</strong>' : 'No'}</td></tr>
        </table>
        ${topicBreakdown ? `<h3>Topic Matches</h3><ul class="topic-list">${topicBreakdown}</ul>` : ''}
        <h3>Description</h3>
        <div class="description">${escapeHtml(opp.description)}</div>
        ${opp.eligibility_text ? `<h3>Eligibility</h3><div class="eligibility">${escapeHtml(opp.eligibility_text)}</div>` : ''}
        <a href="${escapeHtml(opp.url)}" target="_blank" rel="noopener" class="btn-primary">Open Full Announcement</a>
    `;
    modal.classList.add('active');
}

function closeModal() {
    document.getElementById('detail-modal').classList.remove('active');
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
});
