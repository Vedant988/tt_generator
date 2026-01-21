// API Base URL
const API_BASE = '';

// State
let subjectMapping = {};
let selectedSubjects = new Set();

// DOM Elements
const statusIndicator = document.getElementById('statusIndicator');
const statusDot = statusIndicator.querySelector('.status-dot');
const statusText = statusIndicator.querySelector('.status-text');

const branchInput = document.getElementById('branch');
const batchInput = document.getElementById('batch');
const useAICheckbox = document.getElementById('useAI');

const fetchSubjectsBtn = document.getElementById('fetchSubjectsBtn');
const subjectsLoading = document.getElementById('subjectsLoading');
const subjectsContainer = document.getElementById('subjectsContainer');
const subjectsPlaceholder = document.getElementById('subjectsPlaceholder');
const subjectsList = document.getElementById('subjectsList');
const subjectSearch = document.getElementById('subjectSearch');
const selectedCount = document.getElementById('selectedCount');

const generateBtn = document.getElementById('generateBtn');
const resultsSection = document.getElementById('resultsSection');
const timetableContainer = document.getElementById('timetableContainer');
const downloadBtn = document.getElementById('downloadBtn');

// Initialize
async function init() {
    try {
        const response = await fetch(`${API_BASE}/api/status`);
        const data = await response.json();

        if (data.class_file_loaded && data.lab_file_loaded) {
            updateStatus('success', '✓ System Ready');
        } else {
            updateStatus('error', '✗ Data files missing');
        }
    } catch (error) {
        updateStatus('error', '✗ Connection failed');
        console.error('Status check failed:', error);
    }
}

function updateStatus(type, text) {
    statusIndicator.className = `status-indicator ${type}`;
    statusText.textContent = text;
}

// Fetch Subjects
fetchSubjectsBtn.addEventListener('click', async () => {
    try {
        subjectsLoading.style.display = 'block';
        subjectsPlaceholder.style.display = 'none';
        subjectsContainer.style.display = 'none';

        const response = await fetch(`${API_BASE}/api/subjects`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                use_ai: useAICheckbox.checked,
                model_name: 'llama-3.3-70b-versatile'
            })
        });

        if (!response.ok) {
            throw new Error('Failed to fetch subjects');
        }

        const data = await response.json();
        subjectMapping = data.mapping;

        renderSubjects(data.subjects);

        subjectsLoading.style.display = 'none';
        subjectsContainer.style.display = 'block';

    } catch (error) {
        subjectsLoading.style.display = 'none';
        subjectsPlaceholder.style.display = 'block';
        subjectsPlaceholder.textContent = '❌ Failed to load subjects. Please try again.';
        console.error('Fetch subjects failed:', error);
    }
});

function renderSubjects(subjects) {
    subjectsList.innerHTML = '';
    selectedSubjects.clear();

    subjects.forEach(subject => {
        const item = document.createElement('div');
        item.className = 'subject-item';
        item.textContent = subject;
        item.dataset.subject = subject;

        item.addEventListener('click', () => {
            item.classList.toggle('selected');

            if (item.classList.contains('selected')) {
                selectedSubjects.add(subject);
            } else {
                selectedSubjects.delete(subject);
            }

            updateSelectedCount();
        });

        subjectsList.appendChild(item);
    });

    updateSelectedCount();
}

function updateSelectedCount() {
    const count = selectedSubjects.size;
    selectedCount.textContent = `${count} subject${count !== 1 ? 's' : ''} selected`;
    generateBtn.disabled = count === 0;
}

// Search Subjects
subjectSearch.addEventListener('input', (e) => {
    const query = e.target.value.toLowerCase();
    const items = subjectsList.querySelectorAll('.subject-item');

    items.forEach(item => {
        const subject = item.dataset.subject.toLowerCase();
        item.style.display = subject.includes(query) ? 'block' : 'none';
    });
});

// Generate Timetable
generateBtn.addEventListener('click', async () => {
    try {
        generateBtn.disabled = true;
        generateBtn.innerHTML = '<span class="spinner"></span> Generating...';

        const response = await fetch(`${API_BASE}/api/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                selected_subjects: Array.from(selectedSubjects),
                branch: branchInput.value.trim(),
                batch: batchInput.value.trim()
            })
        });

        if (!response.ok) {
            throw new Error('Generation failed');
        }

        const result = await response.json();

        if (result.success) {
            renderTimetable(result.data);
            resultsSection.style.display = 'block';
            resultsSection.scrollIntoView({ behavior: 'smooth' });
        } else {
            alert(result.message || 'No matching classes found');
        }

    } catch (error) {
        alert('Failed to generate timetable. Please try again.');
        console.error('Generation failed:', error);
    } finally {
        generateBtn.disabled = false;
        generateBtn.innerHTML = '<span class="btn-icon">⚡</span> Generate My Timetable';
    }
});

function renderTimetable(data) {
    // Data comes as: { "Monday": { "10:00 - 11:00": "Subject (Room)", ... }, ... }
    // We want: Days as ROWS, Time as COLUMNS (like Streamlit)

    const days = Object.keys(data);
    if (days.length === 0) {
        timetableContainer.innerHTML = '<p class="placeholder">No data to display</p>';
        return;
    }

    // Get all unique time slots across all days
    const timeSlots = new Set();
    days.forEach(day => {
        Object.keys(data[day]).forEach(time => timeSlots.add(time));
    });

    // Sort time slots chronologically
    const sortedTimes = Array.from(timeSlots).sort((a, b) => {
        const parseTime = (t) => {
            try {
                const first = t.split('-')[0].trim();
                const val = parseFloat(first.replace(':', '.'));
                return val;
            } catch { return 99; }
        };
        return parseTime(a) - parseTime(b);
    });

    // Build table with Days as ROWS and Time as COLUMNS
    let html = '<table class="timetable"><thead><tr><th>Day</th>';
    sortedTimes.forEach(time => {
        html += `<th>${time}</th>`;
    });
    html += '</tr></thead><tbody>';

    // Sort days in logical order
    const dayOrder = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
    const sortedDays = days.sort((a, b) => {
        return dayOrder.indexOf(a) - dayOrder.indexOf(b);
    });

    sortedDays.forEach(day => {
        html += `<tr><th>${day}</th>`;
        sortedTimes.forEach(time => {
            const cell = data[day][time] || '';
            html += `<td>${cell}</td>`;
        });
        html += '</tr>';
    });

    html += '</tbody></table>';
    timetableContainer.innerHTML = html;
}

// Download CSV
downloadBtn.addEventListener('click', () => {
    const table = timetableContainer.querySelector('table');
    if (!table) return;

    let csv = '';
    const rows = table.querySelectorAll('tr');

    rows.forEach(row => {
        const cells = row.querySelectorAll('th, td');
        const rowData = Array.from(cells).map(cell => {
            let text = cell.textContent.trim();
            // Escape quotes and wrap in quotes if contains comma
            if (text.includes(',') || text.includes('"')) {
                text = '"' + text.replace(/"/g, '""') + '"';
            }
            return text;
        });
        csv += rowData.join(',') + '\n';
    });

    // Download
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'my_timetable.csv';
    a.click();
    URL.revokeObjectURL(url);
});

// Initialize on load
init();
