/**
 * VlogForge i18n 国际化模块
 * 轻量级前端多语言支持，不依赖任何框架
 *
 * 功能：
 * - 自动检测语言：localStorage > 浏览器语言 > 回退 'zh-CN'
 * - 加载 JSON 翻译文件：/i18n/{lang}.json
 * - 全局 t(key, params) 函数：支持点号嵌套 + {param} 模板替换
 * - applyStaticTranslations()：批量更新 [data-i18n] 和 [data-i18n-placeholder] 元素
 * - switchLanguage(lang)：切换语言并刷新页面
 */

(function () {
  "use strict";

  // 支持的语言列表
  const SUPPORTED_LANGS = ["zh-CN", "en", "ja", "ko", "es", "pt"];

  // 默认语言
  const DEFAULT_LANG = "zh-CN";

  // 翻译数据缓存
  let _translations = {};

  // 当前语言
  let _currentLang = DEFAULT_LANG;

  /**
   * 检测用户语言偏好
   * 优先级：localStorage > 浏览器语言 > 默认值
   */
  function detectLanguage() {
    // 1. localStorage
    const saved = localStorage.getItem("vlogforge_lang");
    if (saved && SUPPORTED_LANGS.includes(saved)) return saved;

    // 2. 浏览器语言
    const browserLangs = navigator.languages || [navigator.language || navigator.userLanguage || ""];
    for (const lang of browserLangs) {
      // 精确匹配
      if (SUPPORTED_LANGS.includes(lang)) return lang;
      // 前缀匹配（如 zh → zh-CN, es-MX → es）
      const prefix = lang.split("-")[0];
      const match = SUPPORTED_LANGS.find(
        (s) => s === prefix || s.startsWith(prefix + "-")
      );
      if (match) return match;
    }

    // 3. 回退默认
    return DEFAULT_LANG;
  }

  /**
   * 加载翻译文件
   * @param {string} lang - 语言代码
   * @returns {Promise<object>} 翻译对象
   */
  async function loadTranslations(lang) {
    try {
      const url = `/i18n/${lang}.json?v=${Date.now()}`;
      const resp = await fetch(url);
      if (!resp.ok) {
        console.warn(`[i18n] 翻译文件加载失败: ${lang} (${resp.status})，回退到 ${DEFAULT_LANG}`);
        if (lang !== DEFAULT_LANG) {
          return loadTranslations(DEFAULT_LANG);
        }
        return {};
      }
      return await resp.json();
    } catch (err) {
      console.error(`[i18n] 加载翻译文件异常:`, err);
      if (lang !== DEFAULT_LANG) {
        return loadTranslations(DEFAULT_LANG);
      }
      return {};
    }
  }

  /**
   * 通过点号路径获取嵌套对象的值
   * @param {object} obj - 翻译对象
   * @param {string} key - 点号分隔的键路径，如 "nav.items"
   * @returns {string|undefined}
   */
  function getNestedValue(obj, key) {
    const parts = key.split(".");
    let current = obj;
    for (const part of parts) {
      if (current == null || typeof current !== "object") return undefined;
      current = current[part];
    }
    return current;
  }

  /**
   * 翻译函数
   * @param {string} key - 翻译键，支持点号嵌套，如 "toast.createSuccess"
   * @param {object} [params] - 模板参数，如 {name: "洗面奶"} 替换 "{name}"
   * @returns {string} 翻译后的字符串，找不到则返回 key 本身
   */
  function t(key, params) {
    let value = getNestedValue(_translations, key);

    // 找不到翻译，返回 key 本身（方便开发时定位缺失的翻译）
    if (value === undefined || value === null) {
      // 开发模式下打印警告
      if (_currentLang !== DEFAULT_LANG) {
        console.warn(`[i18n] 缺失翻译: "${key}" (${_currentLang})`);
      }
      return key;
    }

    // 确保是字符串
    if (typeof value !== "string") {
      return String(value);
    }

    // 模板参数替换：将 {paramName} 替换为 params 中的对应值
    if (params && typeof params === "object") {
      value = value.replace(/\{(\w+)\}/g, (match, paramName) => {
        return params[paramName] !== undefined ? String(params[paramName]) : match;
      });
    }

    return value;
  }

  /**
   * 批量更新页面中的静态翻译
   * 扫描所有带 data-i18n 和 data-i18n-placeholder 属性的元素
   */
  function applyStaticTranslations() {
    // 更新 textContent
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.getAttribute("data-i18n");
      if (!key) return;
      const translated = t(key);
      // 只在翻译存在（且不等于 key 本身，除非是默认语言）时更新
      if (translated !== key || _currentLang === DEFAULT_LANG) {
        el.textContent = translated;
      }
    });

    // 更新 innerHTML（用于包含 HTML 实体的元素，如 &#9889;）
    document.querySelectorAll("[data-i18n-html]").forEach((el) => {
      const key = el.getAttribute("data-i18n-html");
      if (!key) return;
      const translated = t(key);
      if (translated !== key || _currentLang === DEFAULT_LANG) {
        el.innerHTML = translated;
      }
    });

    // 更新 placeholder
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      const key = el.getAttribute("data-i18n-placeholder");
      if (!key) return;
      const translated = t(key);
      if (translated !== key || _currentLang === DEFAULT_LANG) {
        el.placeholder = translated;
      }
    });

    // 更新 title 属性
    document.querySelectorAll("[data-i18n-title]").forEach((el) => {
      const key = el.getAttribute("data-i18n-title");
      if (!key) return;
      const translated = t(key);
      if (translated !== key || _currentLang === DEFAULT_LANG) {
        el.title = translated;
      }
    });

    // 更新页面标题
    const titleKey = document.documentElement.getAttribute("data-i18n-title");
    if (titleKey) {
      document.title = t(titleKey);
    }
  }

  /**
   * 切换语言（无需刷新页面）
   * @param {string} lang - 目标语言代码
   */
  async function switchLanguage(lang) {
    if (!SUPPORTED_LANGS.includes(lang)) {
      console.warn(`[i18n] 不支持的语言: ${lang}`);
      return;
    }
    localStorage.setItem("vlogforge_lang", lang);
    _currentLang = lang;

    // 重新加载翻译文件
    _translations = await loadTranslations(lang);

    // 更新 HTML lang 属性
    document.documentElement.lang = lang;

    // 批量更新静态翻译
    applyStaticTranslations();

    // 通知其他模块（如 app.js）刷新动态内容
    window.dispatchEvent(new CustomEvent("i18n:langChanged", { detail: { lang } }));
  }

  /**
   * 获取当前语言
   * @returns {string}
   */
  function getCurrentLang() {
    return _currentLang;
  }

  /**
   * 获取支持的语言列表
   * @returns {string[]}
   */
  function getSupportedLangs() {
    return [...SUPPORTED_LANGS];
  }

  /**
   * 初始化 i18n
   * 检测语言 → 加载翻译文件 → 应用静态翻译
   */
  async function initI18n() {
    _currentLang = detectLanguage();
    console.log(`[i18n] 当前语言: ${_currentLang}`);

    // 更新 HTML lang 属性
    document.documentElement.lang = _currentLang;

    // 加载翻译文件
    _translations = await loadTranslations(_currentLang);

    // 应用静态翻译
    applyStaticTranslations();

    // 初始化语言切换器（如果存在）
    const langSwitcher = document.getElementById("lang-switcher");
    if (langSwitcher) {
      langSwitcher.value = _currentLang;
      langSwitcher.addEventListener("change", async (e) => {
        await switchLanguage(e.target.value);
      });
    }
  }

  // 导出到全局
  window.t = t;
  window.applyStaticTranslations = applyStaticTranslations;
  window.switchLanguage = switchLanguage;
  window.getCurrentLang = getCurrentLang;
  window.getSupportedLangs = getSupportedLangs;
  window.i18nReady = false;

  // 创建 Promise 供其他模块 await（如 app.js 在初始化前等翻译加载完成）
  let _resolveReady;
  window.i18nPromise = new Promise((resolve) => { _resolveReady = resolve; });

  function markReady() {
    window.i18nReady = true;
    _resolveReady();
    window.dispatchEvent(new CustomEvent("i18n:ready", { detail: { lang: _currentLang } }));
  }

  // DOM 加载完成后自动初始化
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", async () => {
      await initI18n();
      markReady();
    });
  } else {
    // DOM 已加载（例如 defer 脚本），直接初始化
    initI18n().then(() => {
      markReady();
    });
  }
})();
