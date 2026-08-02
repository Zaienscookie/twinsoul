// Twinsoul v3 WebUI
const bridge = window.AstrBotPluginPage;
await bridge.ready();
const $ = id => document.getElementById(id);

function esc(t) { const d = document.createElement("div"); d.textContent = t; return d.innerHTML; }
function showMsg(el, text, type = "info") {
    el.textContent = text; el.className = `msg show ${type}`;
    setTimeout(() => el.className = "msg", 3500);
}
function timeStr(ts) {
    const d = new Date(ts * 1000);
    return `${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}:${String(d.getSeconds()).padStart(2,"0")}`;
}
function ctxTimeStr(iso) { if (!iso) return ""; const d = new Date(iso); return `${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`; }

// ─── 状态 ────────────────────────────────────────────────

async function fetchStatus() {
    try {
        const s = await bridge.apiGet("status");
        $("sb-running").textContent = s.running ? "✅ 运行中" : "⏸ 已停止";
        $("sb-running").style.color = s.running ? "#22c55e" : "#f59e0b";
        $("sb-bots").textContent = `🤖 Bot: ${s.found_bots.join(", ") || "无"}`;
        $("sb-history").textContent = `📝 历史: ${s.history_count}条`;
        $("sb-context").textContent = `🧠 记忆: 扎${s.context_zaiens} 威${s.context_william}`;
        $("sb-interject").textContent = `💬 插话: ${s.interject_chance}%`;
        $("sb-greeting").textContent = `🌅 问候: ${s.greeting_enabled ? s.greeting_chance + "%" : "关"}`;
        $("sb-sleep").textContent = `🌙 睡眠: ${s.sleeping ? "休息中" : "清醒"}·熬夜${s.sleep_talk_chance ?? 15}%`;

        // 填充表单
        $("cfg-group_id").value = s.group_id || "";
        $("cfg-zaiens_qq").value = s.zaiens_qq || "";
        $("cfg-william_qq").value = s.william_qq || "";
        $("cfg-zaiens_persona").value = s.zaiens_persona || "zaiens";
        $("cfg-william_persona").value = s.william_persona || "william";
        $("cfg-interval").value = s.interval || 90;
        $("cfg-context_rounds").value = s.context_rounds || 5;
        $("cfg-william_chance").value = s.william_chance || 55;
        $("cfg-zaiens_chance").value = s.zaiens_chance || 45;
        $("cfg-timed").value = s.timed_chat ? "true" : "false";
        $("cfg-interject_chance").value = s.interject_chance || 30;
        $("cfg-greeting_enabled").value = s.greeting_enabled ? "true" : "false";
        $("cfg-greeting_chance").value = s.greeting_chance || 35;
        $("cfg-greeting_check_interval").value = s.greeting_check_interval || 30;
        $("cfg-morning_boost").value = s.morning_boost || 25;
        $("cfg-noon_boost").value = s.noon_boost || 20;
        $("cfg-evening_boost").value = s.evening_boost || 20;
        $("cfg-night_boost").value = s.night_boost || 15;
        $("cfg-reply_delay_min").value = s.reply_delay_min ?? 0.5;
        $("cfg-reply_delay_max").value = s.reply_delay_max ?? 2.0;
        $("cfg-sleep_start_hour").value = s.sleep_start_hour ?? 23;
        $("cfg-sleep_end_hour").value = s.sleep_end_hour ?? 7;
        $("cfg-sleep_talk_chance").value = s.sleep_talk_chance ?? 15;
        $("ctx-rounds-display").textContent = s.context_rounds || 5;
    } catch (e) { $("sb-running").textContent = "❌ 连接失败"; console.error(e); }
}

// ─── 历史 ────────────────────────────────────────────────

async function fetchHistory(filter = "all") {
    try {
        const data = await bridge.apiGet("history", { limit: 200, role: filter });
        $("history-count").textContent = data.length;
        if (!data || data.length === 0) { $("history-list").innerHTML = '<div class="empty">暂无记录</div>'; return; }
        const reversed = [...data].reverse();
        $("history-list").innerHTML = reversed.map(item => {
            const name = item.role === "zaiens" ? "扎恩斯" : "威廉";
            const type = item.type || "normal";
            const typeLabel = type === "greeting" ? "🌅" : type === "interject" ? "💬" : "";
            return `<div class="history-item">
                <span class="role ${item.role}">${name}</span>
                <span class="text">${esc(item.text)}</span>
                <span class="time">${typeLabel} ${timeStr(item.time)}</span>
                <button class="btn-del" data-del="history" data-index="${item.index}" title="删除这条">✕</button>
            </div>`;
        }).join("");
    } catch (e) { console.error(e); }
}

// ─── 上下文 ──────────────────────────────────────────────

async function fetchContext() {
    try {
        const data = await bridge.apiGet("context");
        const zaiens = data.zaiens || []; const william = data.william || [];
        $("ctx-z-count").textContent = zaiens.length; $("ctx-w-count").textContent = william.length;
        const render = (arr, containerId) => {
            const el = $(containerId);
            if (arr.length === 0) { el.innerHTML = '<div class="empty">无记忆</div>'; return; }
            el.innerHTML = arr.map(item => {
                const name = item.role === "zaiens" ? "扎恩斯" : "威廉";
                return `<div class="context-item ${item.role}"><strong>${name}</strong>：${esc(item.text)}<div class="ctx-time">${ctxTimeStr(item.time)}</div><button class="btn-del" data-del="context" data-role="${item.role}" data-index="${item.index}" title="删除这条">✕</button></div>`;
            }).join("");
        };
        render(zaiens, "ctx-zaiens"); render(william, "ctx-william");
        $("memory-raw").textContent = JSON.stringify(data, null, 2);
    } catch (e) { console.error(e); }
}

// ─── Tab ─────────────────────────────────────────────────

document.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
        document.querySelectorAll(".tab-content").forEach(tc => tc.classList.remove("active"));
        tab.classList.add("active");
        const target = document.getElementById(`tab-${tab.dataset.tab}`);
        if (target) target.classList.add("active");
        if (tab.dataset.tab === "context" || tab.dataset.tab === "memory-detail") fetchContext();
        if (tab.dataset.tab === "history") {
            const a = document.querySelector("#tab-history .filter-btn.active");
            fetchHistory(a ? a.dataset.filter : "all");
        }
    });
});

// ─── 事件 ─────────────────────────────────────────────────

$("btn-start").addEventListener("click", async () => {
    try { const r = await bridge.apiPost("start"); showMsg($("control-msg"), r.message, "success"); fetchStatus(); }
    catch (e) { showMsg($("control-msg"), e.message, "error"); }
});
$("btn-stop").addEventListener("click", async () => {
    try { const r = await bridge.apiPost("stop"); showMsg($("control-msg"), r.message, "success"); fetchStatus(); }
    catch (e) { showMsg($("control-msg"), e.message, "error"); }
});
$("btn-chat").addEventListener("click", async () => {
    try { await bridge.apiPost("chat", {}); showMsg($("control-msg"), "对话已触发", "success");
        setTimeout(fetchHistory, 4000); setTimeout(fetchContext, 5000); setTimeout(fetchStatus, 3000); }
    catch (e) { showMsg($("control-msg"), e.message, "error"); }
});
$("btn-greet").addEventListener("click", async () => {
    try { await bridge.apiPost("greet"); showMsg($("control-msg"), "问候已触发", "success");
        setTimeout(fetchHistory, 4000); setTimeout(fetchContext, 5000); }
    catch (e) { showMsg($("control-msg"), e.message, "error"); }
});
$("btn-chat-seed").addEventListener("click", async () => {
    const seed = $("chat-seed").value.trim();
    if (!seed) { showMsg($("control-msg"), "请输入话题", "info"); return; }
    try { await bridge.apiPost("chat", { seed }); showMsg($("control-msg"), `「${seed}」已触发`, "success");
        $("chat-seed").value = ""; setTimeout(fetchHistory, 4000); setTimeout(fetchContext, 5000); }
    catch (e) { showMsg($("control-msg"), e.message, "error"); }
});

$("btn-save-config").addEventListener("click", async () => {
    const cfg = {
        group_id: $("cfg-group_id").value,
        zaiens_qq: $("cfg-zaiens_qq").value, william_qq: $("cfg-william_qq").value,
        zaiens_persona: $("cfg-zaiens_persona").value, william_persona: $("cfg-william_persona").value,
        chat_interval_minutes: parseInt($("cfg-interval").value) || 90,
        context_rounds: parseInt($("cfg-context_rounds").value) || 5,
        william_initiate_chance: parseInt($("cfg-william_chance").value) || 55,
        zaiens_initiate_chance: parseInt($("cfg-zaiens_chance").value) || 45,
        enable_timed_chat: $("cfg-timed").value === "true",
        interject_chance: parseInt($("cfg-interject_chance").value) || 30,
        greeting_enabled: $("cfg-greeting_enabled").value === "true",
        greeting_chance: parseInt($("cfg-greeting_chance").value) || 35,
        greeting_check_interval: parseInt($("cfg-greeting_check_interval").value) || 30,
        morning_boost: parseInt($("cfg-morning_boost").value) || 25,
        noon_boost: parseInt($("cfg-noon_boost").value) || 20,
        evening_boost: parseInt($("cfg-evening_boost").value) || 20,
        night_boost: parseInt($("cfg-night_boost").value) || 15,
        reply_delay_min: (t => Number.isNaN(t) ? 0.5 : t)(parseFloat($("cfg-reply_delay_min").value)),
        reply_delay_max: (t => Number.isNaN(t) ? 2.0 : t)(parseFloat($("cfg-reply_delay_max").value)),
        sleep_start_hour: (t => Number.isNaN(t) ? 23 : t)(parseInt($("cfg-sleep_start_hour").value)),
        sleep_end_hour: (t => Number.isNaN(t) ? 7 : t)(parseInt($("cfg-sleep_end_hour").value)),
        sleep_talk_chance: (t => Number.isNaN(t) ? 15 : t)(parseInt($("cfg-sleep_talk_chance").value)),
    };
    try { await bridge.apiPost("config/save", cfg); showMsg($("config-msg"), "配置已保存", "success"); fetchStatus(); }
    catch (e) { showMsg($("config-msg"), e.message, "error"); }
});

$("btn-refresh-history").addEventListener("click", () => {
    const a = document.querySelector("#tab-history .filter-btn.active");
    fetchHistory(a ? a.dataset.filter : "all");
});
$("btn-clear-history").addEventListener("click", async () => {
    if (!confirm("确定清空历史？")) return;
    try { await bridge.apiPost("history/clear"); showMsg($("control-msg"), "已清空", "success"); fetchHistory(); }
    catch (e) { showMsg($("control-msg"), e.message, "error"); }
});
$("btn-refresh-context").addEventListener("click", fetchContext);
$("btn-refresh-memory").addEventListener("click", fetchContext);
$("btn-clear-context").addEventListener("click", async () => {
    if (!confirm("清空记忆？双子会忘记之前聊过什么。")) return;
    try { await bridge.apiPost("context/clear"); showMsg($("control-msg"), "记忆已清空", "success"); fetchContext(); }
    catch (e) { showMsg($("control-msg"), e.message, "error"); }
});
$("btn-clear-memory").addEventListener("click", async () => {
    if (!confirm("清空记忆？双子会忘记之前聊过什么。")) return;
    try { await bridge.apiPost("context/clear"); showMsg($("control-msg"), "记忆已清空", "success"); fetchContext(); }
    catch (e) { showMsg($("control-msg"), e.message, "error"); }
});

// 单条删除（事件委托）
document.addEventListener("click", async (e) => {
    const btn = e.target.closest(".btn-del");
    if (!btn) return;
    const idx = parseInt(btn.dataset.index);
    if (btn.dataset.del === "history") {
        if (!confirm("删除这条历史？")) return;
        try { await bridge.apiPost("history/remove", { index: idx }); showMsg($("control-msg"), "已删除", "success"); fetchHistory(); }
        catch (err) { showMsg($("control-msg"), err.message || "删除失败", "error"); }
    } else if (btn.dataset.del === "context") {
        if (!confirm("删除这条记忆？")) return;
        try { await bridge.apiPost("context/remove", { role: btn.dataset.role, index: idx }); showMsg($("control-msg"), "已删除", "success"); fetchContext(); }
        catch (err) { showMsg($("control-msg"), err.message || "删除失败", "error"); }
    }
});

document.querySelectorAll("#tab-history .filter-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll("#tab-history .filter-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active"); fetchHistory(btn.dataset.filter);
    });
});

// ─── 初始化 ──────────────────────────────────────────────

await fetchStatus(); await fetchHistory(); await fetchContext();
setInterval(fetchStatus, 20000);
setInterval(() => {
    if (document.getElementById("tab-history").classList.contains("active")) {
        const a = document.querySelector("#tab-history .filter-btn.active");
        fetchHistory(a ? a.dataset.filter : "all");
    }
}, 12000);
setInterval(() => {
    if (document.getElementById("tab-context").classList.contains("active") ||
        document.getElementById("tab-memory-detail").classList.contains("active")) fetchContext();
}, 15000);