// State Management
let appState = {
    invoices: [],
    filteredInvoices: [],
    settings: { use_mock: true, sheet_id: "" },
    currentTab: "dashboard",
    filters: {
        category: "all",
        search: ""
    },
    sort: {
        column: "date",
        direction: "desc"
    },
    pagination: {
        currentPage: 1,
        itemsPerPage: 8
    }
};

// DOM Elements
const sidebarNav = document.querySelectorAll(".nav-item");
const tabContents = document.querySelectorAll(".tab-content");
const statusDot = document.getElementById("status-dot");
const statusLabel = document.getElementById("status-label");
const sheetInfo = document.getElementById("sheet-info");
const btnSyncNow = document.getElementById("btn-sync-now");
const syncIcon = btnSyncNow.querySelector(".sync-icon");

// Chart references
let trendChart = null;
let categoryChart = null;

function setupReportButtons() {
    const downloadBtn = document.getElementById('btn-download-report');
    const statusEl = document.getElementById('report-status');
    const picker = document.getElementById('report-month-picker');

    if (!downloadBtn) return;

    downloadBtn.addEventListener('click', async () => {
        const month = picker.value;
        if (!month) { statusEl.textContent = 'בחר חודש תחילה'; return; }
        statusEl.textContent = 'מייצר דוח...';
        try {
            const res = await fetch(`/api/reports/monthly?month=${month}`, { credentials: "include" });
            if (res.status === 401) { showLoginScreen(); return; }
            if (!res.ok) {
                const err = await res.json();
                statusEl.textContent = `שגיאה: ${err.detail}`;
                return;
            }
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `expense_report_${month}.pdf`;
            a.click();
            URL.revokeObjectURL(url);
            statusEl.textContent = 'הדוח הורד בהצלחה ✓';
        } catch (e) {
            statusEl.textContent = 'שגיאה בהורדת הדוח';
        }
    });
}

// Initialize Application
document.addEventListener("DOMContentLoaded", async () => {
    // Gate the whole app behind Google Sign-In. If not authenticated, show the
    // login screen and stop — no dashboard, no data fetches.
    const user = await fetchCurrentUser();
    if (!user) {
        showLoginScreen();
        return;
    }
    showApp(user);

    setupTabNavigation();
    setupFiltersAndSearch();
    setupSettingsForm();
    setupSyncAction();
    setupModalActions();
    setupReportButtons();
    setupLogout();

    // Set month picker default to current month
    const picker = document.getElementById('report-month-picker');
    if (picker) {
        const now = new Date();
        picker.value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
    }

    // Load initial settings and invoices
    await fetchSettings();
    await fetchInvoices();
});

// 0. Authentication / session
async function fetchCurrentUser() {
    try {
        const res = await fetch("/api/auth/me", { credentials: "include" });
        if (res.ok) return await res.json();
    } catch (e) {
        console.error("Auth check failed:", e);
    }
    return null;
}

function showLoginScreen() {
    const login = document.getElementById("login-screen");
    const app = document.getElementById("app-container");
    if (login) login.style.display = "flex";
    if (app) app.style.display = "none";
}

function showApp(user) {
    const login = document.getElementById("login-screen");
    const app = document.getElementById("app-container");
    if (login) login.style.display = "none";
    if (app) app.style.display = "flex";

    const nameEl = document.getElementById("user-name");
    const avatarEl = document.getElementById("user-avatar");
    if (nameEl) nameEl.textContent = user.name || user.email || "";
    if (avatarEl) {
        if (user.picture) {
            avatarEl.src = user.picture;
            avatarEl.style.display = "block";
        } else {
            avatarEl.style.display = "none";
        }
    }
}

function setupLogout() {
    const btn = document.getElementById("btn-logout");
    if (!btn) return;
    btn.addEventListener("click", async () => {
        try {
            await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
        } catch (e) {
            console.error("Logout failed:", e);
        }
        // Back to the login screen
        window.location.reload();
    });
}

// 1. Tab Navigation
function setupTabNavigation() {
    sidebarNav.forEach(nav => {
        nav.addEventListener("click", (e) => {
            e.preventDefault();
            const tabId = nav.getAttribute("data-tab");
            
            // Toggle active sidebar item
            sidebarNav.forEach(item => item.classList.remove("active"));
            nav.classList.add("active");
            
            // Toggle active content tab
            tabContents.forEach(tab => {
                tab.classList.remove("active");
                if (tab.id === `tab-${tabId}`) {
                    tab.classList.add("active");
                }
            });
            
            appState.currentTab = tabId;
            
            // Dynamic Header Text
            const pageTitle = document.getElementById("page-title");
            const pageSubtitle = document.getElementById("page-subtitle");
            
            if (tabId === "dashboard") {
                pageTitle.textContent = "לוח בקרה פיננסי";
                pageSubtitle.textContent = "מעקב וניתוח הוצאות שוטפות וחשבוניות חודשיות מ-Gmail";
            } else if (tabId === "invoices") {
                pageTitle.textContent = "רשימת חשבוניות מנותחות";
                pageSubtitle.textContent = "צפייה, חיפוש וסינון כל ההוצאות שחולצו על ידי סוכן ה-AI";
                renderFullInvoicesTable();
            } else if (tabId === "settings") {
                pageTitle.textContent = "הגדרות סוכן ה-AI";
                pageSubtitle.textContent = "מצב הריצה של הסוכן ופרטי החשבון המחובר";
            }
        });
    });

    // View All Link shortcut
    document.getElementById("link-view-all").addEventListener("click", (e) => {
        e.preventDefault();
        const invoiceTab = document.querySelector('[data-tab="invoices"]');
        if (invoiceTab) invoiceTab.click();
    });
}

// 2. Fetch & Save Settings
async function fetchSettings() {
    try {
        const response = await fetch("/api/settings", { credentials: "include" });
        if (response.ok) {
            const data = await response.json();
            appState.settings = data;

            // Update UI
            document.getElementById("setting-use-mock").checked = data.use_mock;

            updateStatusIndicators();
        }
    } catch (error) {
        console.error("Error fetching settings:", error);
        showToast("שגיאה בטעינת ההגדרות מהשרת", "error");
    }
}

function updateStatusIndicators() {
    const isMock = appState.settings.use_mock;

    if (isMock) {
        statusDot.className = "status-dot pulsating";
        statusDot.style.backgroundColor = "var(--amber)";
        statusLabel.textContent = "מצב סימולציה";
        sheetInfo.innerHTML = `<i class="fa-solid fa-flask"></i> <span>נתוני דמו</span>`;
    } else {
        statusDot.className = "status-dot active";
        statusDot.style.backgroundColor = "var(--success)";
        statusLabel.textContent = "מצב אמת פעיל";
        sheetInfo.innerHTML = `<i class="fa-solid fa-envelope-circle-check" style="color: var(--success)"></i> <span>מחובר ל-Gmail</span>`;
    }
}

function setupSettingsForm() {
    document.getElementById("btn-save-settings").addEventListener("click", async () => {
        const useMock = document.getElementById("setting-use-mock").checked;

        const settingsPayload = { use_mock: useMock };

        try {
            const response = await fetch("/api/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                credentials: "include",
                body: JSON.stringify(settingsPayload)
            });

            if (response.ok) {
                appState.settings = settingsPayload;
                updateStatusIndicators();
                showToast("ההגדרות נשמרו בהצלחה!", "success");
            } else {
                showToast("נכשלה שמירת ההגדרות", "error");
            }
        } catch (error) {
            console.error("Error saving settings:", error);
            showToast("שגיאה בתקשורת עם השרת", "error");
        }
    });
}

// 3. Fetch Invoices & Update Metrics
async function fetchInvoices() {
    try {
        const response = await fetch("/api/invoices", { credentials: "include" });
        if (response.status === 401) { showLoginScreen(); return; }
        if (response.ok) {
            const result = await response.json();
            appState.invoices = result.data || [];
            appState.filteredInvoices = [...appState.invoices];
            
            calculateKPIs();
            renderCharts();
            renderRecentInvoicesTable();
            renderFullInvoicesTable();
        }
    } catch (error) {
        console.error("Error fetching invoices:", error);
        showToast("שגיאה בקבלת נתוני הוצאות מהשרת", "error");
    }
}

function calculateKPIs() {
    const invoices = appState.invoices;
    
    // 1. Calculate Monthly Expenses
    const currentMonth = new Date().getMonth();
    const currentYear = new Date().getFullYear();
    
    let totalILS = 0;
    let totalUSD = 0;
    let monthlyServiceSet = new Set();
    
    invoices.forEach(inv => {
        const invDate = new Date(inv.date);
        const period = inv.subscription_period || 'monthly';

        // Count active subscriptions: annual subs use 400-day window, monthly use 45 days
        const diffDays = Math.ceil(Math.abs(new Date() - invDate) / (1000 * 60 * 60 * 24));
        const activeWindow = period === 'annual' ? 400 : 45;
        if (diffDays <= activeWindow) {
            monthlyServiceSet.add(inv.service_name);
        }

        // Sum current month — amortize annual invoices to their monthly equivalent
        if (invDate.getMonth() === currentMonth && invDate.getFullYear() === currentYear) {
            const effectiveAmount = period === 'annual' ? inv.amount / 12 : inv.amount;
            if (inv.currency === "ILS") {
                totalILS += effectiveAmount;
            } else if (inv.currency === "USD") {
                totalUSD += effectiveAmount;
            }
        }
    });

    // Set KPI Values
    document.getElementById("kpi-monthly-ils").textContent = `₪${totalILS.toLocaleString('he-IL', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    document.getElementById("kpi-monthly-usd").textContent = `$${totalUSD.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    document.getElementById("kpi-active-subs").textContent = monthlyServiceSet.size;

    // 2. Find Expensive Service (amortize annual to monthly for fair comparison)
    let serviceExpenses = {};
    invoices.forEach(inv => {
        const name = inv.service_name;
        const period = inv.subscription_period || 'monthly';
        const monthlyAmount = period === 'annual' ? inv.amount / 12 : inv.amount;
        const amtInILS = inv.currency === "USD" ? monthlyAmount * 3.7 : monthlyAmount;

        if (!serviceExpenses[name]) {
            serviceExpenses[name] = { total: 0, monthlyRaw: monthlyAmount, curr: inv.currency, period };
        }
        serviceExpenses[name].total += amtInILS;
    });

    let mostExpensive = "-";
    let maxAmt = 0;
    let maxRaw = 0;
    let maxCurr = "₪";
    let maxPeriod = "monthly";

    for (let key in serviceExpenses) {
        if (serviceExpenses[key].total > maxAmt) {
            maxAmt = serviceExpenses[key].total;
            mostExpensive = key;
            maxRaw = serviceExpenses[key].monthlyRaw;
            maxCurr = serviceExpenses[key].curr;
            maxPeriod = serviceExpenses[key].period;
        }
    }

    document.getElementById("kpi-expensive-service").textContent = mostExpensive;
    const currSym = maxCurr === "USD" ? "$" : "₪";
    const periodLabel = maxPeriod === 'annual'
        ? `${currSym}${(maxRaw * 12).toFixed(2)} / שנה (≈${currSym}${maxRaw.toFixed(2)} / חודש)`
        : `${currSym}${maxRaw.toFixed(2)} / חודש`;
    document.getElementById("kpi-expensive-amount").textContent = periodLabel;
}

// 4. Synchronization Action
function setupSyncAction() {
    btnSyncNow.addEventListener("click", async () => {
        // Prevent double-click
        if (btnSyncNow.classList.contains("disabled")) return;
        
        btnSyncNow.classList.add("disabled");
        syncIcon.classList.add("spinning");
        btnSyncNow.querySelector("span").textContent = "סורק ומנתח...";
        
        showToast("סוכן ה-AI מתחיל לסרוק את תיבת ה-Gmail שלך...", "info");
        
        try {
            const response = await fetch("/api/sync", {
                method: "POST",
                credentials: "include"
            });

            if (response.status === 401) { showLoginScreen(); return; }
            if (response.ok) {
                const result = await response.json();
                
                showToast(result.message || "הסנכרון הושלם בהצלחה!", "success");
                
                // Reload data
                await fetchInvoices();
            } else {
                const errorData = await response.json();
                showToast(`הסנכרון נכשל: ${errorData.detail || "שגיאה בשרת"}`, "error");
            }
        } catch (error) {
            console.error("Error during sync:", error);
            showToast("שגיאה בחיבור לשרת לצורך סנכרון", "error");
        } finally {
            btnSyncNow.classList.remove("disabled");
            syncIcon.classList.remove("spinning");
            btnSyncNow.querySelector("span").textContent = "סנכרן כעת";
        }
    });
}

// 5. Chart Rendering
function renderCharts() {
    const invoices = appState.invoices;
    
    // Group invoices by Month for Trend
    // Formats dates as YYYY-MM — amortize annual invoices to monthly equivalent
    let monthlyData = {};
    invoices.forEach(inv => {
        if (!inv.date) return;
        const monthKey = inv.date.substring(0, 7); // "2026-05"
        const period = inv.subscription_period || 'monthly';
        const effectiveAmount = period === 'annual' ? inv.amount / 12 : inv.amount;

        if (!monthlyData[monthKey]) {
            monthlyData[monthKey] = { ILS: 0, USD: 0 };
        }

        if (inv.currency === "ILS") {
            monthlyData[monthKey].ILS += effectiveAmount;
        } else if (inv.currency === "USD") {
            monthlyData[monthKey].USD += effectiveAmount;
        }
    });
    
    // Sort month keys ascending
    const monthKeysSorted = Object.keys(monthlyData).sort().slice(-6); // past 6 months
    const ilsValues = monthKeysSorted.map(k => monthlyData[k].ILS);
    const usdValues = monthKeysSorted.map(k => monthlyData[k].USD);
    
    // Convert YYYY-MM labels to Hebrew month names
    const labelMonths = monthKeysSorted.map(k => {
        const [year, month] = k.split("-");
        const date = new Date(year, parseInt(month) - 1, 1);
        return date.toLocaleDateString('he-IL', { month: 'short', year: '2-digit' });
    });
    
    // Destruct existing trend chart
    if (trendChart) trendChart.destroy();
    
    const ctxTrend = document.getElementById("expensesTrendChart").getContext("2d");
    trendChart = new Chart(ctxTrend, {
        type: 'bar',
        data: {
            labels: labelMonths,
            datasets: [
                {
                    label: 'ש"ח (₪)',
                    data: ilsValues,
                    backgroundColor: 'rgba(139, 92, 246, 0.65)',
                    borderColor: '#8b5cf6',
                    borderWidth: 2,
                    borderRadius: 8,
                    yAxisID: 'y'
                },
                {
                    label: 'דולר ($)',
                    data: usdValues,
                    backgroundColor: 'rgba(6, 182, 212, 0.65)',
                    borderColor: '#06b6d4',
                    borderWidth: 2,
                    borderRadius: 8,
                    yAxisID: 'y1'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false } // Custom legend in HTML
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: '#94a3b8' }
                },
                y: {
                    type: 'linear',
                    display: true,
                    position: 'right', // RTL right
                    grid: { color: 'rgba(255, 255, 255, 0.05)' },
                    ticks: { color: '#c084fc', callback: value => '₪' + value },
                    title: { display: true, text: 'הוצאות בש"ח', color: '#c084fc' }
                },
                y1: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    grid: { drawOnChartArea: false }, // avoid double lines
                    ticks: { color: '#22d3ee', callback: value => '$' + value },
                    title: { display: true, text: 'הוצאות בדולר', color: '#22d3ee' }
                }
            }
        }
    });
    
    // Group invoices by Category for Doughnut
    let categorySums = {};
    invoices.forEach(inv => {
        // Standardize category name or group under Other
        const cat = inv.category || "Other";
        // Convert to ILS for standard proportional breakdown
        const amtInILS = inv.currency === "USD" ? inv.amount * 3.7 : inv.amount;
        
        categorySums[cat] = (categorySums[cat] || 0) + amtInILS;
    });
    
    const catLabels = Object.keys(categorySums);
    const catValues = Object.values(categorySums);
    
    // Color palettes for categories
    const catColors = {
        'SaaS/Subscription': 'rgba(139, 92, 246, 0.75)',
        'Cloud/Hosting': 'rgba(6, 182, 212, 0.75)',
        'Utilities': 'rgba(245, 158, 11, 0.75)',
        'Entertainment': 'rgba(244, 63, 94, 0.75)',
        'Other': 'rgba(100, 116, 139, 0.65)'
    };
    
    const backgroundColors = catLabels.map(label => catColors[label] || catColors['Other']);
    
    if (categoryChart) categoryChart.destroy();
    
    const ctxCat = document.getElementById("categoryDistributionChart").getContext("2d");
    categoryChart = new Chart(ctxCat, {
        type: 'doughnut',
        data: {
            labels: catLabels.map(translateCategory),
            datasets: [{
                data: catValues,
                backgroundColor: backgroundColors,
                borderColor: 'rgba(255,255,255,0.05)',
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { color: '#94a3b8', boxWidth: 12, padding: 15 }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            let label = context.label || '';
                            let value = context.parsed || 0;
                            return `${label}: ₪${value.toLocaleString('he-IL', {maximumFractionDigits: 0})} (שקלים שווי ערך)`;
                        }
                    }
                }
            },
            cutout: '65%'
        }
    });
}

function translateCategory(cat) {
    const translations = {
        'SaaS/Subscription': 'מינויים ושירותים (SaaS)',
        'Cloud/Hosting': 'תשתיות ענן ואחסון',
        'Utilities': 'חשבונות ושירותי בית',
        'Entertainment': 'בידור ופנאי',
        'Other': 'אחר'
    };
    return translations[cat] || cat;
}

// 6. Data Tables Rendering
function renderRecentInvoicesTable() {
    const tbody = document.getElementById("recent-invoices-tbody");
    tbody.innerHTML = "";
    
    // Take only the first 5 invoices
    const recents = appState.invoices.slice(0, 5);
    
    if (recents.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted);">לא נמצאו חשבוניות מנותחות. לחץ על 'סנכרן כעת' כדי להתחיל!</td></tr>`;
        return;
    }
    
    recents.forEach(inv => {
        const row = createInvoiceRow(inv);
        tbody.appendChild(row);
    });
}

function createInvoiceRow(inv) {
    const tr = document.createElement("tr");
    
    const dateFormatted = new Date(inv.date).toLocaleDateString('he-IL', { year: 'numeric', month: '2-digit', day: '2-digit' });
    
    // Format amount cell
    const currClass = inv.currency === "USD" ? "currency-usd" : "currency-ils";
    const currSymbol = inv.currency === "USD" ? "$" : "₪";
    const amtStr = `${currSymbol}${inv.amount.toFixed(2)}`;
    
    // Map category css pills
    let catClass = "cat-other";
    if (inv.category === "SaaS/Subscription") catClass = "cat-saas";
    else if (inv.category === "Cloud/Hosting") catClass = "cat-cloud";
    else if (inv.category === "Utilities") catClass = "cat-utilities";
    else if (inv.category === "Entertainment") catClass = "cat-entertainment";
    
    const periodBadge = (inv.subscription_period === 'annual')
        ? `<span class="period-badge period-annual">שנתי</span>` : '';

    tr.innerHTML = `
        <td class="date-cell">${dateFormatted}</td>
        <td class="service-name-cell">${periodBadge}${inv.service_name}</td>
        <td><span class="category-pill ${catClass}">${translateCategory(inv.category)}</span></td>
        <td class="amount-cell">${amtStr} <span class="currency-badge ${currClass}">${inv.currency}</span></td>
        <td class="invoice-id-cell">${inv.invoice_id || '-'}</td>
        <td>
            <button class="btn-icon btn-view-pdf" data-id="${inv.id || ''}" title="צפה בחשבונית המקורית">
                <i class="fa-solid fa-file-pdf"></i>
            </button>
            <button class="btn-icon btn-view-details" data-id="${inv.id || ''}">
                <i class="fa-solid fa-magnifying-glass-chart"></i>
            </button>
        </td>
    `;


    tr.querySelector(".btn-view-details").addEventListener("click", () => {
        showInvoiceDetailsModal(inv);
    });
    tr.querySelector(".btn-view-pdf").addEventListener("click", () => {
        showInvoicePdf(inv);
    });

    return tr;
}

// 7. Filtering & Sorting for Invoices Tab
function setupFiltersAndSearch() {
    const searchInput = document.getElementById("invoice-search");
    searchInput.addEventListener("input", (e) => {
        appState.filters.search = e.target.value.toLowerCase().trim();
        appState.pagination.currentPage = 1;
        applyFiltersAndRender();
    });
    
    const filterButtons = document.querySelectorAll(".filter-btn");
    filterButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            filterButtons.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            
            appState.filters.category = btn.getAttribute("data-category");
            appState.pagination.currentPage = 1;
            applyFiltersAndRender();
        });
    });
    
    // Sortable Headers
    const headers = document.querySelectorAll("#full-invoices-table th.sortable");
    headers.forEach(header => {
        header.addEventListener("click", () => {
            const col = header.getAttribute("data-sort");
            
            if (appState.sort.column === col) {
                appState.sort.direction = appState.sort.direction === "asc" ? "desc" : "asc";
            } else {
                appState.sort.column = col;
                appState.sort.direction = "asc";
            }
            
            // Update icons
            headers.forEach(h => {
                const icon = h.querySelector("i");
                icon.className = "fa-solid fa-sort";
            });
            const activeIcon = header.querySelector("i");
            activeIcon.className = appState.sort.direction === "asc" ? "fa-solid fa-sort-up" : "fa-solid fa-sort-down";
            
            applyFiltersAndRender();
        });
    });
}

function applyFiltersAndRender() {
    let results = [...appState.invoices];
    
    // Category Filter
    if (appState.filters.category !== "all") {
        results = results.filter(inv => inv.category === appState.filters.category);
    }
    
    // Search filter
    if (appState.filters.search) {
        const query = appState.filters.search;
        results = results.filter(inv => 
            inv.service_name.toLowerCase().includes(query) ||
            (inv.description && inv.description.toLowerCase().includes(query)) ||
            (inv.invoice_id && inv.invoice_id.toLowerCase().includes(query))
        );
    }
    
    // Sort
    results.sort((a, b) => {
        let valA = a[appState.sort.column];
        let valB = b[appState.sort.column];
        
        if (appState.sort.column === "amount") {
            // Sort by amount normalized or raw amount? Let's sort by raw amount
            valA = Number(valA) || 0;
            valB = Number(valB) || 0;
        } else {
            valA = String(valA || "").toLowerCase();
            valB = String(valB || "").toLowerCase();
        }
        
        if (valA < valB) return appState.sort.direction === "asc" ? -1 : 1;
        if (valA > valB) return appState.sort.direction === "asc" ? 1 : -1;
        return 0;
    });
    
    appState.filteredInvoices = results;
    renderFullInvoicesTable();
}

function renderFullInvoicesTable() {
    const tbody = document.getElementById("invoices-tbody");
    tbody.innerHTML = "";
    
    const invoices = appState.filteredInvoices;
    const { currentPage, itemsPerPage } = appState.pagination;
    
    if (invoices.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 3rem;">לא נמצאו חשבוניות העונות לתנאי החיפוש והסינון.</td></tr>`;
        document.getElementById("pagination-ctrl").innerHTML = "";
        return;
    }
    
    // Paginate
    const totalPages = Math.ceil(invoices.length / itemsPerPage);
    const startIndex = (currentPage - 1) * itemsPerPage;
    const paginatedInvoices = invoices.slice(startIndex, startIndex + itemsPerPage);
    
    paginatedInvoices.forEach(inv => {
        const tr = document.createElement("tr");
        
        const dateFormatted = new Date(inv.date).toLocaleDateString('he-IL', { year: 'numeric', month: '2-digit', day: '2-digit' });
        
        const currClass = inv.currency === "USD" ? "currency-usd" : "currency-ils";
        const currSymbol = inv.currency === "USD" ? "$" : "₪";
        
        let catClass = "cat-other";
        if (inv.category === "SaaS/Subscription") catClass = "cat-saas";
        else if (inv.category === "Cloud/Hosting") catClass = "cat-cloud";
        else if (inv.category === "Utilities") catClass = "cat-utilities";
        else if (inv.category === "Entertainment") catClass = "cat-entertainment";
        
        const invPeriodBadge = (inv.subscription_period === 'annual')
            ? `<span class="period-badge period-annual">שנתי</span>` : '';

        tr.innerHTML = `
            <td class="date-cell">${dateFormatted}</td>
            <td class="service-name-cell">${invPeriodBadge}${inv.service_name}</td>
            <td><span class="category-pill ${catClass}">${translateCategory(inv.category)}</span></td>
            <td class="amount-cell">${currSymbol}${inv.amount.toFixed(2)} <span class="currency-badge ${currClass}">${inv.currency}</span></td>
            <td style="color: var(--text-secondary); max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${inv.description || '-'}</td>
            <td class="invoice-id-cell">${inv.invoice_id || '-'}</td>
            <td>
                <button class="btn-icon btn-view-pdf" data-id="${inv.id}" title="צפה בחשבונית המקורית">
                    <i class="fa-solid fa-file-pdf"></i>
                </button>
                <button class="btn-icon btn-view-details" data-id="${inv.id}">
                    <i class="fa-solid fa-magnifying-glass-chart"></i>
                </button>
            </td>
        `;

        tr.querySelector(".btn-view-details").addEventListener("click", () => {
            showInvoiceDetailsModal(inv);
        });
        tr.querySelector(".btn-view-pdf").addEventListener("click", () => {
            showInvoicePdf(inv);
        });

        tbody.appendChild(tr);
    });
    
    renderPagination(totalPages);
}

function renderPagination(totalPages) {
    const container = document.getElementById("pagination-ctrl");
    container.innerHTML = "";
    
    if (totalPages <= 1) return;
    
    const { currentPage } = appState.pagination;
    
    // Max 5 page numbers displayed
    let startPage = Math.max(1, currentPage - 2);
    let endPage = Math.min(totalPages, startPage + 4);
    
    if (endPage - startPage < 4) {
        startPage = Math.max(1, endPage - 4);
    }
    
    // Back Button
    if (currentPage > 1) {
        const btnPrev = document.createElement("button");
        btnPrev.className = "page-btn";
        btnPrev.innerHTML = `<i class="fa-solid fa-chevron-right"></i>`; // Chevron Right in RTL context is back
        btnPrev.addEventListener("click", () => {
            appState.pagination.currentPage--;
            renderFullInvoicesTable();
        });
        container.appendChild(btnPrev);
    }
    
    // Page Numbers
    for (let p = startPage; p <= endPage; p++) {
        const btnPage = document.createElement("button");
        btnPage.className = `page-btn ${currentPage === p ? 'active' : ''}`;
        btnPage.textContent = p;
        btnPage.addEventListener("click", () => {
            appState.pagination.currentPage = p;
            renderFullInvoicesTable();
        });
        container.appendChild(btnPage);
    }
    
    // Next Button
    if (currentPage < totalPages) {
        const btnNext = document.createElement("button");
        btnNext.className = "page-btn";
        btnNext.innerHTML = `<i class="fa-solid fa-chevron-left"></i>`; // Chevron Left in RTL context is next
        btnNext.addEventListener("click", () => {
            appState.pagination.currentPage++;
            renderFullInvoicesTable();
        });
        container.appendChild(btnNext);
    }
}

// 8. Invoice Details Modal Interactions
function setupModalActions() {
    const modal = document.getElementById("invoice-modal");
    const closeBtn = document.getElementById("btn-close-modal");

    closeBtn.addEventListener("click", () => {
        modal.classList.remove("show");
    });

    // Close on click outside card
    modal.addEventListener("click", (e) => {
        if (e.target === modal) {
            modal.classList.remove("show");
        }
    });

    // PDF viewer modal
    const pdfModal = document.getElementById("pdf-modal");
    const pdfCloseBtn = document.getElementById("btn-close-pdf-modal");
    pdfCloseBtn.addEventListener("click", closePdfModal);
    pdfModal.addEventListener("click", (e) => {
        if (e.target === pdfModal) closePdfModal();
    });
}

function closePdfModal() {
    const pdfModal = document.getElementById("pdf-modal");
    const frame = document.getElementById("pdf-frame");
    pdfModal.classList.remove("show");
    // Release the blob URL and clear the iframe so nothing keeps rendering in the background
    if (frame.dataset.blobUrl) {
        URL.revokeObjectURL(frame.dataset.blobUrl);
        delete frame.dataset.blobUrl;
    }
    frame.removeAttribute("srcdoc");
    frame.src = "about:blank";
    document.getElementById("pdf-external-link").style.display = "none";
}

// Opens the document modal and shows the original invoice — a PDF attachment when present,
// otherwise the email body itself (with a hosted-invoice link surfaced when one is detected).
async function showInvoicePdf(inv) {
    const pdfModal = document.getElementById("pdf-modal");
    const frame = document.getElementById("pdf-frame");
    const loading = document.getElementById("pdf-loading");
    const fallback = document.getElementById("pdf-fallback");
    const fallbackText = document.getElementById("pdf-fallback-text");
    const gmailLink = document.getElementById("pdf-gmail-link");
    const externalLink = document.getElementById("pdf-external-link");

    document.getElementById("pdf-modal-title").textContent = inv.service_name || "חשבונית";

    // Reset state
    frame.style.display = "none";
    frame.removeAttribute("srcdoc");
    frame.src = "about:blank";
    fallback.style.display = "none";
    externalLink.style.display = "none";
    loading.style.display = "flex";
    pdfModal.classList.add("show");

    gmailLink.href = `https://mail.google.com/mail/u/0/#all/${inv.id}`;

    const showFallback = (msg) => {
        loading.style.display = "none";
        frame.style.display = "none";
        fallbackText.textContent = msg;
        fallback.style.display = "flex";
    };

    if (!inv.scanned_account || inv.scanned_account === "simulation") {
        showFallback("אין מסמך זמין במצב הדגמה.");
        return;
    }

    const id = encodeURIComponent(inv.id);

    try {
        const docRes = await fetch(`/api/invoices/${id}/document`, { credentials: "include" });
        const doc = docRes.ok ? await docRes.json() : { type: "none" };

        if (doc.type === "pdf") {
            // Stream the PDF attachment and embed it
            const res = await fetch(`/api/invoices/${id}/pdf`, { credentials: "include" });
            const contentType = res.headers.get("content-type") || "";
            if (!res.ok || !contentType.includes("application/pdf")) {
                showFallback("לא ניתן לטעון את קובץ ה-PDF.");
                return;
            }
            const blobUrl = URL.createObjectURL(await res.blob());
            frame.dataset.blobUrl = blobUrl;
            frame.removeAttribute("sandbox"); // browser PDF viewer needs no sandbox
            frame.src = blobUrl;
            loading.style.display = "none";
            frame.style.display = "block";
        } else if (doc.type === "page") {
            // Surface a hosted invoice link (opens in a new tab) when one was detected
            if (doc.link) {
                externalLink.href = doc.link;
                externalLink.style.display = "inline-flex";
            }
            if (doc.html) {
                // Render the email body itself, sandboxed (no scripts) for safety
                frame.setAttribute("sandbox", "");
                frame.srcdoc = doc.html;
                loading.style.display = "none";
                frame.style.display = "block";
            } else if (doc.link) {
                // Link only, nothing to embed — point the user to the external page
                showFallback("החשבונית מתארחת בעמוד חיצוני. פתח אותה בכפתור שלמעלה.");
            } else {
                showFallback("לא נמצא תוכן להצגה.");
            }
        } else {
            showFallback("לא נמצא מסמך חשבונית זמין להצגה.");
        }
    } catch (err) {
        console.error("Failed to load invoice document:", err);
        showFallback("אירעה שגיאה בטעינת החשבונית.");
    }
}

function showInvoiceDetailsModal(inv) {
    const modal = document.getElementById("invoice-modal");
    
    let catClass = "cat-other";
    if (inv.category === "SaaS/Subscription") catClass = "cat-saas";
    else if (inv.category === "Cloud/Hosting") catClass = "cat-cloud";
    else if (inv.category === "Utilities") catClass = "cat-utilities";
    else if (inv.category === "Entertainment") catClass = "cat-entertainment";
    
    const catBadge = document.getElementById("modal-category");
    catBadge.className = `category-badge ${catClass}`;
    catBadge.textContent = translateCategory(inv.category);
    
    document.getElementById("modal-service-name").textContent = inv.service_name;
    document.getElementById("modal-invoice-id").textContent = inv.invoice_id ? `חשבונית מס׳ ${inv.invoice_id}` : 'לא צוין מספר חשבונית';
    
    const dateFormatted = new Date(inv.date).toLocaleDateString('he-IL', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
    document.getElementById("modal-date").textContent = dateFormatted;
    
    const currSymbol = inv.currency === "USD" ? "$" : "₪";
    document.getElementById("modal-amount").textContent = `${currSymbol}${inv.amount.toFixed(2)}`;
    
    document.getElementById("modal-description").textContent = inv.description || "אין תיאור מורחב.";
    document.getElementById("modal-email-subject").textContent = inv.email_subject || "נושא מייל סימולטיבי";
    document.getElementById("modal-subscription-period").textContent =
        (inv.subscription_period === 'annual') ? 'שנתי (Annual)' : 'חודשי (Monthly)';

    // Wire the "view original invoice" button (re-bound each open to the current invoice)
    const viewBtn = document.getElementById("modal-view-invoice");
    viewBtn.onclick = () => showInvoicePdf(inv);

    modal.classList.add("show");
}

// 9. Toast Notifications
function showToast(message, type = "info") {
    const container = document.getElementById("toast-container");
    
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    
    let icon = "fa-circle-info";
    if (type === "success") icon = "fa-circle-check";
    else if (type === "error") icon = "fa-circle-exclamation";
    
    toast.innerHTML = `
        <i class="fa-solid ${icon} toast-icon"></i>
        <div class="toast-message">${message}</div>
    `;
    
    container.appendChild(toast);
    
    // Trigger animation frame
    setTimeout(() => {
        toast.classList.add("show");
    }, 10);
    
    // Remove after 4.5 seconds
    setTimeout(() => {
        toast.classList.remove("show");
        setTimeout(() => {
            toast.remove();
        }, 300);
    }, 4500);
}
