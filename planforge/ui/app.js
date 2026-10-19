/**
 * PlanForge Client-Side Application
 * Coordinates UI views, Gantt chart rendering, Function Point estimation,
 * and interoperability workflows.
 */

(function () {
    'use strict';

    // Application state
    let project = null;
    let projectSummary = null;
    let currentView = 'overview';
    let currentZoom = 'day'; // 'day', 'week', 'month'
    let editingTaskId = null;
    let pendingImportFile = null;

    // Default FP Calculator People state
    let fpPeople = [
        {
            name: "Alice (Lead Engineer)",
            hourly_rate: 45.0,
            hours_per_complex_point: 2.5,
            hours_per_simple_point: 1.0,
            tasks: [
                { name: "Core Architecture & Data Schema", type: "complex", points: 12 },
                { name: "Security Audit & JWT Handlers", type: "complex", points: 8 },
                { name: "API Documentation", type: "simple", points: 10 }
            ]
        },
        {
            name: "Bob (Designer & Frontend)",
            hourly_rate: 35.0,
            hours_per_complex_point: 3.0,
            hours_per_simple_point: 1.2,
            tasks: [
                { name: "Responsive Navigation & Shell", type: "complex", points: 10 },
                { name: "Component Styleguide", type: "simple", points: 15 }
            ]
        }
    ];

    // Initialize application
    document.addEventListener('DOMContentLoaded', () => {
        initTheme();
        initNavigation();
        initEventListeners();
        loadProject();
        initShortcuts();
    });

    // --- API & State ---

    async function loadProject() {
        try {
            const resp = await fetch('/api/project');
            const data = await resp.json();
            project = data.project;
            projectSummary = data.summary;
            renderAllViews();
        } catch (err) {
            showToast('Failed to load project: ' + err.message, 'error');
        }
    }

    async function saveProjectState() {
        try {
            const resp = await fetch('/api/project', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(project)
            });
            const data = await resp.json();
            if (data.status === 'ok') {
                showToast('Project saved.', 'success');
                loadProject();
            } else {
                showToast('Save failed: ' + data.error, 'error');
            }
        } catch (err) {
            showToast('Save error: ' + err.message, 'error');
        }
    }

    async function recalculateSchedule() {
        try {
            const resp = await fetch('/api/project/schedule', { method: 'POST' });
            const data = await resp.json();
            if (data.status === 'ok') {
                showToast('Schedule recalculated.', 'success');
                loadProject();
            }
        } catch (err) {
            showToast('Schedule error: ' + err.message, 'error');
        }
    }

    // --- Theme & Settings ---

    async function initTheme() {
        try {
            const resp = await fetch('/api/config');
            const data = await resp.json();
            if (data.theme === 'dark') {
                document.body.classList.remove('theme-light');
                document.body.classList.add('theme-dark');
            } else {
                document.body.classList.remove('theme-dark');
                document.body.classList.add('theme-light');
            }
        } catch (e) {}

        const toggleBtn = document.getElementById('theme-toggle-btn');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', async () => {
                const isDark = document.body.classList.contains('theme-dark');
                const newTheme = isDark ? 'light' : 'dark';
                document.body.classList.toggle('theme-dark', !isDark);
                document.body.classList.toggle('theme-light', isDark);
                try {
                    await fetch('/api/config', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ theme: newTheme })
                    });
                } catch (e) {}
            });
        }
    }

    // --- Navigation ---

    function initNavigation() {
        const navLinks = document.querySelectorAll('.nav-link[data-view]');
        navLinks.forEach(link => {
            link.addEventListener('click', (e) => {
                const view = link.getAttribute('data-view');
                switchView(view);
            });
        });

        // Zoom controls
        const zoomBtns = document.querySelectorAll('.zoom-controls button');
        zoomBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                zoomBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                currentZoom = btn.getAttribute('data-zoom');
                renderTimeline();
            });
        });
    }

    function switchView(viewName) {
        currentView = viewName;
        document.querySelectorAll('.nav-link[data-view]').forEach(link => {
            link.classList.toggle('active', link.getAttribute('data-view') === viewName);
        });
        document.querySelectorAll('.view-panel').forEach(panel => {
            panel.classList.toggle('active', panel.id === `view-${viewName}`);
        });

        if (viewName === 'timeline') {
            renderTimeline();
        } else if (viewName === 'function-points') {
            renderFPCalculator();
        } else if (viewName === 'summary') {
            renderSummaryReport();
        }
    }

    function initShortcuts() {
        window.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key >= '1' && e.key <= '5') {
                e.preventDefault();
                const views = ['tasks', 'timeline', 'people', 'costs', 'function-points'];
                switchView(views[parseInt(e.key, 10) - 1]);
            } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
                e.preventDefault();
                saveProjectToPfp();
            } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'n') {
                e.preventDefault();
                createNewProject();
            } else if (e.key === 'Escape') {
                closeAllModals();
            }
        });
    }

    // --- Renderers ---

    function renderAllViews() {
        if (!project) return;

        // Header Title & Stats
        const titleInput = document.getElementById('project-title-input');
        if (titleInput) titleInput.value = project.name || 'Untitled Project';

        updateStatsPills();
        renderOverview();
        renderTasksTable();
        renderTimeline();
        renderPeopleTable();
        renderCostsView();
        renderSettings();
    }

    function updateStatsPills() {
        const tasks = project.tasks || [];
        const taskCount = tasks.length;
        const completeTasks = tasks.filter(t => (t.percent_complete || 0) >= 100).length;
        const progressPct = taskCount > 0 ? Math.round((completeTasks / taskCount) * 100) : 0;
        const criticalCount = tasks.filter(t => t.custom_fields && t.custom_fields.is_critical).length;

        let totalCost = 0;
        tasks.forEach(t => {
            if (t.estimated_cost) totalCost += t.estimated_cost;
        });

        const currencySymbol = project.currency === 'USD' ? '$' : (project.currency === 'EUR' ? '€' : '£');

        const statTasks = document.getElementById('stat-tasks-count');
        if (statTasks) statTasks.textContent = `${taskCount} tasks`;

        const statProg = document.getElementById('stat-progress-pill');
        if (statProg) statProg.textContent = `${progressPct}% complete`;

        const statCrit = document.getElementById('stat-critical-count');
        if (statCrit) statCrit.textContent = `${criticalCount} critical`;

        const statBudget = document.getElementById('stat-budget-pill');
        if (statBudget) statBudget.textContent = `${currencySymbol}${totalCost.toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    }

    function renderOverview() {
        const tasks = project.tasks || [];
        const resources = project.resources || [];
        const currencySymbol = project.currency === 'USD' ? '$' : (project.currency === 'EUR' ? '€' : '£');

        // Schedule dates
        const starts = tasks.map(t => t.start_date).filter(Boolean);
        const finishes = tasks.map(t => t.finish_date).filter(Boolean);
        const startStr = starts.length ? starts.sort()[0] : '—';
        const finishStr = finishes.length ? finishes.sort().reverse()[0] : '—';

        document.getElementById('card-schedule-dates').textContent = (startStr !== '—' && finishStr !== '—') ? `${startStr} → ${finishStr}` : 'Not scheduled';

        // Working days count
        const totalDur = tasks.filter(t => !t.milestone && t.task_type !== 'summary').reduce((acc, t) => acc + (t.duration || 0), 0);
        document.getElementById('card-schedule-days').textContent = `${totalDur} task work days`;

        // Total tasks
        const leafTasks = tasks.filter(t => t.task_type !== 'summary');
        const milestoneCount = tasks.filter(t => t.milestone || t.task_type === 'milestone').length;
        document.getElementById('card-tasks-total').textContent = tasks.length;
        document.getElementById('card-tasks-breakdown').textContent = `${leafTasks.length} leaf tasks, ${milestoneCount} milestones`;

        // Work Hours
        const totalHours = tasks.reduce((acc, t) => acc + (t.estimated_work || (t.duration || 0) * 8), 0);
        document.getElementById('card-hours-total').textContent = `${totalHours} hrs`;
        document.getElementById('card-people-count').textContent = `${resources.length} team members`;

        // Budget
        let totalCost = 0;
        tasks.forEach(t => { if (t.estimated_cost) totalCost += t.estimated_cost; });
        document.getElementById('card-budget-total').textContent = `${currencySymbol}${totalCost.toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

        // Critical Path
        const criticalTasks = tasks.filter(t => t.custom_fields && t.custom_fields.is_critical);
        document.getElementById('critical-path-badge').textContent = `${criticalTasks.length} tasks on critical path`;
        const critList = document.getElementById('critical-tasks-list');
        critList.innerHTML = '';
        if (criticalTasks.length === 0) {
            critList.innerHTML = '<div class="text-muted" style="font-size:0.85rem;">No critical path bottlenecks found.</div>';
        } else {
            criticalTasks.slice(0, 6).forEach(t => {
                const item = document.createElement('div');
                item.className = 'critical-item';
                item.innerHTML = `<span><strong>${escapeHtml(t.name)}</strong></span><span>${t.start_date || '—'} → ${t.finish_date || '—'}</span>`;
                critList.appendChild(item);
            });
        }

        // Team Workload
        const workloadDiv = document.getElementById('team-workload-overview');
        workloadDiv.innerHTML = '';
        const assigns = project.assignments || [];
        resources.forEach(r => {
            const rAssigns = assigns.filter(a => a.resource_id === r.id);
            const rHours = rAssigns.reduce((acc, a) => acc + (a.work || 0), 0);
            const maxRef = Math.max(80, totalHours || 80);
            const pct = Math.min(100, Math.round((rHours / maxRef) * 100));

            const row = document.createElement('div');
            row.className = 'workload-person-row';
            row.innerHTML = `
                <div class="workload-header">
                    <span>${escapeHtml(r.name)}</span>
                    <span><strong>${rHours} hrs</strong> (${rAssigns.length} tasks)</span>
                </div>
                <div class="workload-track">
                    <div class="workload-fill" style="width: ${pct}%;"></div>
                </div>
            `;
            workloadDiv.appendChild(row);
        });
    }

    // --- Tasks Table Rendering ---

    function renderTasksTable() {
        const tbody = document.getElementById('tasks-table-body');
        if (!tbody) return;
        tbody.innerHTML = '';

        const tasks = project.tasks || [];
        const dependencies = project.dependencies || [];
        const resources = project.resources || [];
        const assigns = project.assignments || [];

        const resMap = {};
        resources.forEach(r => { resMap[r.id] = r; });

        const taskMap = {};
        tasks.forEach(t => { taskMap[t.id] = t; });

        const filterQuery = (document.getElementById('task-search-input')?.value || '').trim().toLowerCase();

        tasks.forEach((task, idx) => {
            if (filterQuery && !task.name.toLowerCase().includes(filterQuery)) {
                return;
            }

            const tr = document.createElement('tr');
            const level = task.outline_level || (task.parent_id ? 2 : 1);
            const indentClass = level > 1 ? `task-indent-${Math.min(3, level - 1)}` : '';

            // Type icon
            let typeIcon = '';
            if (task.milestone || task.task_type === 'milestone') {
                typeIcon = '<span class="task-icon-milestone">◆</span>';
            } else if (task.task_type === 'summary') {
                typeIcon = '<span class="task-icon-summary">▾</span>';
            } else {
                typeIcon = '<span class="text-muted">▪</span>';
            }

            // Predecessors
            const preds = dependencies.filter(d => d.successor_id === task.id).map(d => {
                const pt = taskMap[d.predecessor_id];
                return pt ? escapeHtml(pt.name) : 'Task';
            });
            const predsText = preds.length ? preds.join(', ') : '—';

            // Assigned people
            const taskAssigns = assigns.filter(a => a.task_id === task.id);
            const peopleNames = taskAssigns.map(a => {
                const r = resMap[a.resource_id];
                return r ? escapeHtml(r.name) : 'Unassigned';
            });
            const peopleText = peopleNames.length ? peopleNames.join(', ') : '—';

            const pct = task.percent_complete || 0;
            const currencySymbol = project.currency === 'USD' ? '$' : (project.currency === 'EUR' ? '€' : '£');

            tr.innerHTML = `
                <td>${idx + 1}</td>
                <td class="${indentClass}">
                    <div class="task-name-cell">
                        ${typeIcon}
                        <span style="font-weight: ${task.task_type === 'summary' ? '600' : 'normal'}">${escapeHtml(task.name)}</span>
                    </div>
                </td>
                <td><span class="badge ${task.milestone ? 'badge-warning' : (task.task_type === 'summary' ? 'badge-info' : 'badge-secondary')}">${task.milestone ? 'Milestone' : (task.task_type === 'summary' ? 'Summary' : 'Task')}</span></td>
                <td>${task.milestone ? '0d' : `${task.duration || 1}d`}</td>
                <td>${task.start_date || '—'}</td>
                <td>${task.finish_date || '—'}</td>
                <td>
                    <div class="progress-cell">
                        <div class="progress-bar-mini">
                            <div class="progress-fill-mini" style="width: ${pct}%;"></div>
                        </div>
                        <span>${pct}%</span>
                    </div>
                </td>
                <td>${task.estimated_work != null ? `${task.estimated_work}h` : '—'}</td>
                <td>${task.estimated_cost != null ? `${currencySymbol}${task.estimated_cost.toFixed(2)}` : '—'}</td>
                <td title="${predsText}">${truncate(predsText, 18)}</td>
                <td title="${peopleText}">${truncate(peopleText, 18)}</td>
                <td>
                    <button class="btn btn-secondary btn-sm" onclick="window.planforgeEditTask('${task.id}')">Edit</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    }

    // --- Timeline / Interactive Gantt Chart ---

    function renderTimeline() {
        const labelsCol = document.getElementById('gantt-labels');
        const headerRow = document.getElementById('gantt-header');
        const rowsContainer = document.getElementById('gantt-rows');
        const svgLinks = document.getElementById('gantt-svg-links');
        if (!labelsCol || !headerRow || !rowsContainer || !svgLinks) return;

        labelsCol.innerHTML = '';
        headerRow.innerHTML = '';
        rowsContainer.innerHTML = '';
        svgLinks.innerHTML = '';

        const tasks = project.tasks || [];
        if (!tasks.length) {
            headerRow.innerHTML = '<div style="padding:1rem;">No tasks to display.</div>';
            return;
        }

        // Determine date span
        const allStarts = tasks.map(t => t.start_date).filter(Boolean);
        const allFinishes = tasks.map(t => t.finish_date).filter(Boolean);

        let minDate = allStarts.length ? new Date(allStarts.sort()[0]) : new Date();
        let maxDate = allFinishes.length ? new Date(allFinishes.sort().reverse()[0]) : new Date();

        // Add padding days
        minDate.setDate(minDate.getDate() - 2);
        maxDate.setDate(maxDate.getDate() + 7);

        const dayWidth = currentZoom === 'day' ? 36 : (currentZoom === 'week' ? 20 : 12);
        const totalDays = Math.max(14, Math.round((maxDate - minDate) / (1000 * 60 * 60 * 24)));
        const totalWidth = totalDays * dayWidth;

        rowsContainer.style.width = `${totalWidth}px`;
        headerRow.style.width = `${totalWidth}px`;
        svgLinks.style.width = `${totalWidth}px`;
        svgLinks.style.height = `${tasks.length * 38}px`;

        // Render header days
        const daysArray = [];
        for (let i = 0; i < totalDays; i++) {
            const d = new Date(minDate);
            d.setDate(minDate.getDate() + i);
            daysArray.push(d);

            const isWeekend = d.getDay() === 0 || d.getDay() === 6;
            const dayEl = document.createElement('div');
            dayEl.className = `gantt-day-header ${isWeekend ? 'weekend' : ''}`;
            dayEl.style.width = `${dayWidth}px`;
            const dayNames = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];
            dayEl.innerHTML = `<span>${d.getDate()}</span><span style="font-size:0.6rem;">${dayNames[d.getDay()]}</span>`;
            headerRow.appendChild(dayEl);
        }

        const taskCoords = {}; // task_id -> { startX, endX, midY }

        // Render rows
        tasks.forEach((task, idx) => {
            const rowY = idx * 38;

            // Left label
            const labelRow = document.createElement('div');
            labelRow.className = 'gantt-label-row';
            const indent = (task.outline_level || (task.parent_id ? 2 : 1)) > 1 ? '— ' : '';
            labelRow.textContent = `${indent}${task.name}`;
            labelRow.onclick = () => window.planforgeEditTask(task.id);
            labelsCol.appendChild(labelRow);

            // Right canvas row
            const row = document.createElement('div');
            row.className = 'gantt-row';
            row.style.width = `${totalWidth}px`;

            if (task.start_date) {
                const tStart = new Date(task.start_date);
                const tFinish = task.finish_date ? new Date(task.finish_date) : tStart;

                const dayOffsetStart = (tStart - minDate) / (1000 * 60 * 60 * 24);
                const dayOffsetFinish = ((tFinish - minDate) / (1000 * 60 * 60 * 24)) + 1;

                const leftPx = Math.max(0, dayOffsetStart * dayWidth);
                const widthPx = Math.max(dayWidth, (dayOffsetFinish - dayOffsetStart) * dayWidth);

                taskCoords[task.id] = {
                    startX: leftPx,
                    endX: leftPx + widthPx,
                    midY: rowY + 19
                };

                const isCrit = task.custom_fields && task.custom_fields.is_critical;
                const isMilestone = task.milestone || task.task_type === 'milestone';
                const isSummary = task.task_type === 'summary';

                if (isMilestone) {
                    const mEl = document.createElement('div');
                    mEl.className = 'gantt-milestone';
                    mEl.style.left = `${leftPx + (dayWidth / 2) - 8}px`;
                    mEl.style.top = '11px';
                    mEl.title = `${task.name} (${task.start_date})`;
                    mEl.onclick = () => window.planforgeEditTask(task.id);
                    row.appendChild(mEl);
                } else if (isSummary) {
                    const sEl = document.createElement('div');
                    sEl.className = 'gantt-summary-bracket';
                    sEl.style.left = `${leftPx}px`;
                    sEl.style.width = `${widthPx}px`;
                    sEl.style.top = '15px';
                    sEl.title = `${task.name} (Summary)`;
                    row.appendChild(sEl);
                } else {
                    const bar = document.createElement('div');
                    bar.className = `gantt-bar ${isCrit ? 'critical' : ''}`;
                    bar.style.left = `${leftPx}px`;
                    bar.style.width = `${widthPx}px`;
                    bar.style.top = '9px';

                    const pct = task.percent_complete || 0;
                    bar.innerHTML = `
                        <div class="gantt-bar-progress" style="width: ${pct}%;"></div>
                        <span class="gantt-bar-text">${escapeHtml(task.name)}</span>
                    `;
                    bar.title = `${task.name} (${task.duration || 1}d, ${pct}% complete)`;
                    bar.onclick = () => window.planforgeEditTask(task.id);
                    row.appendChild(bar);
                }
            }

            rowsContainer.appendChild(row);
        });

        // Draw dependency SVG arrows
        const dependencies = project.dependencies || [];
        let svgHtml = '';
        dependencies.forEach(dep => {
            const pred = taskCoords[dep.predecessor_id];
            const succ = taskCoords[dep.successor_id];
            if (pred && succ) {
                const x1 = pred.endX;
                const y1 = pred.midY;
                const x2 = succ.startX;
                const y2 = succ.midY;

                // Bezier / step path
                const midX = x1 + Math.max(10, (x2 - x1) / 2);
                const pathD = `M ${x1} ${y1} L ${midX} ${y1} L ${midX} ${y2} L ${x2} ${y2}`;
                svgHtml += `
                    <path d="${pathD}" fill="none" stroke="var(--color-primary)" stroke-width="1.8" stroke-dasharray="${dep.relationship_type !== 'finish_to_start' ? '3,3' : 'none'}"></path>
                    <polygon points="${x2},${y2} ${x2 - 5},${y2 - 3.5} ${x2 - 5},${y2 + 3.5}" fill="var(--color-primary)"></polygon>
                `;
            }
        });
        svgLinks.innerHTML = svgHtml;

        // Draw Today marker line
        const today = new Date();
        const todayOffset = (today - minDate) / (1000 * 60 * 60 * 24);
        if (todayOffset >= 0 && todayOffset <= totalDays) {
            const todayX = todayOffset * dayWidth;
            const todayLine = document.createElement('div');
            todayLine.style.position = 'absolute';
            todayLine.style.left = `${todayX}px`;
            todayLine.style.top = '0';
            todayLine.style.bottom = '0';
            todayLine.style.width = '2px';
            todayLine.style.backgroundColor = 'var(--color-danger)';
            todayLine.style.zIndex = '4';
            todayLine.style.pointerEvents = 'none';
            todayLine.title = 'Today';
            rowsContainer.appendChild(todayLine);
        }
    }

    // --- People & Resources ---

    function renderPeopleTable() {
        const tbody = document.getElementById('people-table-body');
        if (!tbody) return;
        tbody.innerHTML = '';

        const resources = project.resources || [];
        const assigns = project.assignments || [];
        const currencySymbol = project.currency === 'USD' ? '$' : (project.currency === 'EUR' ? '€' : '£');

        resources.forEach(r => {
            const tr = document.createElement('tr');
            const rAssigns = assigns.filter(a => a.resource_id === r.id);
            const totalHours = rAssigns.reduce((acc, a) => acc + (a.work || 0), 0);
            const rate = r.standard_rate != null ? r.standard_rate : 30.0;
            const totalCost = totalHours * rate;
            const hoursPerDay = r.custom_fields && r.custom_fields.hours_per_day ? r.custom_fields.hours_per_day : 8.0;

            tr.innerHTML = `
                <td><strong>${escapeHtml(r.name)}</strong></td>
                <td>${currencySymbol}${rate.toFixed(2)} / hr</td>
                <td>${hoursPerDay} hrs</td>
                <td><span class="badge badge-info">${rAssigns.length} tasks</span></td>
                <td>${totalHours} hrs</td>
                <td><strong>${currencySymbol}${totalCost.toFixed(2)}</strong></td>
                <td>
                    <button class="btn btn-secondary btn-sm" onclick="window.planforgeDeletePerson('${r.id}')">Delete</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    }

    // --- Costs & Workload ---

    function renderCostsView() {
        const tasks = project.tasks || [];
        const resources = project.resources || [];
        const assigns = project.assignments || [];
        const currencySymbol = project.currency === 'USD' ? '$' : (project.currency === 'EUR' ? '€' : '£');

        let totalCost = 0;
        let totalHours = 0;
        tasks.forEach(t => {
            if (t.estimated_cost) totalCost += t.estimated_cost;
            if (t.estimated_work) totalHours += t.estimated_work;
        });

        const avgRate = totalHours > 0 ? (totalCost / totalHours) : 0;

        document.getElementById('costs-total-cost').textContent = `${currencySymbol}${totalCost.toFixed(2)}`;
        document.getElementById('costs-total-hours').textContent = `${totalHours} hrs`;
        document.getElementById('costs-avg-rate').textContent = `${currencySymbol}${avgRate.toFixed(2)}/hr`;

        const tbody = document.getElementById('costs-breakdown-body');
        if (!tbody) return;
        tbody.innerHTML = '';

        resources.forEach(r => {
            const tr = document.createElement('tr');
            const rAssigns = assigns.filter(a => a.resource_id === r.id);
            const rHours = rAssigns.reduce((acc, a) => acc + (a.work || 0), 0);
            const rate = r.standard_rate != null ? r.standard_rate : 30.0;
            const rCost = rHours * rate;
            const sharePct = totalHours > 0 ? Math.round((rHours / totalHours) * 100) : 0;

            tr.innerHTML = `
                <td><strong>${escapeHtml(r.name)}</strong></td>
                <td>${currencySymbol}${rate.toFixed(2)}/hr</td>
                <td>${rAssigns.length}</td>
                <td>${rHours} hrs</td>
                <td><strong>${currencySymbol}${rCost.toFixed(2)}</strong></td>
                <td>
                    <div class="progress-cell">
                        <div class="progress-bar-mini" style="width: 80px;">
                            <div class="progress-fill-mini" style="width: ${sharePct}%;"></div>
                        </div>
                        <span>${sharePct}%</span>
                    </div>
                </td>
            `;
            tbody.appendChild(tr);
        });
    }

    // --- Function Point Calculator Integration ---

    function renderFPCalculator() {
        const container = document.getElementById('fp-people-container');
        if (!container) return;
        container.innerHTML = '';

        fpPeople.forEach((person, pIdx) => {
            const card = document.createElement('div');
            card.className = 'fp-person-card';

            let tasksRows = '';
            let pTotalHours = 0;
            let pTotalCost = 0;

            person.tasks.forEach((t, tIdx) => {
                const perPt = t.type === 'complex' ? person.hours_per_complex_point : person.hours_per_simple_point;
                const hrs = t.points * perPt;
                const cost = hrs * person.hourly_rate;
                pTotalHours += hrs;
                pTotalCost += cost;

                tasksRows += `
                    <tr>
                        <td><input type="text" class="form-control form-control-sm" value="${escapeHtml(t.name)}" onchange="window.planforgeUpdateFPTask(${pIdx}, ${tIdx}, 'name', this.value)"></td>
                        <td width="130">
                            <select class="form-control form-control-sm" onchange="window.planforgeUpdateFPTask(${pIdx}, ${tIdx}, 'type', this.value)">
                                <option value="complex" ${t.type === 'complex' ? 'selected' : ''}>Complex</option>
                                <option value="simple" ${t.type === 'simple' ? 'selected' : ''}>Simple</option>
                            </select>
                        </td>
                        <td width="100"><input type="number" class="form-control form-control-sm" value="${t.points}" min="0" onchange="window.planforgeUpdateFPTask(${pIdx}, ${tIdx}, 'points', parseInt(this.value, 10))"></td>
                        <td width="110"><strong>${hrs.toFixed(1)} hrs</strong></td>
                        <td width="120"><strong>£${cost.toFixed(2)}</strong></td>
                        <td width="70"><button class="btn btn-secondary btn-sm" onclick="window.planforgeDeleteFPTask(${pIdx}, ${tIdx})">&times;</button></td>
                    </tr>
                `;
            });

            card.innerHTML = `
                <div class="fp-person-header">
                    <div>
                        <strong style="font-size: 1.05rem;">${escapeHtml(person.name)}</strong>
                    </div>
                    <div class="fp-person-params">
                        <span>Rate: <strong>£${person.hourly_rate.toFixed(2)}/hr</strong></span>
                        <span>Complex FP: <strong>${person.hours_per_complex_point}h/pt</strong></span>
                        <span>Simple FP: <strong>${person.hours_per_simple_point}h/pt</strong></span>
                        <span>Total: <strong style="color:var(--color-primary)">${pTotalHours.toFixed(1)}h (£${pTotalCost.toFixed(2)})</strong></span>
                    </div>
                    <div>
                        <button class="btn btn-secondary btn-sm" onclick="window.planforgeAddFPTask(${pIdx})">+ Add Estimate</button>
                    </div>
                </div>
                <table class="fp-tasks-table">
                    <thead>
                        <tr>
                            <th>Estimated Task</th>
                            <th>Complexity</th>
                            <th>Points</th>
                            <th>Hours</th>
                            <th>Cost</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>${tasksRows}</tbody>
                </table>
            `;
            container.appendChild(card);
        });
    }

    window.planforgeUpdateFPTask = function (pIdx, tIdx, field, val) {
        fpPeople[pIdx].tasks[tIdx][field] = val;
        renderFPCalculator();
    };

    window.planforgeAddFPTask = function (pIdx) {
        fpPeople[pIdx].tasks.push({ name: "New Function Point Task", type: "complex", points: 8 });
        renderFPCalculator();
    };

    window.planforgeDeleteFPTask = function (pIdx, tIdx) {
        fpPeople[pIdx].tasks.splice(tIdx, 1);
        renderFPCalculator();
    };

    async function transferFPToProject() {
        try {
            const resp = await fetch('/api/fp/transfer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ people: fpPeople })
            });
            const data = await resp.json();
            if (data.status === 'ok') {
                showToast(data.message, 'success');
                loadProject();
                switchView('tasks');
            } else {
                showToast('Transfer failed: ' + data.error, 'error');
            }
        } catch (e) {
            showToast('Transfer error: ' + e.message, 'error');
        }
    }

    // --- Summary Report ---

    function renderSummaryReport() {
        const box = document.getElementById('report-text-container');
        if (!box || !project) return;

        const tasks = project.tasks || [];
        const resources = project.resources || [];
        const deps = project.dependencies || [];
        const assigns = project.assignments || [];

        const currencySymbol = project.currency === 'USD' ? '$' : (project.currency === 'EUR' ? '€' : '£');
        let totalCost = 0;
        let totalHours = 0;
        tasks.forEach(t => {
            if (t.estimated_cost) totalCost += t.estimated_cost;
            if (t.estimated_work) totalHours += t.estimated_work;
        });

        const lines = [
            `PLANFORGE PROJECT SUMMARY REPORT`,
            `=================================`,
            `Project Name: ${project.name}`,
            `Description:  ${project.description || 'None'}`,
            `Author:       ${project.author || 'PlanForge'}`,
            `Currency:     ${project.currency} (${currencySymbol})`,
            `Start Date:   ${project.start_date || 'Not set'}`,
            `Finish Date:  ${project.finish_date || 'Not set'}`,
            ``,
            `KEY METRICS`,
            `-----------`,
            `Total Tasks:        ${tasks.length}`,
            `Milestones:         ${tasks.filter(t => t.milestone).length}`,
            `Dependencies:       ${deps.length}`,
            `Team Members:       ${resources.length}`,
            `Estimated Hours:    ${totalHours} hours`,
            `Total Labour Cost:  ${currencySymbol}${totalCost.toFixed(2)}`,
            ``,
            `CRITICAL PATH`,
            `-------------`,
        ];

        const crit = tasks.filter(t => t.custom_fields && t.custom_fields.is_critical);
        if (crit.length) {
            crit.forEach(t => {
                lines.push(` * [${t.start_date} -> ${t.finish_date}] ${t.name} (${t.duration || 1}d)`);
            });
        } else {
            lines.push(` None detected or project not scheduled.`);
        }

        lines.push(``);
        lines.push(`TEAM ALLOCATION & COSTS`);
        lines.push(`-----------------------`);
        resources.forEach(r => {
            const rAssigns = assigns.filter(a => a.resource_id === r.id);
            const rHours = rAssigns.reduce((acc, a) => acc + (a.work || 0), 0);
            const rCost = rHours * (r.standard_rate || 30);
            lines.push(` * ${r.name.padEnd(28)}: ${String(rHours).padStart(5)} hrs | ${currencySymbol}${rCost.toFixed(2)}`);
        });

        lines.push(``);
        lines.push(`Report generated on ${new Date().toISOString()}`);

        box.textContent = lines.join('\n');
    }

    // --- Settings View ---

    function renderSettings() {
        if (!project) return;
        document.getElementById('setting-proj-name').value = project.name || '';
        document.getElementById('setting-proj-desc').value = project.description || '';
        document.getElementById('setting-proj-start').value = project.start_date || '';
        document.getElementById('setting-proj-currency').value = project.currency || 'GBP';
    }

    function saveSettings() {
        if (!project) return;
        project.name = document.getElementById('setting-proj-name').value;
        project.description = document.getElementById('setting-proj-desc').value;
        project.start_date = document.getElementById('setting-proj-start').value || null;
        project.currency = document.getElementById('setting-proj-currency').value;
        saveProjectState();
    }

    // --- Modals & Task Editing ---

    window.planforgeEditTask = function (taskId) {
        editingTaskId = taskId;
        const task = (project.tasks || []).find(t => t.id === taskId);
        if (!task) return;

        document.getElementById('task-modal-title').textContent = 'Edit Task';
        document.getElementById('task-edit-name').value = task.name || '';
        document.getElementById('task-edit-notes').value = task.description || '';
        document.getElementById('task-edit-duration').value = task.duration != null ? task.duration : 1;
        document.getElementById('task-edit-progress').value = task.percent_complete || 0;
        document.getElementById('task-edit-priority').value = task.priority || 500;
        document.getElementById('task-edit-milestone').checked = Boolean(task.milestone);

        // Predecessor dropdown
        const predSelect = document.getElementById('task-edit-predecessor');
        predSelect.innerHTML = '<option value="">None (No predecessor)</option>';
        (project.tasks || []).forEach(t => {
            if (t.id !== taskId) {
                const opt = document.createElement('option');
                opt.value = t.id;
                opt.textContent = t.name;
                predSelect.appendChild(opt);
            }
        });

        const existingDep = (project.dependencies || []).find(d => d.successor_id === taskId);
        if (existingDep) {
            predSelect.value = existingDep.predecessor_id;
            document.getElementById('task-edit-deptype').value = existingDep.relationship_type || 'finish_to_start';
            document.getElementById('task-edit-lag').value = existingDep.lag || 0;
        } else {
            predSelect.value = '';
            document.getElementById('task-edit-lag').value = 0;
        }

        // Assignee dropdown
        const assignSelect = document.getElementById('task-edit-assignee');
        assignSelect.innerHTML = '<option value="">Unassigned</option>';
        (project.resources || []).forEach(r => {
            const opt = document.createElement('option');
            opt.value = r.id;
            opt.textContent = r.name;
            assignSelect.appendChild(opt);
        });

        const existingAssign = (project.assignments || []).find(a => a.task_id === taskId);
        if (existingAssign) {
            assignSelect.value = existingAssign.resource_id;
        } else {
            assignSelect.value = '';
        }

        // Function Point setup
        const hasFP = task.function_points && (task.function_points.function_points || (task.function_points.counts && task.function_points.counts.function_points));
        const estMethodManual = document.getElementById('est-method-manual');
        const estMethodFP = document.getElementById('est-method-fp');
        const fpSection = document.getElementById('task-fp-section');
        const fpComplexity = document.getElementById('task-fp-complexity');
        const fpPoints = document.getElementById('task-fp-points');

        if (hasFP) {
            if (estMethodFP) estMethodFP.checked = true;
            if (fpSection) fpSection.style.display = 'block';
            if (fpComplexity) fpComplexity.value = task.function_points.complexities?.type || 'complex';
            if (fpPoints) fpPoints.value = task.function_points.function_points || task.function_points.counts?.function_points || 8;
        } else {
            if (estMethodManual) estMethodManual.checked = true;
            if (fpSection) fpSection.style.display = 'none';
        }

        function updateFPCalc() {
            if (!fpComplexity || !fpPoints) return;
            const resId = document.getElementById('task-edit-assignee').value;
            const res = (project.resources || []).find(r => r.id === resId);
            const rate = res && res.standard_rate != null ? res.standard_rate : 30.0;
            const cRate = res && res.custom_fields && res.custom_fields.hours_per_complex_point ? res.custom_fields.hours_per_complex_point : 2.5;
            const sRate = res && res.custom_fields && res.custom_fields.hours_per_simple_point ? res.custom_fields.hours_per_simple_point : 1.0;

            const cType = fpComplexity.value;
            const pts = parseFloat(fpPoints.value) || 0;
            const perPt = cType === 'complex' ? cRate : sRate;
            const hrs = pts * perPt;
            const cost = hrs * rate;

            const currencySymbol = project.currency === 'USD' ? '$' : (project.currency === 'EUR' ? '€' : '£');
            const previewEl = document.getElementById('task-fp-calc-preview');
            if (previewEl) {
                previewEl.textContent = `${hrs.toFixed(1)} hrs (${currencySymbol}${cost.toFixed(2)})`;
            }
        }

        if (estMethodManual) estMethodManual.onchange = () => { if (fpSection) fpSection.style.display = 'none'; };
        if (estMethodFP) estMethodFP.onchange = () => { if (fpSection) fpSection.style.display = 'block'; updateFPCalc(); };
        if (fpComplexity) fpComplexity.onchange = updateFPCalc;
        if (fpPoints) fpPoints.oninput = updateFPCalc;
        assignSelect.onchange = updateFPCalc;
        updateFPCalc();

        openModal('modal-task-detail');
    };

    function saveTaskModal() {
        if (!editingTaskId || !project) return;
        const task = (project.tasks || []).find(t => t.id === editingTaskId);
        if (!task) return;

        task.name = document.getElementById('task-edit-name').value;
        task.description = document.getElementById('task-edit-notes').value;
        task.milestone = document.getElementById('task-edit-milestone').checked;
        task.duration = task.milestone ? 0 : parseFloat(document.getElementById('task-edit-duration').value || 1);
        task.percent_complete = parseFloat(document.getElementById('task-edit-progress').value || 0);
        task.priority = parseInt(document.getElementById('task-edit-priority').value || 500, 10);
        task.task_type = task.milestone ? 'milestone' : (task.task_type === 'summary' ? 'summary' : 'task');

        // Check if Function Points method is chosen
        const isFpMethod = document.getElementById('est-method-fp')?.checked;
        if (isFpMethod) {
            const resId = document.getElementById('task-edit-assignee').value;
            const res = (project.resources || []).find(r => r.id === resId);
            const rate = res && res.standard_rate != null ? res.standard_rate : 30.0;
            const cRate = res && res.custom_fields && res.custom_fields.hours_per_complex_point ? res.custom_fields.hours_per_complex_point : 2.5;
            const sRate = res && res.custom_fields && res.custom_fields.hours_per_simple_point ? res.custom_fields.hours_per_simple_point : 1.0;
            const cType = document.getElementById('task-fp-complexity').value;
            const pts = parseFloat(document.getElementById('task-fp-points').value) || 0;
            const perPt = cType === 'complex' ? cRate : sRate;
            const hrs = pts * perPt;
            const cost = hrs * rate;

            task.function_points = {
                counts: { function_points: pts },
                complexities: { type: cType },
                function_points: pts,
                estimated_hours: hrs,
                hourly_rate: rate,
                estimated_cost: cost,
                currency: project.currency || 'GBP'
            };
            task.estimated_work = hrs;
            task.estimated_cost = cost;
            if (!task.milestone) {
                task.duration = Math.max(1, Math.ceil(hrs / 8.0));
            }
        } else {
            task.function_points = null;
        }

        // Update dependency
        const predId = document.getElementById('task-edit-predecessor').value;
        const depType = document.getElementById('task-edit-deptype').value;
        const lag = parseFloat(document.getElementById('task-edit-lag').value || 0);

        project.dependencies = (project.dependencies || []).filter(d => d.successor_id !== editingTaskId);
        if (predId) {
            project.dependencies.push({
                id: 'dep-' + Math.random().toString(36).substring(2, 9),
                predecessor_id: predId,
                successor_id: editingTaskId,
                relationship_type: depType,
                lag: lag,
                lag_unit: 'day'
            });
        }

        // Update assignment
        const resId = document.getElementById('task-edit-assignee').value;
        project.assignments = (project.assignments || []).filter(a => a.task_id !== editingTaskId);
        if (resId) {
            const res = (project.resources || []).find(r => r.id === resId);
            const workHrs = task.estimated_work || (task.duration || 1) * 8;
            const cost = task.estimated_cost || (workHrs * (res && res.standard_rate != null ? res.standard_rate : 30));

            project.assignments.push({
                id: 'asg-' + Math.random().toString(36).substring(2, 9),
                task_id: editingTaskId,
                resource_id: resId,
                units: 1.0,
                work: workHrs,
                cost: cost
            });
        }

        closeModal('modal-task-detail');
        recalculateSchedule();
    }

    function deleteTask(taskId) {
        if (!confirm('Are you sure you want to delete this task?')) return;
        project.tasks = (project.tasks || []).filter(t => t.id !== taskId);
        project.dependencies = (project.dependencies || []).filter(d => d.predecessor_id !== taskId && d.successor_id !== taskId);
        project.assignments = (project.assignments || []).filter(a => a.task_id !== taskId);
        closeModal('modal-task-detail');
        recalculateSchedule();
    }

    window.planforgeDeletePerson = function (personId) {
        if (!confirm('Delete this team member and unassign their tasks?')) return;
        project.resources = (project.resources || []).filter(r => r.id !== personId);
        project.assignments = (project.assignments || []).filter(a => a.resource_id !== personId);
        saveProjectState();
    };

    function addNewTask(isMilestone = false) {
        const newId = 'task-' + Math.random().toString(36).substring(2, 9);
        const order = (project.tasks || []).length;
        const task = {
            id: newId,
            name: isMilestone ? 'New Milestone' : 'New Task',
            order: order,
            duration: isMilestone ? 0 : 3,
            duration_unit: 'day',
            percent_complete: 0,
            priority: 500,
            milestone: isMilestone,
            task_type: isMilestone ? 'milestone' : 'task',
            start_date: project.start_date || new Date().toISOString().split('T')[0]
        };
        project.tasks.push(task);
        recalculateSchedule();
    }

    function indentTask() {
        const tasks = project.tasks || [];
        if (tasks.length < 2) return;
        // Indent last task under previous task
        const last = tasks[tasks.length - 1];
        const prev = tasks[tasks.length - 2];
        last.parent_id = prev.id;
        last.outline_level = (prev.outline_level || 1) + 1;
        prev.task_type = 'summary';
        showToast(`Indented '${last.name}' under '${prev.name}'`, 'info');
        recalculateSchedule();
    }

    function outdentTask() {
        const tasks = project.tasks || [];
        if (tasks.length === 0) return;
        const last = tasks[tasks.length - 1];
        last.parent_id = null;
        last.outline_level = 1;
        showToast(`Promoted '${last.name}' to top level`, 'info');
        recalculateSchedule();
    }

    function addNewPerson() {
        const name = document.getElementById('person-edit-name').value.trim();
        if (!name) {
            showToast('Please enter a person name.', 'warning');
            return;
        }
        const rate = parseFloat(document.getElementById('person-edit-rate').value || 30);
        const hours = parseFloat(document.getElementById('person-edit-hours').value || 8);

        const newP = {
            id: 'res-' + Math.random().toString(36).substring(2, 9),
            name: name,
            standard_rate: rate,
            custom_fields: { hours_per_day: hours }
        };
        project.resources.push(newP);
        closeModal('modal-person');
        saveProjectState();
    }

    // --- Import & Export Workflows ---

    function handleFileSelected(file) {
        pendingImportFile = file;
        const reader = new FileReader();
        reader.onload = async (e) => {
            const content = e.target.result;
            try {
                const resp = await fetch('/api/import/preview', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ filename: file.name, content: content })
                });
                const data = await resp.json();
                renderImportPreview(data, file.name);
            } catch (err) {
                showToast('Preview error: ' + err.message, 'error');
            }
        };
        reader.readAsText(file);
    }

    function renderImportPreview(data, filename) {
        const box = document.getElementById('import-preview-box');
        const confirmBtn = document.getElementById('btn-confirm-import');
        box.style.display = 'block';

        if (!data.success) {
            confirmBtn.disabled = true;
            document.getElementById('import-format-badge').className = 'badge badge-danger';
            document.getElementById('import-format-badge').textContent = 'Unsupported Format';
            document.getElementById('import-preview-name').textContent = filename;

            const warningsBox = document.getElementById('import-warnings-box');
            warningsBox.style.display = 'block';
            warningsBox.innerHTML = (data.issues || []).map(i => `<div>• ${escapeHtml(i.message)}</div>`).join('');
            return;
        }

        confirmBtn.disabled = false;
        document.getElementById('import-format-badge').className = 'badge badge-success';
        document.getElementById('import-format-badge').textContent = data.format_name || data.format_id;
        document.getElementById('import-preview-name').textContent = data.summary.name || filename;

        document.getElementById('prev-tasks').textContent = data.summary.task_count;
        document.getElementById('prev-subtasks').textContent = data.summary.subtask_count;
        document.getElementById('prev-deps').textContent = data.summary.dependency_count;
        document.getElementById('prev-res').textContent = data.summary.resource_count;
        document.getElementById('prev-span').textContent = (data.summary.start_date && data.summary.finish_date) ? `${data.summary.start_date} → ${data.summary.finish_date}` : '—';

        const warningsBox = document.getElementById('import-warnings-box');
        const warnings = (data.issues || []).filter(i => i.severity === 'warning');
        if (warnings.length) {
            warningsBox.style.display = 'block';
            warningsBox.innerHTML = `<strong>Import Compatibility Notes:</strong><br>` + warnings.map(w => `• ${escapeHtml(w.message)}`).join('<br>');
        } else {
            warningsBox.style.display = 'none';
        }
    }

    async function confirmImport() {
        if (!pendingImportFile) return;
        const reader = new FileReader();
        reader.onload = async (e) => {
            const content = e.target.result;
            try {
                const resp = await fetch('/api/import/confirm', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ filename: pendingImportFile.name, content: content })
                });
                const data = await resp.json();
                if (data.status === 'ok') {
                    showToast(data.message, 'success');
                    closeModal('modal-import');
                    loadProject();
                } else {
                    showToast('Import failed: ' + data.error, 'error');
                }
            } catch (err) {
                showToast('Import error: ' + err.message, 'error');
            }
        };
        reader.readAsText(pendingImportFile);
    }

    async function executeExport() {
        const selectedRadio = document.querySelector('input[name="export-format"]:checked');
        const formatId = selectedRadio ? selectedRadio.value : 'microsoft-project-xml';

        try {
            const resp = await fetch('/api/export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ format_id: formatId })
            });

            if (!resp.ok) {
                const errData = await resp.json();
                showToast('Export failed: ' + errData.error, 'error');
                return;
            }

            const blob = await resp.blob();
            const disposition = resp.headers.get('Content-Disposition');
            let filename = 'project_export';
            if (disposition && disposition.indexOf('filename=') !== -1) {
                filename = disposition.split('filename=')[1].replace(/"/g, '').trim();
            }

            const downloadUrl = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = downloadUrl;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(downloadUrl);

            closeModal('modal-export');
            showToast(`Exported ${filename} successfully.`, 'success');
        } catch (err) {
            showToast('Export error: ' + err.message, 'error');
        }
    }

    async function saveProjectToPfp() {
        try {
            const resp = await fetch('/api/export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ format_id: 'pfp' })
            });
            if (resp.ok) {
                const blob = await resp.blob();
                const downloadUrl = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = downloadUrl;
                a.download = `${(project.name || 'project').replace(/\s+/g, '_')}.pfp`;
                document.body.appendChild(a);
                a.click();
                a.remove();
                showToast('Project saved as SQLite .pfp database file.', 'success');
            }
        } catch (e) {
            showToast('Save error: ' + e.message, 'error');
        }
    }

    async function createNewProject() {
        if (!confirm('Start a new project? Unsaved changes will be cleared.')) return;
        try {
            const resp = await fetch('/api/project/new', { method: 'POST' });
            const data = await resp.json();
            if (data.status === 'ok') {
                showToast('New project created.', 'info');
                loadProject();
            }
        } catch (e) {
            showToast(e.message, 'error');
        }
    }

    // --- Modal Management & Event Listeners ---

    function openModal(id) {
        document.getElementById(id).classList.add('active');
    }

    function closeModal(id) {
        document.getElementById(id).classList.remove('active');
    }

    function closeAllModals() {
        document.querySelectorAll('.modal-overlay').forEach(m => m.classList.remove('active'));
    }

    function initEventListeners() {
        // Quick buttons
        document.getElementById('btn-recalculate').onclick = recalculateSchedule;
        document.getElementById('btn-save-project').onclick = saveProjectToPfp;
        document.getElementById('btn-quick-new').onclick = createNewProject;
        document.getElementById('btn-quick-add-task').onclick = () => addNewTask(false);
        document.getElementById('btn-add-task').onclick = () => addNewTask(false);
        document.getElementById('btn-add-milestone').onclick = () => addNewTask(true);
        document.getElementById('btn-indent-task').onclick = indentTask;
        document.getElementById('btn-outdent-task').onclick = outdentTask;
        document.getElementById('btn-save-settings').onclick = saveSettings;
        document.getElementById('btn-fp-transfer').onclick = transferFPToProject;

        // Modals
        document.getElementById('btn-import-modal').onclick = () => {
            pendingImportFile = null;
            document.getElementById('import-preview-box').style.display = 'none';
            document.getElementById('btn-confirm-import').disabled = true;
            openModal('modal-import');
        };
        document.getElementById('btn-export-modal').onclick = () => openModal('modal-export');
        document.getElementById('btn-close-import').onclick = () => closeModal('modal-import');
        document.getElementById('btn-cancel-import').onclick = () => closeModal('modal-import');
        document.getElementById('btn-confirm-import').onclick = confirmImport;

        document.getElementById('btn-close-export').onclick = () => closeModal('modal-export');
        document.getElementById('btn-cancel-export').onclick = () => closeModal('modal-export');
        document.getElementById('btn-confirm-export').onclick = executeExport;

        document.getElementById('btn-close-task-modal').onclick = () => closeModal('modal-task-detail');
        document.getElementById('btn-cancel-task').onclick = () => closeModal('modal-task-detail');
        document.getElementById('btn-save-task').onclick = saveTaskModal;
        document.getElementById('btn-delete-task').onclick = () => deleteTask(editingTaskId);

        // People
        document.getElementById('btn-add-person').onclick = () => {
            document.getElementById('person-edit-name').value = '';
            openModal('modal-person');
        };
        document.getElementById('btn-close-person').onclick = () => closeModal('modal-person');
        document.getElementById('btn-cancel-person').onclick = () => closeModal('modal-person');
        document.getElementById('btn-save-person').onclick = addNewPerson;

        // FP Person add
        document.getElementById('btn-fp-add-person').onclick = () => {
            const name = prompt('Estimator name:');
            if (name) {
                fpPeople.push({
                    name: name,
                    hourly_rate: 35.0,
                    hours_per_complex_point: 2.5,
                    hours_per_simple_point: 1.0,
                    tasks: [{ name: "Feature estimation", type: "complex", points: 8 }]
                });
                renderFPCalculator();
            }
        };

        // Summary report buttons
        document.getElementById('btn-copy-report').onclick = () => {
            const text = document.getElementById('report-text-container').textContent;
            navigator.clipboard.writeText(text);
            showToast('Report copied to clipboard.', 'success');
        };
        document.getElementById('btn-download-report').onclick = () => {
            const text = document.getElementById('report-text-container').textContent;
            const blob = new Blob([text], { type: 'text/plain' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${(project.name || 'project').replace(/\s+/g, '_')}_summary.txt`;
            a.click();
            URL.revokeObjectURL(url);
        };

        // Task search filter
        const taskSearch = document.getElementById('task-search-input');
        if (taskSearch) {
            taskSearch.addEventListener('input', renderTasksTable);
        }

        // Drop zone
        const dropZone = document.getElementById('import-drop-zone');
        const fileInput = document.getElementById('import-file-input');
        document.getElementById('btn-browse-file').onclick = (e) => {
            e.stopPropagation();
            fileInput.click();
        };
        dropZone.onclick = () => fileInput.click();

        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('dragover');
        });
        dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            if (e.dataTransfer.files.length) {
                handleFileSelected(e.dataTransfer.files[0]);
            }
        });
        fileInput.addEventListener('change', () => {
            if (fileInput.files.length) {
                handleFileSelected(fileInput.files[0]);
            }
        });

        // Inline Title rename
        const titleInput = document.getElementById('project-title-input');
        titleInput.addEventListener('change', () => {
            if (project) {
                project.name = titleInput.value.trim() || 'Untitled Project';
                saveProjectState();
            }
        });
    }

    // --- Toast Notifications ---

    function showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        container.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transition = 'opacity 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, 3500);
    }

    // --- Utilities ---

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function truncate(str, maxLen = 20) {
        if (!str) return '';
        return str.length > maxLen ? str.substring(0, maxLen - 1) + '…' : str;
    }

})();
