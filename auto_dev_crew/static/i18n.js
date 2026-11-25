/* ตัวแปลหน้าเว็บ (แทนระบบแทนข้อความย่อยแบบเดิม)
 * - ข้อความไทยเป็นคีย์ของพจนานุกรม ค่าอังกฤษมาจาก GET /api/i18n (auto_dev_crew/locales/en.json)
 * - window.i18n(key, params?)            คืนข้อความตามภาษาที่ตั้งไว้ ไม่พบคีย์คืนคีย์เอง (= ไทย)
 * - window.applyI18n(root?)           แปล [data-i18n] (ข้อความ) และ [data-i18n-attr="title placeholder"] (attribute)
 * - window.adcLoadI18n(token?)        โหลดพจนานุกรมและภาษาจากเซิร์ฟเวอร์; เรียกครั้งเดียวตอนเริ่มหน้า
 * - window.adcI18nReady               Promise ที่จบเมื่อโหลดเสร็จ (สำเร็จหรือไม่ก็ตาม)
 * - window.setLanguage(lang)          บันทึกภาษาในเซิร์ฟเวอร์แล้วโหลดหน้าใหม่
 * ถ้าโหลดพจนานุกรมไม่ได้ ใช้ข้อความไทยเดิมทั้งหน้า */
(function () {
  "use strict";
  var lang = "en";
  var dict = {};

  function t(key, params) {
    var text = (lang === "en" && Object.prototype.hasOwnProperty.call(dict, key)) ? dict[key] : key;
    if (params) {
      text = text.replace(/\{(\w+)\}/g, function (m, name) {
        return Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : m;
      });
    }
    return text;
  }
  window.i18n = t;
  window.adcLang = lang;

  function applyI18n(root) {
    var scope = root || document;
    scope.querySelectorAll("[data-i18n]").forEach(function (el) {
      if (!el.dataset.adcKey) {
        // data-i18n="html" = ข้อความมี HTML ปน (เช่น <strong>, <code>) ใช้ innerHTML เดิมเป็นคีย์
        el.dataset.adcHtml = el.getAttribute("data-i18n") === "html" ? "1" : "";
        el.dataset.adcKey = el.dataset.adcHtml ? el.innerHTML.trim() : el.textContent.trim();
      }
      if (el.dataset.adcHtml) el.innerHTML = t(el.dataset.adcKey);
      else el.textContent = t(el.dataset.adcKey);
    });
    scope.querySelectorAll("[data-i18n-attr]").forEach(function (el) {
      el.getAttribute("data-i18n-attr").split(/\s+/).forEach(function (attr) {
        if (!attr) return;
        var orig = el.dataset["adcOrig_" + attr.replace(/-/g, "_")];
        if (orig === undefined) {
          orig = el.getAttribute(attr) || "";
          el.dataset["adcOrig_" + attr.replace(/-/g, "_")] = orig;
        }
        el.setAttribute(attr, t(orig));
      });
    });
    document.documentElement.lang = lang;
  }
  window.applyI18n = applyI18n;

  function headers(token, json) {
    var h = {};
    if (token) h["X-Token"] = token;
    if (json) h["Content-Type"] = "application/json";
    return h;
  }

  // ทางหลัก: เซิร์ฟเวอร์ฝัง window.ADC_INIT = {lang, dict} ลงในหน้าตอนเสิร์ฟ (ซิงโครนัส ไม่มีช่วงแสดงผลเป็นไทย)
  if (window.ADC_INIT) {
    lang = window.ADC_INIT.lang === "en" ? "en" : "th";
    dict = window.ADC_INIT.dict || {};
    window.adcI18nReady = Promise.resolve();
  }
  window.adcLang = lang;

  // ทางสำรอง: โหลดจาก API (ช่วงนี้หน้าอาจแสดงไทยก่อน)
  window.adcLoadI18n = function (token) {
    if (window.ADC_INIT) {
      window.adcI18nReady = Promise.resolve();
      return window.adcI18nReady;
    }
    window.adcI18nReady = fetch("/api/i18n", { headers: headers(token, false) })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (data) {
        lang = data.lang === "en" ? "en" : "th";
        dict = data.dict || {};
        window.adcLang = lang;
      })
      .catch(function (err) {
        console.warn("Failed to load i18n dictionary, using English fallback:", err);
        lang = "en";
        dict = {};
        window.adcLang = lang;
      });
    return window.adcI18nReady;
  };

  window.setLanguage = function (next, token) {
    var value = next === "en" ? "en" : "th";
    return fetch("/api/settings/language", {
      method: "POST",
      headers: headers(token, true),
      body: JSON.stringify({ lang: value })
    }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      location.reload();
    });
  };
})();
