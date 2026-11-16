/* ตัวแปลหน้า GUI เป็น English (ทำงานเมื่อ adc_lang = "en" เท่านั้น)
 * - แปลข้อความและ attribute (title / placeholder / aria-label) ทั้งหน้าตอนโหลด
 * - MutationObserver แปลข้อความที่ JS เขียนเพิ่มทีหลัง (ตาราง, toast, ฯลฯ)
 * - confirm() / alert() แปลข้อความก่อนแสดง
 * พจนานุกรมอยู่ใน i18n_en.js (window.ADC_EN) ข้อความจริง เช่น ชื่อ issue และ log ของเอเจนต์ยังเป็นภาษาไทย */
(function () {
  "use strict";
  var lang = "th";
  try { lang = localStorage.getItem("adc_lang") === "en" ? "en" : "th"; } catch (e) { /* ใช้ค่าเริ่มต้น */ }
  if (lang !== "en" || !window.ADC_EN) return;

  var DICT = window.ADC_EN;
  var THAI = /[฀-๿]/;
  var KEYS = Object.keys(DICT)
    .filter(function (k) { return k.trim().length > 0; })
    .sort(function (a, b) { return b.length - a.length; });
  // วลีที่แทนได้ภายในข้อความยาว: ยาว >= 12 ตัวอักษร หรือมีช่องว่าง/วงเล็บและยาว >= 3
  // (คำไทยเดี่ยว ๆ เช่น "บรรทัด" "สถานะ" ไม่แทนในข้อความ เพราะจะไปทับข้อมูลจริง เช่น ชื่อ issue)
  function isPhrase(k) {
    var t = k.trim();
    return t.length >= 12 || (/[\s()]/.test(k) && t.length >= 3);
  }
  var ATTRS = ["title", "placeholder", "aria-label"];
  var SKIP = { SCRIPT: 1, STYLE: 1, TEXTAREA: 1, CODE: 1, PRE: 0 };

  // แปลข้อความหนึ่งชิ้น: ตรงทั้งข้อความก่อน แล้วค่อยแทนวลีที่ยาว (>= 5 ตัวอักษร) ที่อยู่ในข้อความ
  function tr(s) {
    if (!s || !THAI.test(s)) return s;
    var t = s.trim().replace(/\r\n/g, "\n");
    if (Object.prototype.hasOwnProperty.call(DICT, t)) {
      var lead = s.match(/^\s*/)[0];
      var trail = s.match(/\s*$/)[0];
      return lead + DICT[t] + trail;
    }
    var out = s;
    for (var i = 0; i < KEYS.length; i++) {
      var k = KEYS[i];
      if (!isPhrase(k)) continue;
      if (out.indexOf(k) !== -1) out = out.split(k).join(DICT[k]);
    }
    if (out !== s) {
      // เว้นช่องว่างระหว่างคำอังกฤษที่แทนแล้วกับตัวอักษรไทยที่ติดกัน (เช่น "ลำดับProvider" → "ลำดับ Provider")
      out = out.replace(/([A-Za-z0-9\)])([฀-๿])/g, "$1 $2").replace(/([฀-๿])([A-Za-z0-9\(])/g, "$1 $2");
    }
    return out;
  }
  window.ADC_trText = tr;

  function translateText(node) {
    var cur = node.nodeValue;
    var nv = tr(cur);
    if (nv !== cur) node.nodeValue = nv;
  }

  function translateAttrs(el) {
    for (var i = 0; i < ATTRS.length; i++) {
      var a = ATTRS[i];
      if (!el.hasAttribute || !el.hasAttribute(a)) continue;
      var v = el.getAttribute(a);
      var nv = tr(v);
      if (nv !== v) el.setAttribute(a, nv);
    }
    if (el.tagName === "INPUT" && (el.type === "button" || el.type === "submit") && el.value) {
      var nvv = tr(el.value);
      if (nvv !== el.value) el.value = nvv;
    }
  }

  function walk(node) {
    if (node.nodeType === 3) return translateText(node);
    if (node.nodeType !== 1) return;
    translateAttrs(node); // แปล placeholder ของ TEXTAREA ด้วย แม้ไม่แปลเนื้อหาข้างใน
    if (SKIP[node.tagName]) return;
    for (var c = node.firstChild; c; c = c.nextSibling) walk(c);
  }

  var observer = new MutationObserver(function (records) {
    observer.disconnect();
    try {
      records.forEach(function (rec) {
        if (rec.type === "childList") {
          for (var i = 0; i < rec.addedNodes.length; i++) walk(rec.addedNodes[i]);
        } else if (rec.type === "characterData") {
          translateText(rec.target);
        } else if (rec.type === "attributes") {
          translateAttrs(rec.target);
        }
      });
    } finally {
      observe();
    }
  });

  function observe() {
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ATTRS
    });
  }

  function start() {
    document.documentElement.lang = "en";
    walk(document.body);
    observe();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();

  var nativeConfirm = window.confirm.bind(window);
  var nativeAlert = window.alert.bind(window);
  window.confirm = function (msg) { return nativeConfirm(tr(String(msg))); };
  window.alert = function (msg) { return nativeAlert(tr(String(msg))); };
})();
