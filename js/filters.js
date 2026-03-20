function applyFilters() {
    const searchText = (document.getElementById('search-box').value || '').toLowerCase();
    const sourceFilter = document.getElementById('filter-source').value;
    const topicFilter = document.getElementById('filter-topic').value;
    const eligFilter = document.getElementById('filter-eligibility').value;
    const priorityOnly = document.getElementById('filter-priority').checked;
    const sortBy = document.getElementById('sort-by').value;

    filteredOpportunities = allOpportunities.filter(opp => {
        // Text search
        if (searchText) {
            const haystack = `${opp.title} ${opp.description} ${opp.agency} ${opp.id}`.toLowerCase();
            if (!haystack.includes(searchText)) return false;
        }
        // Source
        if (sourceFilter && opp.source !== sourceFilter) return false;
        // Topic
        if (topicFilter && !(opp.matched_topics || []).includes(topicFilter)) return false;
        // Eligibility
        if (eligFilter === 'startup' && !opp.startup_eligible) return false;
        if (eligFilter === 'consortium' && !opp.consortium_eligible) return false;
        if (eligFilter === 'both' && !(opp.startup_eligible && opp.consortium_eligible)) return false;
        // Priority
        if (priorityOnly && !opp.high_priority) return false;

        return true;
    });

    // Sort
    filteredOpportunities.sort((a, b) => {
        if (sortBy === 'score') return b.combined_score - a.combined_score;
        if (sortBy === 'deadline') {
            if (!a.deadline) return 1;
            if (!b.deadline) return -1;
            return new Date(a.deadline) - new Date(b.deadline);
        }
        if (sortBy === 'posted') {
            return new Date(b.posted_date || 0) - new Date(a.posted_date || 0);
        }
        return 0;
    });

    renderResults(filteredOpportunities);
    updateResultCount(filteredOpportunities.length);
}
