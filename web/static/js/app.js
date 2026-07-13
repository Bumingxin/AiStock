(function(){
"use strict";

/* ─── Session ─── */
function getCookie(name) {
    const m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
    return m ? decodeURIComponent(m[1]) : null;
}
function setCookie(name, value, days) {
    const d = new Date();
    d.setTime(d.getTime() + days * 86400000);
    document.cookie = `${name}=${encodeURIComponent(value)};expires=${d.toUTCString()};path=/;SameSite=Lax`;
}
function ensureSession() {
    return getCookie("session_id") || "";
}
ensureSession();

function getCsrfToken() {
    var m = document.cookie.match(/(?:^|; )csrf_token=([^;]*)/);
    return m ? decodeURIComponent(m[1]) : '';
}

let ws = null;
let timerInterval = null;
let startTime = null;
let selectedStockIndex = -1;
let chatHistory = [];
let allResults = [];
let allReports = [];
let deepResult = null;

const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

/* ─── Tabs ─── */
$$(".nav-tab[data-tab]").forEach(tab => {
    tab.addEventListener("click", (e) => {
        if (location.pathname === "/") {
            e.preventDefault();
            switchTab(tab.dataset.tab);
            const hash = tab.dataset.tab === "monitor" ? "" : `#tab-${tab.dataset.tab}`;
            history.replaceState(null, "", `${location.pathname}${hash}`);
        }
    });
});

function tabFromHash() {
    const match = location.hash.match(/^#tab-(monitor|dashboard|chat|deep)$/);
    return match ? match[1] : "monitor";
}

function syncTabFromHash() {
    switchTab(tabFromHash());
}

/* ─── WebSocket ─── */
function connectWS() {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${protocol}//${location.host}/ws/logs`);
    ws.onopen = () => { ws.send("ping"); };
    ws.onmessage = (e) => {
        try {
            const msg = JSON.parse(e.data);
            handleWSMessage(msg);
        } catch(err) {}
    };
    ws.onclose = () => { setTimeout(connectWS, 2000); };
    ws.onerror = () => { ws.close(); };
}

function handleWSMessage(msg) {
    if (msg.type === "log") {
        appendLog(msg.detail, msg.stage);
    } else if (msg.type === "progress") {
        updateProgress(msg.stage, msg.progress, msg.status);
    } else if (msg.type === "done") {
        allResults = msg.result || {};
        loadResults();
        setRunningUI(false);
    } else if (msg.type === "error") {
        appendLog(`错误：${msg.detail}`, "error");
        setRunningUI(false);
    } else if (msg.type === "cancelled") {
        appendLog(`已停止：${msg.detail}`, "warn");
        setRunningUI(false);
    }
}

function appendLog(text, stage) {
    const area = $("#log-area");
    if (!area) return;
    const line = document.createElement("div");
    line.className = "log-line";
    if (text.includes("完成") || text.includes("选出") || text.includes("通过")) {
        line.classList.add("success");
    } else if (text.includes("失败") || text.includes("异常")) {
        line.classList.add("error");
    } else if (text.includes("=") || text.includes("【")) {
        line.classList.add("header");
    } else if (text.includes("警") || text.includes("弱势")) {
        line.classList.add("warn");
    } else {
        line.classList.add("info");
    }
    line.textContent = text;
    area.appendChild(line);
    area.scrollTop = area.scrollHeight;
}

function updateProgress(stage, progress, statusText) {
    $("#progress-fill").style.width = progress + "%";
    $("#nav-status").textContent = statusText;
    const isDone = progress >= 100;
    const isStopped = statusText === "已停止";
    const isError = statusText.includes("异常");
    let badgeClass = "status-ready";
    if (isDone) badgeClass = "status-done";
    else if (isError) badgeClass = "status-error";
    else if (isStopped) badgeClass = "status-error";
    else if (progress > 0) badgeClass = "status-running";
    $("#nav-status").className = "status-badge " + badgeClass;

    $$(".stage").forEach(s => {
        const sn = parseInt(s.dataset.stage);
        s.classList.remove("active", "done");
        if (sn < stage) s.classList.add("done");
        else if (sn === stage) s.classList.add("active");
    });

    if (isDone || progress <= 0 || isStopped || isError) {
        stopTimer();
    }
}

/* ─── Timer ─── */
function startTimer() {
    startTime = Date.now();
    timerInterval = setInterval(() => {
        const elapsed = Math.floor((Date.now() - startTime) / 1000);
        const m = String(Math.floor(elapsed / 60)).padStart(2, "0");
        const s = String(elapsed % 60).padStart(2, "0");
        $("#nav-timer").textContent = `${m}:${s}`;
    }, 1000);
}
function stopTimer() {
    if (timerInterval) { clearInterval(timerInterval); timerInterval = null; }
}

/* ─── Run ─── */
function setRunningUI(running) {
    const btnRun = $("#btn-run");
    const btnStop = $("#btn-stop");
    if (running) {
        btnRun.style.display = "none";
        btnStop.style.display = "";
        btnStop.disabled = false;
        btnStop.textContent = "停止分析";
    } else {
        btnRun.style.display = "";
        btnStop.style.display = "none";
        btnRun.disabled = false;
        btnRun.textContent = "开始分析";
    }
}

$("#btn-run").addEventListener("click", async () => {
    setRunningUI(true);
    $("#log-area").innerHTML = "";

    try {
        const resp = await fetch("/api/analyze", { method: "POST", headers:{"X-CSRF-Token":getCsrfToken()},credentials: "include" });
        const data = await resp.json();
        if (!resp.ok) {
            alert(data.error || "启动失败");
            setRunningUI(false);
            return;
        }
        startTimer();
    } catch(e) {
        alert("请求失败：" + e.message);
        setRunningUI(false);
    }
});

$("#btn-stop").addEventListener("click", async () => {
    const btn = $("#btn-stop");
    btn.disabled = true;
    btn.textContent = "停止中...";

    try {
        const resp = await fetch("/api/stop", { method: "POST", headers:{"X-CSRF-Token":getCsrfToken()},credentials: "include" });
        if (!resp.ok) {
            const data = await resp.json();
            alert(data.error || "停止失败");
            btn.disabled = false;
            btn.textContent = "停止分析";
        }
    } catch(e) {
        alert("请求失败：" + e.message);
        btn.disabled = false;
        btn.textContent = "停止分析";
    }
});



/* ─── Dashboard ─── */
function loadResults() {
    fetch("/api/results", { headers:{"X-CSRF-Token":getCsrfToken()},credentials: "include" }).then(r => r.json()).then(data => {
        allResults = data.results || {};
        allReports = allResults.all_reports || [];
        renderDashboard(allResults, data.market);
        renderChatSelect(allResults);
        loadDeepStockList();
    }).catch(() => {});
}

function renderDashboard(final, market) {
    const items = final.final_list || [];

    // Stats
    const scores = items.map(i => parseFloat(i.probability_score) || 60);
    const avgScore = scores.length ? scores.reduce((a,b) => a+b, 0) / scores.length : 0;
    drawGauge(avgScore);

    const sectors = new Set(items.map(i => i.sector));
    const highCount = items.filter(i => i.probability_label === "高").length;
    const signals = items.map(i => parseInt(i.signal_strength) || 0).filter(s => s > 0);
    const avgSignal = signals.length ? signals.reduce((a,b) => a+b, 0) / signals.length : 0;

    $("#card-total").textContent = items.length;
    $("#card-sectors").textContent = sectors.size;
    $("#card-high").textContent = highCount;
    $("#card-signal").textContent = Math.round(avgSignal);

    // Market
    if (market) {
        const regime = market.regime || "unknown";
        const trend = market.trend || "";
        const map = {bull:"牛市++",neutral_bull:"偏多+",consolidation:"震荡~",bear:"熊市--",choppy:"混乱?"};
        const clr = {bull:"#66bb6a",neutral_bull:"#9ccc65",consolidation:"#ffa726",bear:"#ef5350",choppy:"#78909c"};
        const el = $("#market-info");
        el.textContent = `[${map[regime]||"?"}] ${trend.slice(0,30)}`;
        el.style.color = clr[regime] || "#78909c";
    }

    // Table
    const tbody = $("#stock-tbody");
    tbody.innerHTML = "";
    const sorted = [...items].sort((a,b) => (b.probability_score||0) - (a.probability_score||0));
    sorted.forEach((it, idx) => {
        const tr = document.createElement("tr");
        tr.dataset.index = idx;
        tr.innerHTML = `
            <td class="col-rank">${idx+1}</td>
            <td>${it.code||""}</td>
            <td>${it.name||""}</td>
            <td>${it.sector||""}</td>
            <td class="col-price">${it.current_price||""}</td>
            <td class="col-entry">${it.entry_price||""}</td>
            <td class="col-stop">${it.stop_loss_price||""}</td>
            <td class="col-target">${it.target_price_3d||""}</td>
            <td class="col-signal">${it.signal_strength||""}</td>
            <td class="col-prob">${it.probability_label||""}</td>
            <td>${(it.logic_analysis||it.sector_logic||it.reason||"").slice(0,80)}</td>
            <td>${(it.technical_analysis||it.watch_3d||"").slice(0,100)}</td>
        `;
        tr.addEventListener("dblclick", () => {
            selectedStockIndex = idx;
            switchTab("chat");
            selectChatStock(idx);
        });
        tbody.appendChild(tr);
    });

    const top1 = sorted[0];
    if (top1) {
        $("#dash-status").textContent = `Top1: ${top1.code} ${top1.name} | ${top1.probability_label}(${top1.probability_score}分) | 当前:${top1.current_price} 买入:${top1.entry_price} 止损:${top1.stop_loss_price} 目标:${top1.target_price_3d}`;
    }
}

/* ─── Gauge ─── */
function drawGauge(v) {
    v = Math.max(0, Math.min(100, v));
    const canvas = $("#gauge-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.width, H = canvas.height;
    const cx = W / 2, cy = H - 15, r = 70;
    ctx.clearRect(0, 0, W, H);

    ctx.beginPath();
    ctx.arc(cx, cy, r, Math.PI, 0, false);
    ctx.strokeStyle = "#2a2e36";
    ctx.lineWidth = 16;
    ctx.stroke();

    const extent = Math.PI * (v / 100);
    let color = "#b71c1c";
    if (v >= 75) color = "#66bb6a";
    else if (v >= 50) color = "#ffa726";
    else if (v >= 25) color = "#ef5350";

    if (extent > 0) {
        ctx.beginPath();
        ctx.arc(cx, cy, r, Math.PI, Math.PI + extent, false);
        ctx.strokeStyle = color;
        ctx.lineWidth = 16;
        ctx.stroke();
    }

    ctx.fillStyle = color;
    ctx.font = "bold 26px Consolas";
    ctx.textAlign = "center";
    ctx.fillText(Math.round(v), cx, cy - 18);

    const label = v >= 75 ? "高" : v >= 50 ? "中" : "低";
    ctx.fillStyle = "#78909c";
    ctx.font = "12px Microsoft YaHei UI";
    ctx.fillText(`综合置信度: ${label}`, cx, cy + 8);
    $("#gauge-label").textContent = `综合置信度: ${label}`;
}

/* ─── Chat ─── */
function renderChatSelect(final) {
    const sel = $("#chat-stock-select");
    sel.innerHTML = "";
    const items = final.final_list || [];
    items.forEach((it, idx) => {
        const opt = document.createElement("option");
        opt.value = idx;
        opt.textContent = `#${idx+1} ${it.code} ${it.name} | ${it.sector} | 综合:${it.probability_score} | 信号:${it.signal_strength} | 价:${it.current_price}`;
        sel.appendChild(opt);
    });
    sel.addEventListener("change", () => selectChatStock(parseInt(sel.value)));
    if (items.length) selectChatStock(0);
}

function selectChatStock(idx) {
    const items = allResults.final_list || [];
    if (idx < 0 || idx >= items.length) return;
    selectedStockIndex = idx;

    const item = items[idx];
    // find matching report
    let report = {...item};
    for (const r of allReports) {
        if (String(r.code).trim() === String(item.code).trim()) {
            report = {...r, ...Object.fromEntries(Object.entries(item).filter(([k,v]) => v !== null && v !== "" && v !== undefined && v !== 0))};
            break;
        }
    }

    renderStockInfo(report);
    chatHistory = [];
    clearChatMessages();
    appendChatMsg("system", `已切换到 ${report.code} ${report.name}，可开始提问。`);
}

function renderStockInfo(r) {
    const el = $("#chat-stock-info");
    let html = `<div class="info-header">${r.code} ${r.name} | ${r.sector}</div>`;
    html += `<div class="info-price">综合评分：${r.probability_score||""}  技术信号：${r.signal_strength||""}  趋势阶段：${r.trend_stage||""}</div><br>`;

    for (const [label, key] of [
        ["新闻/板块逻辑","logic_analysis"],["综合理由","reason"],
        ["技术面解释","technical_analysis"],["未来3天观察","watch_3d"]
    ]) {
        if (r[key]) html += `<span class="info-label">${label}：</span>${r[key]}<br>`;
    }

    html += `<br><span class="info-label">关键价位：</span><br>`;
    html += `当前价：<span class="info-price">${r.current_price||"-"}</span><br>`;
    html += `买入观察：<span class="info-price">${r.entry_price||"-"}</span><br>`;
    html += `止损价：<span class="info-resist">${r.stop_loss_price||"-"}</span><br>`;
    html += `3日目标：<span class="info-price">${r.target_price_3d||"-"}</span><br>`;

    const supports = r.key_support || r.key_support_levels;
    if (supports && supports.length) {
        html += `<span class="info-support">支撑位：</span>`;
        supports.forEach(s => {
            const lv = typeof s === "object" ? s.level : s;
            html += `<span class="info-support">${lv}</span> `;
        });
        html += "<br>";
    }
    const resists = r.key_resistance || r.key_resistance_levels;
    if (resists && resists.length) {
        html += `<span class="info-resist">压力位：</span>`;
        resists.forEach(s => {
            const lv = typeof s === "object" ? s.level : s;
            html += `<span class="info-resist">${lv}</span> `;
        });
        html += "<br>";
    }

    for (const [label, key] of [
        ["均线","ma_analysis"],["MACD","macd_analysis"],["RSI","rsi_analysis"],
        ["KDJ","kdj_analysis"],["布林带","boll_analysis"],["成交量","volume_analysis"]
    ]) {
        if (r[key]) html += `<span class="info-label">${label}：</span>${r[key]}<br>`;
    }

    const risk = r.risk_warning || (Array.isArray(r.invalidation) ? r.invalidation[0] : r.invalidation);
    if (risk) html += `<br><span class="info-label">风险提示：</span><span class="info-resist">${risk}</span>`;

    el.innerHTML = html;
}

function clearChatMessages() {
    $("#chat-messages").innerHTML = "";
}

function appendChatMsg(role, text) {
    const el = $("#chat-messages");
    const div = document.createElement("div");
    div.className = `msg msg-${role}`;
    if (role !== "system") {
        const roleDiv = document.createElement("div");
        roleDiv.className = "msg-role";
        roleDiv.textContent = role === "user" ? "你" : "AI";
        div.appendChild(roleDiv);
    }
    const content = document.createElement("div");
    content.textContent = text;
    div.appendChild(content);
    el.appendChild(div);
    el.scrollTop = el.scrollHeight;
}

async function sendChat(question) {
    if (!question || selectedStockIndex < 0) return;
    const items = allResults.final_list || [];
    if (selectedStockIndex >= items.length) return;

    appendChatMsg("user", question);
    chatHistory.push({ role: "user", content: question });

    // find report
    let report = {...items[selectedStockIndex]};
    for (const r of allReports) {
        if (String(r.code).trim() === String(report.code).trim()) {
            report = {...r, ...Object.fromEntries(Object.entries(report).filter(([k,v]) => v !== null && v !== "" && v !== undefined && v !== 0))};
            break;
        }
    }

    $("#btn-send").disabled = true;
    try {
        const resp = await fetch("/api/chat", {
            method: "POST",
            credentials: "include",
            headers: {'X-CSRF-Token': getCsrfToken(),  "Content-Type": "application/json" },
            body: JSON.stringify({ stock: report, history: chatHistory, question }),
        });
        const data = await resp.json();
        if (!resp.ok) {
            appendChatMsg("system", `错误：${data.error}`);
        } else {
            appendChatMsg("assistant", data.answer);
            chatHistory.push({ role: "assistant", content: data.answer });
        }
    } catch(e) {
        appendChatMsg("system", `请求失败：${e.message}`);
    }
    $("#btn-send").disabled = false;
}

$("#btn-send").addEventListener("click", () => {
    const input = $("#chat-input");
    const q = input.value.trim();
    if (q) { sendChat(q); input.value = ""; }
});
$("#chat-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        $("#btn-send").click();
    }
});
$("#btn-clear-chat").addEventListener("click", () => {
    chatHistory = [];
    clearChatMessages();
    appendChatMsg("system", "对话已清空。");
});

$$(".btn-quick").forEach(btn => {
    btn.addEventListener("click", () => {
        const q = btn.dataset.q;
        $("#chat-input").value = q;
        sendChat(q);
        $("#chat-input").value = "";
    });
});

/* ─── Stock detail modal ─── */
$("#btn-close-detail").addEventListener("click", () => { $("#modal-stock-detail").style.display = "none"; });
$("#btn-detail-chat").addEventListener("click", () => {
    $("#modal-stock-detail").style.display = "none";
    switchTab("chat");
});

/* ─── Init ─── */
syncTabFromHash();
window.addEventListener("hashchange", syncTabFromHash);
connectWS();
loadResults();
fetch("/api/status", { headers:{"X-CSRF-Token":getCsrfToken()},credentials: "include" }).then(r => r.json()).then(s => {
    if (s.running) {
        setRunningUI(true);
        startTimer();
    }
}).catch(() => {});


/* ─── Deep Analysis ─── */
let deepWs = null;
let deepRunning = false;
const deepStages = ["数据抓取","评分计算","同行对比","合并同行","博弈分析","合并博弈","渲染HTML","验证结果"];

function connectDeepWS() {
    if (deepWs && deepWs.readyState <= 1) return;
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
        deepWs = new WebSocket(`${protocol}//${location.host}/ws/deep-logs`);
    deepWs.onopen = () => { deepWs.send("ping"); };
    deepWs.onmessage = (e) => {
        try { handleDeepWSMessage(JSON.parse(e.data)); } catch(err) {}
    };
    deepWs.onclose = () => { setTimeout(connectDeepWS, 3000); };
    deepWs.onerror = () => { if(deepWs) deepWs.close(); };
}

function handleDeepWSMessage(msg) {
    if (msg.type === "log") {
        appendDeepLog(msg.detail);
    } else if (msg.type === "progress") {
        updateDeepStages(msg.stage, msg.progress, msg.status);
    } else if (msg.type === "done") {
        deepRunning = false;
        setDeepRunningUI(false);
        renderDeepResult(msg.result);
    } else if (msg.type === "error") {
        appendDeepLog("错误：" + msg.detail, "error");
        deepRunning = false;
        setDeepRunningUI(false);
    } else if (msg.type === "cancelled") {
        appendDeepLog("已停止：" + msg.detail, "warn");
        deepRunning = false;
        setDeepRunningUI(false);
    }
}

function appendDeepLog(text, type) {
    const area = $("#deep-log-area");
    if (!area) return;
    // During analysis, hide log and show clean progress
    if (deepRunning && type !== "error") {
        area.style.display = "none";
        const stxt = $("#deep-status-text");
        if (stxt) stxt.textContent = text;
        return;
    }
    const line = document.createElement("div");
    line.className = "log-line " + (type || "info");
    line.textContent = text;
    area.appendChild(line);
    area.scrollTop = area.scrollHeight;
}

function updateDeepStages(currentStage, progress, statusText) {
    const fill = $("#deep-progress-fill");
    const stxt = $("#deep-status-text");
    if (fill) fill.style.width = (progress || 0) + "%";
    if (stxt) stxt.textContent = statusText || "运行中...";

    // Update stage indicators
    $$("#deep-stages .stage").forEach(s => {
        const name = s.dataset.stage;
        s.classList.remove("active", "done");
        const idx = deepStages.indexOf(name);
        const curIdx = deepStages.indexOf(currentStage);
        if ((progress || 0) >= 100 || idx < curIdx) {
            s.classList.add("done");
        } else if (idx === curIdx) {
            s.classList.add("active");
        }
    });
}

function setDeepRunningUI(running) {
    const btnRun = $("#btn-deep-run");
    const btnStop = $("#btn-deep-stop");
    const stxt = $("#deep-status-text");
    const logArea = $("#deep-log-area");
    if (running) {
        if (btnRun) btnRun.style.display = "none";
        if (btnStop) btnStop.style.display = "";
        deepRunning = true;
        if (stxt) { stxt.textContent = "分析中..."; stxt.className = "running"; }
        if (logArea) logArea.style.display = "none";
    } else {
        if (btnRun) btnRun.style.display = "";
        if (btnStop) btnStop.style.display = "none";
        deepRunning = false;
        if (stxt) stxt.className = "";
    }
}

async function startDeepAnalysis() {
    const selectEl = $("#deep-stock-select");
    const inputEl = $("#deep-code");
    let code = "";
    if (selectEl && selectEl.value) {
        code = selectEl.value;
    } else if (inputEl) {
        code = inputEl.value;
    }
    const quick = false;
    if (!code.trim()) { alert("请选择或输入股票代码"); return; }

    // Reset iframe, show log, reset stages
    const iframeWrap = $("#deep-iframe-wrap");
    const iframe = $("#deep-iframe");
    const logArea = $("#deep-log-area");
    if (iframeWrap) iframeWrap.style.display = "none";
    if (iframe) iframe.src = "";
    if (logArea) { logArea.style.display = "none"; logArea.innerHTML = ""; }
    $$("#deep-stages .stage").forEach(s => { s.classList.remove("active","done"); });

    connectDeepWS();
    setDeepRunningUI(true);

    try {
        const resp = await fetch("/api/deep-analysis/start", {
            method: "POST",
            credentials: "include",
            headers: {'X-CSRF-Token': getCsrfToken(),  "Content-Type": "application/json" },
            body: JSON.stringify({ code: code.trim(), quick }),
        });
        const data = await resp.json();
        if (!resp.ok) {
            appendDeepLog("启动失败：" + (data.error || "未知错误"), "error");
            setDeepRunningUI(false);
        } else {
            appendDeepLog(data.message || "已启动");
        }
    } catch(e) {
        appendDeepLog("请求失败：" + e.message, "error");
        setDeepRunningUI(false);
    }
}

async function stopDeepAnalysis() {
    try {
        await fetch("/api/deep-analysis/stop", { method: "POST", headers:{"X-CSRF-Token":getCsrfToken()},credentials: "include" });
    } catch(e) {}
}

function renderDeepResult(r) {
    if (!r) return;
    deepResult = r;
    const iframeWrap = $("#deep-iframe-wrap");
    const iframe = $("#deep-iframe");
    const logArea = $("#deep-log-area");
    if (r.html_exists && r.html_path) {
        const fname = r.html_path.split(/[/\\]/).pop();
        if (iframe) iframe.src = "/api/deep-analysis/view/" + encodeURIComponent(fname);
        if (iframeWrap) iframeWrap.style.display = "flex";
        if (logArea) logArea.style.display = "none";
        const exportBtns = $("#deep-export-btns");
        if (exportBtns) exportBtns.style.display = "";
        const dlBtn = $("#btn-deep-download");
        if (dlBtn) {
            dlBtn.onclick = () => {
                const a = document.createElement("a");
                a.href = "/api/deep-analysis/download/" + encodeURIComponent(fname);
                a.download = fname;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
            };
        }
    }
}

function exportDeepPdf() {
    const iframe = $("#deep-iframe");
    if (!iframe || !iframe.contentWindow) {
        alert("请先完成分析并查看报告");
        return;
    }
    try {
        if (deepResult && iframe.contentDocument) {
            const name = deepResult.title || "";
            const code = deepResult.code || "";
            const path = deepResult.html_path || "";
            const dateMatch = path.match(/(\d{8})\.html/);
            const date = dateMatch ? dateMatch[1] : new Date().toISOString().slice(0,10).replace(/-/g,"");
            const pdfName = [name, code, date].filter(Boolean).join("_");
            if (pdfName) iframe.contentDocument.title = pdfName;
        }
        iframe.contentWindow.print();
    } catch(e) {
        alert("PDF 导出失败，请确保报告已加载完成");
    }
}

// Event listeners
document.addEventListener("DOMContentLoaded", () => {
    const btnRun = $("#btn-deep-run");
    const btnStop = $("#btn-deep-stop");
    if (btnRun) btnRun.addEventListener("click", startDeepAnalysis);
    if (btnStop) btnStop.addEventListener("click", stopDeepAnalysis);
    const btnPdf = $("#btn-deep-pdf");
    if (btnPdf) btnPdf.addEventListener("click", exportDeepPdf);

    // Load stock list from batch results
    loadDeepStockList();

    // Sync select <-> input
    const selectEl = $("#deep-stock-select");
    const inputEl = $("#deep-code");
    if (selectEl) selectEl.addEventListener("change", () => {
        if (selectEl.value && inputEl) inputEl.value = selectEl.value;
    });
    if (inputEl) inputEl.addEventListener("input", () => {
        if (inputEl.value && selectEl) selectEl.value = "";
    });

    // Auto-fill from URL params
    const params = new URLSearchParams(location.search);
    const deepCode = params.get("deep_code");
    if (deepCode) {
        if (inputEl) inputEl.value = deepCode;
        switchTab("deep");
    }
});

function loadDeepStockList() {
    fetch("/api/results", { headers:{"X-CSRF-Token":getCsrfToken()},credentials: "include" }).then(r => r.json()).then(data => {
        const select = $("#deep-stock-select");
        if (!select) return;
        const reports = data.results?.all_reports || [];
        const finalList = data.results?.final_list || [];
        // Prefer final_list, fall back to all_reports
        const stocks = finalList.length ? finalList : reports;
        if (!stocks.length) return;
        // Clear and rebuild
        select.innerHTML = '<option value="">-- 从分析结果选择 --</option>';
        stocks.forEach(s => {
            const code = s.code || "";
            const name = s.name || "";
            const signal = s.signal_strength || "";
            if (!code) return;
            const opt = document.createElement("option");
            opt.value = code;
            opt.textContent = code + " " + name + (signal ? " (" + signal + ")" : "");
            select.appendChild(opt);
        });
    }).catch(() => {});
}

function switchTab(name) {
    $$(".nav-tab").forEach(t => t.classList.remove("active"));
    $$(".tab-panel").forEach(p => p.classList.remove("active"));
    const tab = $(`.nav-tab[data-tab="${name}"]`);
    if (tab) tab.classList.add("active");
    const panel = $(`#tab-${name}`);
    if (panel) panel.classList.add("active");
    if (name === "deep") loadDeepStockList();
}

})();
