/* auto_dev_crew/static/mission_control.js
 * Drop-in Mission Control UX, Beginner Onboarding, Manual, Safety Self-Quiz & MCP Hub.
 * Security: Strict HTML escaping / textContent only; preserves all test_gui_*.py contracts.
 */
(() => {
  "use strict";

  const OWNER_REPO_RE = /^[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}\/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}$/;
  const ENV_KEY_NAME_RE = /^[A-Z][A-Z0-9_]{2,63}$/;
  const RESERVED_ENV = new Set([
    "PATH", "PYTHONPATH", "PYTHONHOME", "NODE_OPTIONS", "LD_PRELOAD", "LD_LIBRARY_PATH", "SOMETHING_ELSE"
  ]);

  function esc(val) {
    return String(val ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    }[ch]));
  }

  function storageGet(key, fallback) {
    try {
      const v = window.localStorage.getItem(key);
      return v !== null ? v : fallback;
    } catch (_) {
      return fallback;
    }
  }

  function storageSet(key, val) {
    try {
      window.localStorage.setItem(key, val);
    } catch (_) {}
  }

  // 1. Simple vs Pro Mode Controller
  // ผู้ใช้ครั้งแรก (ยังไม่เคยเลือกโหมด) = ง่าย · การเลือกของผู้ใช้จะถูกจำไว้ (adc_ui_mode)
  // applyUiMode แสดงผลอย่างเดียว ไม่เขียน storage; setUiComplexityMode = การกดของผู้ใช้
  function applyUiMode(mode) {
    const clean = mode === "pro" ? "pro" : "simple";
    document.documentElement.setAttribute("data-ui-mode", clean);
    document.querySelectorAll("[data-mode-btn]").forEach((btn) => {
      btn.setAttribute("aria-pressed", String(btn.dataset.modeBtn === clean));
      btn.classList.toggle("active", btn.dataset.modeBtn === clean);
    });
  }

  function setUiComplexityMode(mode) {
    const clean = mode === "pro" ? "pro" : "simple";
    applyUiMode(clean);
    storageSet("adc_ui_mode", clean);
  }

  // 2. Category 8 Rubric Safety Self-Quiz Gate (Protects Level 3 & merge-all)
  const QUIZ_ITEMS = [
    {
      id: "q1",
      ref: "Rubric 8.1",
      q: "Which Git operation is Auto Dev Crew strictly forbidden from ever running?",
      opts: [
        "Pushing branch self/* and opening a PR",
        "Force-pushing, pushing directly to main, or committing config.yaml / .env",
        "Posting diagnostic comments on ai-task issues"
      ],
      ans: 1
    },
    {
      id: "q2",
      ref: "Rubric 8.2",
      q: "What must happen if a test fails—or if the existing test itself looks wrong?",
      opts: [
        "Delete or skip the failing test",
        "Modify the expected assertion value so CI turns green",
        "Fix production code; if the test looks wrong, stop and ask the owner"
      ],
      ans: 2
    },
    {
      id: "q3",
      ref: "Rubric 5.1",
      q: "How does Auto Dev Crew prevent an AI from grading its own code?",
      opts: [
        "pick_judge_pool excludes the Coder's engine and requires a cross-family Judge >= 0.75",
        "Coder grades its own diff without tests",
        "Judge is optional on protected files"
      ],
      ans: 0
    },
    {
      id: "q4",
      ref: "Rubric 6.4",
      q: "If a PR passes CI and Judge (0.92) but touches runner.py or .github/workflows/, what happens?",
      opts: [
        "It auto-merges immediately",
        "Protected paths never auto-merge—it pauses for human approval",
        "It overwrites main directly"
      ],
      ans: 1
    },
    {
      id: "q5",
      ref: "Safe Rollback",
      q: "What is the safest way to undo an autonomous PR merge?",
      opts: [
        "git push --force origin main",
        "Use 1-Click Safe Revert PR to open a clean git revert branch",
        "Delete the state directory"
      ],
      ans: 1
    }
  ];

  function hasPassedSafetyQuiz() {
    return storageGet("adc_safety_quiz_passed", "false") === "true";
  }

  function guardHighAutonomySelection(selectEl, fallbackVal, openQuizCallback) {
    if (!selectEl) return true;
    const isHigh = selectEl.value === "merge-all" || selectEl.value === "3";
    if (isHigh && !hasPassedSafetyQuiz()) {
      selectEl.value = fallbackVal;
      if (window.confirm("โหมดอัตโนมัติระดับสูงสุด (merge-all / ระดับ 3) ต้องผ่านแบบทดสอบความปลอดภัย 5 ข้อในหน้าคู่มือก่อน ต้องการเปิดแบบทดสอบตอนนี้หรือไม่?")) {
        if (typeof openQuizCallback === "function") openQuizCallback();
      }
      return false;
    }
    return true;
  }

  // 3. Client-Side Input Validators (Matching Backend Security Guards)
  function validateClientRepo(repoStr) {
    return OWNER_REPO_RE.test(String(repoStr || "").trim());
  }

  function validateClientEnvKey(varName, secretVal) {
    const clean = String(varName || "").trim();
    if (!ENV_KEY_NAME_RE.test(clean) || RESERVED_ENV.has(clean)) return false;
    if (!clean.includes("KEY") && !clean.includes("TOKEN")) return false;
    if (!secretVal || /[\r\n\0]/.test(secretVal)) return false;
    return true;
  }

  // 4. Mission Control card: view mode, Graceful Drain, Context Slicer preview.
  // Builds DOM with createElement and textContent only, so server output is shown as plain text.
  function apiToken() {
    try {
      return typeof TOKEN !== "undefined" ? String(TOKEN) : "";
    } catch (_) {
      return "";
    }
  }

  async function mcRequest(method, path, body) {
    const opts = {method, headers: {"X-Token": apiToken()}};
    if (method === "POST") {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body || {});
    }
    const r = await fetch(path, opts);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  }

  function el(tag, attrs, text) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, val]) => {
      if (key === "class") node.className = val;
      else node.setAttribute(key, val);
    });
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function button(label, attrs) {
    return el("button", Object.assign({type: "button", class: "btn"}, attrs || {}), label);
  }

  function setOutput(node, message, isError) {
    node.textContent = "";
    node.appendChild(el("p", {class: isError ? "muted error" : "muted"}, message));
  }

  function buildDrainSection() {
    const out = el("div", {class: "adc-out", "aria-live": "polite"});
    const row = el("div", {class: "row"});
    const requestBtn = button("⏸ ขอ Graceful Drain", {id: "mcDrainStart"});
    const clearBtn = button("▶ ยกเลิก Drain", {id: "mcDrainClear"});
    const statusBtn = button("ตรวจสถานะ Drain", {id: "mcDrainStatus"});
    row.append(requestBtn, clearBtn, statusBtn);

    requestBtn.addEventListener("click", async () => {
      const ok = window.confirm(
        "Graceful Drain: ระบบจะรอให้ช่องที่กำลังทำงานเสร็จ แล้วหยุดโดยไม่รับงานใหม่ " +
        "และปิดโหมดอัตโนมัติด้วย ต้องการดำเนินการหรือไม่?"
      );
      if (!ok) return;
      setOutput(out, "กำลังส่งคำขอ…");
      try {
        const data = await mcRequest("POST", "/api/graceful-drain", {});
        setOutput(out, data.message || "เปิดโหมด Graceful Drain แล้ว");
      } catch (err) {
        setOutput(out, `ส่งคำขอไม่สำเร็จ: ${err.message}`, true);
      }
    });

    clearBtn.addEventListener("click", async () => {
      setOutput(out, "กำลังยกเลิก…");
      try {
        const data = await mcRequest("POST", "/api/graceful-drain", {clear: true});
        setOutput(out, data.message || "ยกเลิกโหมด Graceful Drain แล้ว");
      } catch (err) {
        setOutput(out, `ยกเลิกไม่สำเร็จ: ${err.message}`, true);
      }
    });

    statusBtn.addEventListener("click", async () => {
      setOutput(out, "กำลังอ่านสถานะ… (อาจใช้เวลาครู่หนึ่ง)");
      try {
        const data = await mcRequest("GET", "/api/status");
        const drain = data.drain || {draining: false};
        if (!drain.draining) {
          setOutput(out, "ยังไม่ได้เปิด Graceful Drain");
          return;
        }
        const when = drain.requested_at
          ? new Date(drain.requested_at * 1000).toLocaleString("th-TH")
          : "ไม่ทราบเวลา";
        setOutput(out, `กำลัง Drain ตั้งแต่ ${when} — ช่องที่ทำงานอยู่จะหยุดหลังจบงาน`);
      } catch (err) {
        setOutput(out, `อ่านสถานะไม่สำเร็จ: ${err.message}`, true);
      }
    });

    return [row, out];
  }

  function buildSlicerSection() {
    const form = el("form", {class: "settings-grid", style: "grid-template-columns:1fr"});
    const pathId = "mcSlicerPath";
    const refId = "mcSlicerRef";
    const pathField = el("div", {class: "field"});
    pathField.append(
      el("label", {for: pathId}, "พาธไฟล์ในโปรเจกต์"),
      el("input", {id: pathId, name: "path", placeholder: "เช่น auto_dev_crew/runner.py…", autocomplete: "off", spellcheck: "false"})
    );
    const refField = el("div", {class: "field"});
    refField.append(
      el("label", {for: refId}, "ข้อความอ้างอิง (ใส่ได้ เช่นข้อความ issue ที่อ้างเลขบรรทัด)"),
      el("textarea", {id: refId, name: "reference", rows: "3", placeholder: "เช่น ดูบั๊กที่ line 1200…", autocomplete: "off"})
    );
    const go = button("ดูตัวอย่างการตัด", {type: "submit"});
    const out = el("div", {class: "adc-out", "aria-live": "polite"});
    const actions = el("div", {class: "row", style: "margin-top:10px"});
    actions.appendChild(go);
    form.append(pathField, refField, actions);

    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const path = form.elements.path.value.trim();
      if (!path) {
        setOutput(out, "กรอกพาธไฟล์ก่อน", true);
        return;
      }
      setOutput(out, "กำลังตัดไฟล์…");
      try {
        const data = await mcRequest("POST", "/api/context-slicer/preview", {
          path, reference: form.elements.reference.value
        });
        out.textContent = "";
        out.appendChild(el("p", {class: "muted"},
          `${data.path}: ${data.total_lines} บรรทัด · อ้างอิง ${data.cited_lines.length} บรรทัด · ` +
          `${data.windows.length} ช่วง · ส่งได้ ${data.sliced_chars} ตัวอักษร`));
        out.appendChild(el("pre", {class: "adc-code"}, data.preview + (data.truncated ? "\n… (แสดงเฉพาะ 4000 ตัวอักษรแรก)" : "")));
      } catch (err) {
        setOutput(out, `ตัดไฟล์ไม่สำเร็จ: ${err.message}`, true);
      }
    });

    return [form, out];
  }

  function mountMissionControlCard() {
    const anchor = document.getElementById("toolRevert");
    if (!anchor || !anchor.parentElement || document.getElementById("toolMissionControl")) return;

    const card = el("div", {class: "card", id: "toolMissionControl"});
    card.appendChild(el("div", {class: "card-head"}, null)).appendChild(el("h2", {}, "🛰️ Mission Control"));
    card.appendChild(el("p", {class: "muted"}, "ขอหยุดอย่างปลอดภัย (Graceful Drain) และดูตัวอย่างการตัดไฟล์ · ไม่แตะ GitHub"));

    card.appendChild(el("h3", {}, "Graceful Drain"));
    buildDrainSection().forEach((node) => card.appendChild(node));

    card.appendChild(el("h3", {}, "Context Slicer (ดูตัวอย่างอย่างเดียว)"));
    buildSlicerSection().forEach((node) => card.appendChild(node));

    anchor.parentElement.insertBefore(card, anchor);
  }

  // โหมดการแสดงผล (ง่าย / โปร) อยู่บนแถบบน (topbar) ไม่ได้อยู่ในการ์ด Mission Control
  function bindModeSwitch() {
    document.querySelectorAll("[data-mode-btn]").forEach((btn) => {
      btn.addEventListener("click", () => setUiComplexityMode(btn.dataset.modeBtn));
    });
    applyUiMode(storageGet("adc_ui_mode", "simple"));
  }

  // 5. บทแนะนำการใช้งาน (Tutorial): เปิดอัตโนมัติครั้งแรก และเปิดซ้ำได้จากหน้าตั้งค่า
  // ใช้ textContent เท่านั้น · ภาษาตาม adc_lang ของหน้า (th / en) ณ ตอนเปิด
  const TUTORIAL_STEPS = [
    {
      target: null,
      th: {title: "ยินดีต้อนรับสู่ Auto Dev Crew", body: "เริ่มต้นด้วยโหมด \"ง่าย\" ซึ่งแสดงเฉพาะเมนูที่จำเป็น เปลี่ยนเป็นโหมด \"โปร\" ได้ทุกเมื่อที่มุมบนขวา (ง่าย / โปร)"},
      en: {title: "Welcome to Auto Dev Crew", body: "You start in Simple mode, which shows only the essentials. Switch to Pro any time with the Simple / Pro toggle at the top right."}
    },
    {
      target: "overview",
      th: {title: "ภาพรวม", body: "ดูว่าเอเจนต์กำลังทำอะไร และมีงานที่รอให้คุณตัดสินใจหรือไม่"},
      en: {title: "Overview", body: "See what the agents are doing and whether anything is waiting for your decision."}
    },
    {
      target: "studio",
      th: {title: "สตูดิโอ", body: "บอก AI ว่าต้องทำอะไร ระบบจะสร้างเป็น issue ให้เอเจนต์ทำ"},
      en: {title: "Studio", body: "Tell the AI what to do. The system turns it into an issue for an agent to work on."}
    },
    {
      target: "keys",
      th: {title: "คีย์ AI", body: "เพิ่มคีย์ของผู้ให้บริการ AI อย่างน้อยหนึ่งตัวก่อนเริ่มงาน"},
      en: {title: "AI keys", body: "Add at least one AI provider key before you start work."}
    },
    {
      target: "work",
      th: {title: "งาน", body: "ดูบันทึกสดและประวัติงานที่เอเจนต์ทำไปแล้ว"},
      en: {title: "Work", body: "Watch the live log and review the history of finished agent work."}
    },
    {
      target: "settings",
      th: {title: "ตั้งค่า", body: "เปลี่ยนภาษา และเปิดบทแนะนำนี้ดูอีกครั้งได้ที่นี่ · พร้อมแล้ว เริ่มจากปุ่ม ➕ สั่งงานใหม่ ที่มุมบนขวา"},
      en: {title: "Settings", body: "Change the language and reopen this guide here. Ready? Start with the ➕ New task button at the top right."}
    }
  ];

  // เสร็จหรือข้ามแล้ว = จำไว้ในเบราว์เซอร์นี้ (ถ้า storage ใช้ไม่ได้ บทแนะนำจะเปิดทุกครั้งที่โหลดหน้า)
  function tutorialDone() {
    return storageGet("adc_tutorial_done", "false") === "true";
  }

  function tutorialLang() {
    return storageGet("adc_lang", "th") === "en" ? "en" : "th";
  }

  function goToPanel(main) {
    const btn = document.querySelector(`nav.side button[data-main="${main}"]`);
    if (btn) btn.click();
  }

  function openTutorial() {
    const old = document.getElementById("adcTutorialDlg");
    if (old) old.remove();
    const lang = tutorialLang();
    const ui = lang === "en"
      ? {skip: "Skip", back: "Back", next: "Next", finish: "Finish", counter: (n, t) => `${n} / ${t}`}
      : {skip: "ข้าม", back: "ย้อนกลับ", next: "ถัดไป", finish: "เสร็จสิ้น", counter: (n, t) => `${n} / ${t}`};

    const dlg = el("dialog", {id: "adcTutorialDlg", "aria-labelledby": "adcTutorialTitle", style: "width:min(520px,94vw)"});
    const head = el("h2", {id: "adcTutorialTitle", style: "margin:0 0 6px"});
    const counter = el("p", {class: "muted", style: "margin:0 0 8px; font-size:12px"});
    const body = el("p", {style: "margin:0 0 12px"});
    const skipBtn = button(ui.skip, {class: "btn btn-sm"});
    const backBtn = button(ui.back, {class: "btn btn-sm"});
    const nextBtn = button(ui.next, {class: "btn btn-sm primary"});
    const actions = el("div", {class: "row", style: "gap:8px; flex-wrap:wrap"});
    actions.append(skipBtn, el("span", {class: "spacer"}), backBtn, nextBtn);
    dlg.append(counter, head, body, actions);

    let i = 0;
    function render() {
      const step = TUTORIAL_STEPS[i];
      const text = step[lang];
      head.textContent = text.title;
      body.textContent = text.body;
      counter.textContent = ui.counter(i + 1, TUTORIAL_STEPS.length);
      backBtn.disabled = i === 0;
      nextBtn.textContent = i === TUTORIAL_STEPS.length - 1 ? ui.finish : ui.next;
      if (step.target) goToPanel(step.target);
    }

    // ทำงานซ้ำได้ (idempotent): บันทึกว่าดูแล้วและเอาออกจากหน้า
    function onClosed() {
      storageSet("adc_tutorial_done", "true");
      dlg.remove();
    }
    // ไม่พึ่ง event "close" ที่อาจมาช้า: บันทึกและเอาออกทันที แล้วค่อยปิด dialog
    function closeTutorial() {
      if (dlg.open && typeof dlg.close === "function") dlg.close();
      onClosed();
    }

    skipBtn.addEventListener("click", closeTutorial);
    backBtn.addEventListener("click", () => {
      if (i > 0) { i -= 1; render(); }
    });
    nextBtn.addEventListener("click", () => {
      if (i < TUTORIAL_STEPS.length - 1) { i += 1; render(); }
      else closeTutorial();
    });
    dlg.addEventListener("close", onClosed);

    document.body.append(dlg);
    render();
    if (typeof dlg.showModal === "function") dlg.showModal();
    else dlg.setAttribute("open", "");
  }

  function maybeAutoOpenTutorial() {
    if (!tutorialDone()) setTimeout(openTutorial, 400);
  }

  function bindTutorial() {
    const btn = document.getElementById("openTutorialBtn");
    if (btn) btn.addEventListener("click", openTutorial);
  }

  function initMissionControl() {
    bindModeSwitch();
    mountMissionControlCard();
    bindTutorial();
    maybeAutoOpenTutorial();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initMissionControl);
  } else {
    initMissionControl();
  }

  window.AutoDevCrewMissionControl = {
    esc,
    QUIZ_ITEMS,
    setUiComplexityMode,
    hasPassedSafetyQuiz,
    guardHighAutonomySelection,
    validateClientRepo,
    validateClientEnvKey
  };
})();
