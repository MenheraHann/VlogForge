/**
 * VlogForge 前端交互逻辑 (v5)
 * 统一主页：素材库三列 + 生成区拖拽槽位
 * 智能问卷：物品创建走 analyze → 问卷确认 → confirm
 * 素材详情：点击卡片展开详情面板
 */

// ========== 工具 ==========
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function escapeHtml(str) {
  if (!str) return "";
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function showToast(message, type = "info") {
  let container = $(".toast-container");
  if (!container) {
    container = document.createElement("div");
    container.className = "toast-container";
    document.body.appendChild(container);
  }
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(20px)";
    toast.style.transition = "all 0.3s";
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

// ========== 状态 ==========
let assets = { items: [], models: [], scenes: [] };
let currentJobId = null;
let eventSource = null;
let currentScript = null;

// 生成区槽位绑定的素材
let slotAssets = { item: null, model: null, scene: null };

// ========== 导航 ==========

function showView(viewId) {
  $$(".view").forEach((v) => v.classList.remove("active"));
  const view = $(`#view-${viewId}`);
  if (view) view.classList.add("active");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

$("#nav-logo").addEventListener("click", () => { showView("home"); refreshAssets(); });

// ========== 素材库 CRUD ==========

async function refreshAssets() {
  try {
    const res = await fetch("/api/assets");
    if (!res.ok) throw new Error("加载素材失败");
    const data = await res.json();
    assets.items = data.items || [];
    assets.models = data.models || [];
    assets.scenes = data.scenes || [];

    $("#count-items").textContent = assets.items.length;
    $("#count-models").textContent = assets.models.length;
    $("#count-scenes").textContent = assets.scenes.length;

    renderColumnList("items", assets.items, "#col-items");
    renderColumnList("models", assets.models, "#col-models");
    renderColumnList("scenes", assets.scenes, "#col-scenes");
  } catch (err) {
    console.error("[Assets] 加载失败:", err);
  }
}

function renderColumnList(type, list, containerSel) {
  const container = $(containerSel);
  container.innerHTML = "";

  if (list.length === 0) {
    container.innerHTML = `<div style="text-align:center;color:var(--text-muted);font-size:0.8rem;padding:1rem 0;">暂无素材</div>`;
    return;
  }

  list.forEach((asset) => {
    const card = createMiniCard(type, asset);
    container.appendChild(card);
  });
}

function getAssetThumbUrl(asset) {
  const imgPath = asset.instruction_image || asset.selected_look || asset.selected_scene;
  if (!imgPath) return null;
  const filename = imgPath.split("/").pop();
  return `/assets/${asset.id}/${filename}`;
}

function createMiniCard(type, asset) {
  const card = document.createElement("div");
  card.className = "asset-mini-card";
  card.draggable = true;

  // 拖拽数据
  const slotType = type === "items" ? "item" : type === "models" ? "model" : "scene";
  card.addEventListener("dragstart", (e) => {
    e.dataTransfer.setData("application/vlogforge-asset", JSON.stringify({ type: slotType, id: asset.id }));
    e.dataTransfer.effectAllowed = "copy";
    card.classList.add("dragging");
  });
  card.addEventListener("dragend", () => card.classList.remove("dragging"));

  // 缩略图
  const thumbUrl = getAssetThumbUrl(asset);
  let thumbHtml = "";
  if (thumbUrl) {
    thumbHtml = `<img class="asset-mini-thumb" src="${thumbUrl}" alt="${escapeHtml(asset.name)}" onerror="this.style.display='none'">`;
  } else {
    const icons = { items: "&#128230;", models: "&#128100;", scenes: "&#127968;" };
    thumbHtml = `<div class="asset-mini-thumb-placeholder">${icons[type]}</div>`;
  }

  // 元数据
  let meta = "";
  if (type === "items") meta = asset.selling_point || asset.category || "";
  else if (type === "models") meta = asset.personality || "";
  else meta = asset.mood || "";

  // 状态标签
  let badge = "";
  if (type === "items") {
    const qs = asset.questionnaire_status || "completed";
    badge = qs === "completed"
      ? `<span class="asset-mini-badge success">已完成</span>`
      : `<span class="asset-mini-badge warning">待确认</span>`;
  } else if (type === "models") {
    badge = asset.selected_look
      ? `<span class="asset-mini-badge success">已选造型</span>`
      : `<span class="asset-mini-badge warning">待选造型</span>`;
  } else if (type === "scenes") {
    badge = asset.selected_scene
      ? `<span class="asset-mini-badge success">已选方案</span>`
      : `<span class="asset-mini-badge warning">待选方案</span>`;
  }

  card.innerHTML = `
    <div class="asset-mini-card-inner">
      ${thumbHtml}
      <div class="asset-mini-info">
        <div class="asset-mini-name">${escapeHtml(asset.name)}</div>
        <div class="asset-mini-meta">${escapeHtml(meta)}</div>
      </div>
    </div>
    <div class="asset-mini-actions">
      ${badge}
      <button class="btn-sm btn-detail" data-detail="${asset.id}">详情</button>
      <button class="btn-sm btn-danger" data-delete="${asset.id}">删除</button>
    </div>
  `;

  // 点击详情
  card.querySelector("[data-detail]").addEventListener("click", (e) => {
    e.stopPropagation();
    openDetailModal(type, asset);
  });

  // 点击删除
  card.querySelector("[data-delete]").addEventListener("click", async (e) => {
    e.stopPropagation();
    if (!confirm(`确定删除 ${asset.name}？`)) return;
    try {
      const res = await fetch(`/api/assets/${asset.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("删除失败");
      showToast(`${asset.name} 已删除`, "success");
      // 如果槽位绑定了这个素材，清空
      if (slotAssets[slotType] && slotAssets[slotType].id === asset.id) clearSlot(slotType);
      refreshAssets();
    } catch (err) {
      showToast(`删除失败: ${err.message}`, "error");
    }
  });

  return card;
}

// ========== 素材详情模态框 ==========

function openDetailModal(type, asset) {
  const modal = $("#detail-modal");
  const title = $("#detail-modal-title");
  const body = $("#detail-modal-body");

  const labels = { items: "物品", models: "人物", scenes: "场景" };
  title.textContent = `${labels[type]}详情 - ${asset.name}`;

  let content = "";

  if (type === "items") {
    const thumbUrl = getAssetThumbUrl(asset);
    const imgHtml = thumbUrl ? `<img src="${thumbUrl}" class="detail-img" onerror="this.style.display='none'">` : "";

    // 卖点
    const sp = asset.selling_points || {};
    let spHtml = "";
    if (sp.P0 && sp.P0.length) spHtml += `<div class="sp-group"><span class="sp-label sp-p0">P0 核心</span>${sp.P0.map(s => `<span class="sp-tag">${escapeHtml(s)}</span>`).join("")}</div>`;
    if (sp.P1 && sp.P1.length) spHtml += `<div class="sp-group"><span class="sp-label sp-p1">P1 辅助</span>${sp.P1.map(s => `<span class="sp-tag">${escapeHtml(s)}</span>`).join("")}</div>`;
    if (sp.P2 && sp.P2.length) spHtml += `<div class="sp-group"><span class="sp-label sp-p2">P2 补充</span>${sp.P2.map(s => `<span class="sp-tag">${escapeHtml(s)}</span>`).join("")}</div>`;

    // product_info
    let infoHtml = "";
    const pi = asset.product_info || {};
    for (const [k, v] of Object.entries(pi)) {
      if (v) infoHtml += `<div class="detail-field"><span class="detail-field-label">${escapeHtml(k)}</span><span class="detail-field-value">${escapeHtml(v)}</span></div>`;
    }

    content = `
      ${imgHtml}
      <div class="detail-section">
        <div class="detail-field"><span class="detail-field-label">类别</span><span class="detail-field-value">${escapeHtml(asset.category)}</span></div>
        <div class="detail-field"><span class="detail-field-label">核心卖点</span><span class="detail-field-value">${escapeHtml(asset.selling_point)}</span></div>
        <div class="detail-field"><span class="detail-field-label">使用方式</span><span class="detail-field-value">${escapeHtml(asset.usage)}</span></div>
      </div>
      ${spHtml ? `<div class="detail-section"><h4>卖点优先级</h4>${spHtml}</div>` : ""}
      ${infoHtml ? `<div class="detail-section"><h4>产品信息</h4>${infoHtml}</div>` : ""}
      <div class="detail-section"><h4>完整描述</h4><p class="detail-desc">${escapeHtml(asset.full_description)}</p></div>
    `;
  } else if (type === "models") {
    const thumbUrl = getAssetThumbUrl(asset);
    const imgHtml = thumbUrl ? `<img src="${thumbUrl}" class="detail-img" onerror="this.style.display='none'">` : "";
    content = `
      ${imgHtml}
      <div class="detail-section">
        <div class="detail-field"><span class="detail-field-label">外貌</span><span class="detail-field-value">${escapeHtml(asset.appearance)}</span></div>
        <div class="detail-field"><span class="detail-field-label">气质</span><span class="detail-field-value">${escapeHtml(asset.personality)}</span></div>
        <div class="detail-field"><span class="detail-field-label">穿搭</span><span class="detail-field-value">${escapeHtml(asset.outfits)}</span></div>
      </div>
      <div class="detail-section"><h4>完整描述</h4><p class="detail-desc">${escapeHtml(asset.full_description)}</p></div>
    `;
  } else {
    const thumbUrl = getAssetThumbUrl(asset);
    const imgHtml = thumbUrl ? `<img src="${thumbUrl}" class="detail-img" onerror="this.style.display='none'">` : "";
    content = `
      ${imgHtml}
      <div class="detail-section">
        <div class="detail-field"><span class="detail-field-label">环境</span><span class="detail-field-value">${escapeHtml(asset.environment)}</span></div>
        <div class="detail-field"><span class="detail-field-label">光线</span><span class="detail-field-value">${escapeHtml(asset.lighting)}</span></div>
        <div class="detail-field"><span class="detail-field-label">氛围</span><span class="detail-field-value">${escapeHtml(asset.mood)}</span></div>
      </div>
      <div class="detail-section"><h4>完整描述</h4><p class="detail-desc">${escapeHtml(asset.full_description)}</p></div>
    `;
  }

  body.innerHTML = content;
  modal.style.display = "flex";
}

$("#detail-modal-close").addEventListener("click", () => { $("#detail-modal").style.display = "none"; });
$("#detail-modal").addEventListener("click", (e) => { if (e.target === e.currentTarget) $("#detail-modal").style.display = "none"; });

// ========== 添加按钮 ==========
$$(".btn-add").forEach((btn) => {
  btn.addEventListener("click", () => openCreateModal(btn.dataset.create));
});

// ========== 创建素材模态框 ==========

function openCreateModal(type) {
  const modal = $("#create-modal");
  const title = $("#modal-title");
  const body = $("#modal-body");
  const labels = { items: "物品", models: "人物", scenes: "场景" };
  title.textContent = `创建${labels[type]}素材`;

  const placeholders = {
    items: "描述产品信息，如：一瓶氨基酸洗面奶，温和配方不紧绷，适合敏感肌",
    models: "描述人物形象，如：20多岁的清新短发女生，亲和力强，适合美妆vlog",
    scenes: "描述拍摄场景，如：白色简约风格的浴室，光线明亮，干净清爽",
  };

  body.innerHTML = `
    <form id="create-asset-form">
      <div class="form-group">
        <label>描述</label>
        <textarea id="create-desc" rows="3" placeholder="${placeholders[type]}" required></textarea>
      </div>
      <div class="form-group">
        <label>参考图片（可选）</label>
        <div class="upload-zone" id="create-upload-zone">
          <input type="file" id="create-file-input" accept="image/*" multiple hidden>
          <div class="upload-placeholder" id="create-upload-placeholder">
            <span class="upload-icon">&#128247;</span>
            <span>点击上传参考图</span>
          </div>
          <div class="upload-preview-sm" id="create-upload-preview"></div>
        </div>
      </div>
      <button type="submit" class="btn-submit" id="create-submit-btn">创建${labels[type]}</button>
    </form>
  `;

  let createFiles = [];
  const zone = $("#create-upload-zone");
  const fileInput = $("#create-file-input");
  const placeholder = $("#create-upload-placeholder");
  const preview = $("#create-upload-preview");

  zone.addEventListener("click", (e) => {
    if (e.target.closest(".remove-img")) return;
    fileInput.click();
  });

  fileInput.addEventListener("change", () => {
    createFiles.push(...Array.from(fileInput.files).slice(0, 3 - createFiles.length));
    renderModalPreview();
    fileInput.value = "";
  });

  function renderModalPreview() {
    if (createFiles.length === 0) { placeholder.style.display = "flex"; preview.innerHTML = ""; return; }
    placeholder.style.display = "none";
    preview.innerHTML = "";
    createFiles.forEach((file, i) => {
      const w = document.createElement("div"); w.className = "img-wrapper";
      const img = document.createElement("img"); img.src = URL.createObjectURL(file);
      const btn = document.createElement("button"); btn.className = "remove-img"; btn.textContent = "\u00D7";
      btn.addEventListener("click", (e) => { e.stopPropagation(); createFiles.splice(i, 1); renderModalPreview(); });
      w.appendChild(img); w.appendChild(btn); preview.appendChild(w);
    });
  }

  $("#create-asset-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const submitBtn = $("#create-submit-btn");
    submitBtn.disabled = true;
    submitBtn.textContent = "创建中...";

    const desc = $("#create-desc").value.trim();

    if (type === "items") {
      // 物品走智能问卷流程
      await handleItemCreate(desc, createFiles, submitBtn, labels[type]);
    } else {
      // 人物/场景走原有流程
      const apiType = type === "models" ? "model" : "scene";
      const formData = new FormData();
      formData.append("description", desc);
      createFiles.forEach((f) => formData.append("images", f));

      try {
        const res = await fetch(`/api/assets/${apiType}`, { method: "POST", body: formData });
        if (!res.ok) { const err = await res.json(); throw new Error(err.detail || "创建失败"); }
        const data = await res.json();
        showToast(`${data.asset.name} 创建成功`, "success");
        closeCreateModal();

        if (type === "models" && data.look_options) {
          openSelectModal("model", data.asset, data.look_options);
        } else if (type === "scenes" && data.scene_options) {
          openSelectModal("scene", data.asset, data.scene_options);
        }
        refreshAssets();
      } catch (err) {
        showToast(`创建失败: ${err.message}`, "error");
        submitBtn.disabled = false;
        submitBtn.textContent = `创建${labels[type]}`;
      }
    }
  });

  modal.style.display = "flex";
}

// 物品创建 → 走智能问卷
async function handleItemCreate(desc, files, submitBtn, label) {
  const formData = new FormData();
  formData.append("description", desc);
  files.forEach((f) => formData.append("images", f));

  try {
    // 第 1 步：analyze
    const res = await fetch("/api/assets/item/analyze", { method: "POST", body: formData });
    if (!res.ok) { const err = await res.json(); throw new Error(err.detail || "分析失败"); }
    const data = await res.json();

    if (data.status === "rejected") {
      showToast(`物品被拒绝: ${data.reason}`, "error");
      closeCreateModal();
      return;
    }

    showToast(`${data.asset.name} 分析完成，请确认产品信息`, "success");
    closeCreateModal();

    // 打开问卷确认
    openQuestionnaireModal(data.asset, data.questionnaire, data.selling_points);
    refreshAssets();
  } catch (err) {
    showToast(`分析失败: ${err.message}`, "error");
    submitBtn.disabled = false;
    submitBtn.textContent = `创建${label}`;
  }
}

function closeCreateModal() { $("#create-modal").style.display = "none"; }
$("#modal-close").addEventListener("click", closeCreateModal);
$("#create-modal").addEventListener("click", (e) => { if (e.target === e.currentTarget) closeCreateModal(); });

// ========== 智能问卷模态框 ==========

function openQuestionnaireModal(asset, questionnaire, sellingPoints) {
  const modal = $("#questionnaire-modal");
  const title = $("#questionnaire-title");
  const body = $("#questionnaire-body");

  title.textContent = `产品信息确认 - ${asset.name}`;

  // 卖点展示
  let spHtml = "";
  if (sellingPoints) {
    const sp = sellingPoints;
    if (sp.P0 && sp.P0.length) spHtml += `<div class="sp-group"><span class="sp-label sp-p0">P0 核心</span>${sp.P0.map(s => `<span class="sp-tag">${escapeHtml(s)}</span>`).join("")}</div>`;
    if (sp.P1 && sp.P1.length) spHtml += `<div class="sp-group"><span class="sp-label sp-p1">P1 辅助</span>${sp.P1.map(s => `<span class="sp-tag">${escapeHtml(s)}</span>`).join("")}</div>`;
    if (sp.P2 && sp.P2.length) spHtml += `<div class="sp-group"><span class="sp-label sp-p2">P2 补充</span>${sp.P2.map(s => `<span class="sp-tag">${escapeHtml(s)}</span>`).join("")}</div>`;
  }

  // 问卷字段
  let fieldsHtml = "";
  (questionnaire || []).forEach((f, i) => {
    const priorityClass = `priority-${f.priority.toLowerCase()}`;
    const requiredMark = f.required ? '<span class="required">*</span>' : '<span class="optional">可选</span>';
    const sourceLabel = f.source === "ai" ? '<span class="ai-badge">AI 预填</span>' : '<span class="user-badge">待填写</span>';

    fieldsHtml += `
      <div class="q-field ${priorityClass}">
        <div class="q-field-header">
          <label>${escapeHtml(f.label)} ${requiredMark}</label>
          <div class="q-field-tags">
            <span class="q-priority">${f.priority}</span>
            ${sourceLabel}
          </div>
        </div>
        <input type="text" class="q-input" data-key="${f.key}" data-priority="${f.priority}"
          data-required="${f.required}" value="${escapeHtml(f.value)}"
          placeholder="${f.source === 'user' ? '请填写...' : ''}">
      </div>
    `;
  });

  body.innerHTML = `
    ${spHtml ? `<div class="q-section"><h4>ADA 识别的卖点</h4>${spHtml}</div>` : ""}
    <div class="q-section">
      <h4>请确认或修改以下信息</h4>
      <p style="color:var(--text-muted);font-size:0.85rem;margin-bottom:1rem;">AI 预填的内容可直接确认，空白项请补充填写</p>
      ${fieldsHtml}
    </div>
    <button class="btn-submit" id="q-confirm-btn">确认并创建素材</button>
  `;

  // 确认按钮
  body.querySelector("#q-confirm-btn").addEventListener("click", async () => {
    const btn = body.querySelector("#q-confirm-btn");

    // 验证必填项
    const inputs = body.querySelectorAll(".q-input");
    const confirmed = [];
    let hasError = false;

    inputs.forEach((input) => {
      const isRequired = input.dataset.required === "true";
      const value = input.value.trim();
      if (isRequired && !value) {
        input.classList.add("error");
        hasError = true;
      } else {
        input.classList.remove("error");
      }
      confirmed.push({
        key: input.dataset.key,
        label: input.previousElementSibling ? "" : "",
        value: value,
        priority: input.dataset.priority,
      });
    });

    // 从 DOM 获取 label
    confirmed.forEach((f, idx) => {
      const labelEl = inputs[idx].closest(".q-field").querySelector("label");
      f.label = labelEl ? labelEl.textContent.replace(/[*可选]/g, "").trim() : f.key;
    });

    if (hasError) {
      showToast("请填写所有必填项", "error");
      return;
    }

    btn.disabled = true;
    btn.textContent = "确认中...";

    try {
      const formData = new FormData();
      formData.append("confirmed_fields", JSON.stringify(confirmed));

      const res = await fetch(`/api/assets/item/${asset.id}/confirm`, { method: "POST", body: formData });
      if (!res.ok) { const err = await res.json(); throw new Error(err.detail || "确认失败"); }

      showToast("产品档案创建完成", "success");
      $("#questionnaire-modal").style.display = "none";
      refreshAssets();
    } catch (err) {
      showToast(`确认失败: ${err.message}`, "error");
      btn.disabled = false;
      btn.textContent = "确认并创建素材";
    }
  });

  modal.style.display = "flex";
}

$("#questionnaire-close").addEventListener("click", () => { $("#questionnaire-modal").style.display = "none"; });
$("#questionnaire-modal").addEventListener("click", (e) => { if (e.target === e.currentTarget) $("#questionnaire-modal").style.display = "none"; });

// ========== 选择方案模态框 ==========

function openSelectModal(assetType, asset, options) {
  const modal = $("#select-modal");
  const title = $("#select-modal-title");
  const body = $("#select-modal-body");

  const label = assetType === "model" ? "造型" : "场景方案";
  title.textContent = `选择${label} - ${asset.name}`;

  let cardsHtml = "";
  options.forEach((path, i) => {
    const filename = path.split("/").pop();
    cardsHtml += `
      <div class="option-card" data-index="${i}">
        <img src="/assets/${asset.id}/${filename}" alt="${label} ${String.fromCharCode(65 + i)}" onerror="this.src=''">
        <div class="option-card-label">方案 ${String.fromCharCode(65 + i)}</div>
      </div>
    `;
  });

  body.innerHTML = `
    <p style="color:var(--text-secondary);font-size:0.9rem;margin-bottom:1rem;">点击选择一个${label}：</p>
    <div class="options-grid">${cardsHtml}</div>
    <button class="btn-submit" id="confirm-select-btn" disabled>确认选择</button>
  `;

  let selectedIndex = null;
  const cards = body.querySelectorAll(".option-card");
  const confirmBtn = $("#confirm-select-btn");

  cards.forEach((card) => {
    card.addEventListener("click", () => {
      cards.forEach((c) => c.classList.remove("selected"));
      card.classList.add("selected");
      selectedIndex = parseInt(card.dataset.index);
      confirmBtn.disabled = false;
    });
  });

  confirmBtn.addEventListener("click", async () => {
    if (selectedIndex === null) return;
    confirmBtn.disabled = true;
    confirmBtn.textContent = "提交中...";

    try {
      const endpoint = assetType === "model"
        ? `/api/assets/model/${asset.id}/select`
        : `/api/assets/scene/${asset.id}/select`;
      const formData = new FormData();
      formData.append(assetType === "model" ? "look_index" : "scene_index", selectedIndex);
      const res = await fetch(endpoint, { method: "POST", body: formData });
      if (!res.ok) throw new Error("选择失败");
      showToast(`${label}已选择`, "success");
      closeSelectModal();
      refreshAssets();
    } catch (err) {
      showToast(`选择失败: ${err.message}`, "error");
      confirmBtn.disabled = false;
      confirmBtn.textContent = "确认选择";
    }
  });

  modal.style.display = "flex";
}

function closeSelectModal() { $("#select-modal").style.display = "none"; }
$("#select-modal-close").addEventListener("click", closeSelectModal);
$("#select-modal").addEventListener("click", (e) => { if (e.target === e.currentTarget) closeSelectModal(); });

// ========== 拖拽槽位 ==========

function setupSlot(slotType) {
  const slotBody = $(`#slot-${slotType}-body`);
  const clearBtn = $(`#slot-${slotType}-clear`);
  const fileInput = slotBody.querySelector(".slot-file-input");

  // 点击上传
  slotBody.addEventListener("click", () => {
    if (slotAssets[slotType]) return; // 已绑定素材则不触发上传
    fileInput.click();
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files.length === 0) return;
    // 临时上传 → 创建素材
    handleSlotUpload(slotType, Array.from(fileInput.files));
    fileInput.value = "";
  });

  // 拖拽接收
  slotBody.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    slotBody.classList.add("drag-over");
  });
  slotBody.addEventListener("dragleave", () => slotBody.classList.remove("drag-over"));
  slotBody.addEventListener("drop", (e) => {
    e.preventDefault();
    slotBody.classList.remove("drag-over");

    const raw = e.dataTransfer.getData("application/vlogforge-asset");
    if (!raw) return;

    try {
      const { type, id } = JSON.parse(raw);
      if (type !== slotType) {
        showToast(`类型不匹配：需要${slotType === "item" ? "物品" : slotType === "model" ? "人物" : "场景"}素材`, "warning");
        return;
      }

      // 查找素材
      const listKey = type === "item" ? "items" : type === "model" ? "models" : "scenes";
      const asset = assets[listKey].find((a) => a.id === id);
      if (!asset) { showToast("素材不存在", "error"); return; }

      // 验证状态
      if (type === "model" && !asset.selected_look) { showToast("请先选择造型", "warning"); return; }
      if (type === "scene" && !asset.selected_scene) { showToast("请先选择方案", "warning"); return; }
      if (type === "item" && asset.questionnaire_status && asset.questionnaire_status !== "completed") { showToast("请先完成产品信息确认", "warning"); return; }

      bindSlot(slotType, asset);
    } catch (err) {
      console.error("[Drop] 解析失败:", err);
    }
  });

  // 清空
  clearBtn.addEventListener("click", () => clearSlot(slotType));
}

function bindSlot(slotType, asset) {
  slotAssets[slotType] = asset;
  const slotBody = $(`#slot-${slotType}-body`);
  const clearBtn = $(`#slot-${slotType}-clear`);

  const thumbUrl = getAssetThumbUrl(asset);
  slotBody.classList.remove("slot-empty");
  slotBody.innerHTML = `
    ${thumbUrl ? `<img src="${thumbUrl}" class="slot-thumb" onerror="this.style.display='none'">` : ""}
    <div class="slot-asset-name">${escapeHtml(asset.name)}</div>
  `;
  clearBtn.style.display = "block";
  updateGenButton();
}

function clearSlot(slotType) {
  slotAssets[slotType] = null;
  const slotBody = $(`#slot-${slotType}-body`);
  const clearBtn = $(`#slot-${slotType}-clear`);
  const icons = { item: "&#128230;", model: "&#128100;", scene: "&#127968;" };

  slotBody.classList.add("slot-empty");
  slotBody.innerHTML = `
    <span class="slot-icon">${icons[slotType]}</span>
    <span class="slot-hint">拖入素材 或 点击上传</span>
    <input type="file" class="slot-file-input" accept="image/*" ${slotType === "item" ? "multiple" : ""} hidden>
  `;
  clearBtn.style.display = "none";

  // 重新绑定 file input
  const fileInput = slotBody.querySelector(".slot-file-input");
  slotBody.addEventListener("click", () => { if (!slotAssets[slotType]) fileInput.click(); });
  fileInput.addEventListener("change", () => {
    if (fileInput.files.length === 0) return;
    handleSlotUpload(slotType, Array.from(fileInput.files));
    fileInput.value = "";
  });

  updateGenButton();
}

async function handleSlotUpload(slotType, files) {
  const apiType = slotType;
  showToast(`正在创建${slotType === "item" ? "物品" : slotType === "model" ? "人物" : "场景"}...`, "info");

  const formData = new FormData();
  formData.append("description", "请根据图片分析");
  files.forEach((f) => formData.append("images", f));

  try {
    if (slotType === "item") {
      // 走问卷流程
      const res = await fetch("/api/assets/item/analyze", { method: "POST", body: formData });
      if (!res.ok) throw new Error("分析失败");
      const data = await res.json();
      if (data.status === "rejected") { showToast(data.reason, "error"); return; }
      showToast(`${data.asset.name} 分析完成`, "success");
      openQuestionnaireModal(data.asset, data.questionnaire, data.selling_points);
      refreshAssets();
    } else {
      const res = await fetch(`/api/assets/${apiType}`, { method: "POST", body: formData });
      if (!res.ok) throw new Error("创建失败");
      const data = await res.json();

      // 自动选择第一个方案
      if (slotType === "model" && data.look_options && data.look_options.length > 0) {
        const sf = new FormData(); sf.append("look_index", 0);
        await fetch(`/api/assets/model/${data.asset.id}/select`, { method: "POST", body: sf });
        data.asset.selected_look = data.look_options[0];
      }
      if (slotType === "scene" && data.scene_options && data.scene_options.length > 0) {
        const sf = new FormData(); sf.append("scene_index", 0);
        await fetch(`/api/assets/scene/${data.asset.id}/select`, { method: "POST", body: sf });
        data.asset.selected_scene = data.scene_options[0];
      }

      bindSlot(slotType, data.asset);
      showToast(`${data.asset.name} 已创建`, "success");
      refreshAssets();
    }
  } catch (err) {
    showToast(`创建失败: ${err.message}`, "error");
  }
}

// 初始化三个槽位
setupSlot("item");
setupSlot("model");
setupSlot("scene");

// ========== 生成按钮 ==========

function updateGenButton() {
  // 物品必填
  $("#btn-generate").disabled = !slotAssets.item;
}

$("#btn-generate").addEventListener("click", async () => {
  if (!slotAssets.item) return;

  const btn = $("#btn-generate");
  btn.disabled = true;
  btn.classList.add("loading");

  const platform = $("#gen-platform").value;
  const duration = $("#gen-duration").value;
  const extra = $("#gen-prompt").value.trim();

  try {
    // 如果人物/场景槽位为空，先自动创建
    if (!slotAssets.model) {
      showToast("正在自动创建人物...", "info");
      const fd = new FormData();
      fd.append("description", extra || "适合vlog带货的亲和女生");
      const res = await fetch("/api/assets/model", { method: "POST", body: fd });
      const data = await res.json();
      if (data.look_options && data.look_options.length > 0) {
        const sf = new FormData(); sf.append("look_index", 0);
        await fetch(`/api/assets/model/${data.asset.id}/select`, { method: "POST", body: sf });
      }
      slotAssets.model = data.asset;
      slotAssets.model.selected_look = data.look_options?.[0] || null;
    }

    if (!slotAssets.scene) {
      showToast("正在自动创建场景...", "info");
      const fd = new FormData();
      fd.append("description", extra || "适合vlog拍摄的室内场景");
      const res = await fetch("/api/assets/scene", { method: "POST", body: fd });
      const data = await res.json();
      if (data.scene_options && data.scene_options.length > 0) {
        const sf = new FormData(); sf.append("scene_index", 0);
        await fetch(`/api/assets/scene/${data.asset.id}/select`, { method: "POST", body: sf });
      }
      slotAssets.scene = data.asset;
      slotAssets.scene.selected_scene = data.scene_options?.[0] || null;
    }

    // 提交生成
    showToast("正在提交视频生成...", "info");
    const genForm = new FormData();
    genForm.append("item_id", slotAssets.item.id);
    genForm.append("model_id", slotAssets.model.id);
    genForm.append("scene_id", slotAssets.scene.id);
    genForm.append("platform", platform);
    genForm.append("duration", duration);
    genForm.append("extra_requirements", extra);

    const genRes = await fetch("/api/generate/v2", { method: "POST", body: genForm });
    if (!genRes.ok) { const err = await genRes.json(); throw new Error(err.detail || "生成失败"); }
    const genData = await genRes.json();

    currentJobId = genData.job_id;
    resetProgressUI();
    showView("progress");
    startSSE(currentJobId);
    showToast("视频生成任务已创建", "success");
    refreshAssets();
  } catch (err) {
    showToast(`生成失败: ${err.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.classList.remove("loading");
  }
});

// ========== 进度视图 ==========

const STAGE_ORDER = ["script", "images", "videos", "stitching"];
const STATUS_TO_STAGE = {
  pending: null, script: "script", images: "images",
  videos: "videos", stitching: "stitching",
  completed: "completed", failed: "failed",
};

function resetProgressUI() {
  $("#progress-fill").style.width = "0%";
  $("#progress-message").textContent = "准备中...";
  $("#script-preview").style.display = "none";
  $("#script-title").textContent = "";
  $("#style-guide").innerHTML = "";
  $("#segments-list").innerHTML = "";
  $("#storyboard-preview").style.display = "none";
  $("#storyboard-grid").innerHTML = "";
  $$(".pipeline-step").forEach((s) => s.classList.remove("active", "done"));
  $$(".pipeline-line").forEach((l) => l.classList.remove("done"));
}

function startSSE(jobId) {
  if (eventSource) eventSource.close();
  eventSource = new EventSource(`/api/stream/${jobId}`);
  eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    updateProgress(data);
    if (data.status === "completed" || data.status === "failed") {
      eventSource.close();
      eventSource = null;
      if (data.status === "completed" && data.final_video_url) showResult(data);
      else if (data.status === "failed") showToast(`生成失败: ${data.message || "未知错误"}`, "error");
    }
  };
  eventSource.onerror = () => { eventSource.close(); eventSource = null; startPolling(jobId); };
}

function startPolling(jobId) {
  const interval = setInterval(async () => {
    try {
      const res = await fetch(`/api/status/${jobId}`);
      const data = await res.json();
      updateProgress(data);
      if (data.status === "completed" || data.status === "failed") {
        clearInterval(interval);
        if (data.status === "completed" && data.final_video_url) showResult(data);
        else if (data.status === "failed") showToast(`生成失败: ${data.message || "未知错误"}`, "error");
      }
    } catch { /* 继续轮询 */ }
  }, 2000);
}

function updateProgress(data) {
  const pct = Math.round((data.progress || 0) * 100);
  $("#progress-fill").style.width = `${pct}%`;
  $("#progress-message").textContent = data.message || "";

  const stage = STATUS_TO_STAGE[data.status];
  if (stage && stage !== "completed" && stage !== "failed") updatePipelineStage(stage);
  if (data.status === "completed") STAGE_ORDER.forEach((s) => markStageDone(s));

  if (data.script && $("#script-preview").style.display === "none") {
    currentScript = data.script;
    renderScript(data.script);
  }
  if (data.storyboard_urls && data.storyboard_urls.length > 0) renderStoryboard(data.storyboard_urls);
}

function updatePipelineStage(stage) {
  const idx = STAGE_ORDER.indexOf(stage);
  if (idx === -1) return;
  $$(".pipeline-step").forEach((s, i) => {
    if (i < idx) { s.classList.remove("active"); s.classList.add("done"); }
    else if (i === idx) { s.classList.remove("done"); s.classList.add("active"); }
    else s.classList.remove("active", "done");
  });
  $$(".pipeline-line").forEach((l, i) => { if (i < idx) l.classList.add("done"); else l.classList.remove("done"); });
}

function markStageDone(stage) {
  const step = $(`.pipeline-step[data-stage="${stage}"]`);
  if (step) { step.classList.remove("active"); step.classList.add("done"); }
}

// ========== 渲染脚本 ==========

function renderScript(script) {
  $("#script-preview").style.display = "block";
  $("#script-title").textContent = `\u300C${script.title}\u300D`;
  const guide = script.style_guide;
  $("#style-guide").innerHTML = `
    <div class="style-guide-item"><div class="label">人物</div><div class="value">${escapeHtml(guide.person_description)}</div></div>
    <div class="style-guide-item"><div class="label">场景</div><div class="value">${escapeHtml(guide.scene_description)}</div></div>
    <div class="style-guide-item"><div class="label">风格</div><div class="value">${escapeHtml(guide.visual_style)}</div></div>
    <div class="style-guide-item"><div class="label">光线</div><div class="value">${escapeHtml(guide.lighting)}</div></div>
  `;
  const list = $("#segments-list");
  list.innerHTML = "";
  script.segments.forEach((seg) => {
    const el = document.createElement("div");
    el.className = `segment-item${seg.needs_product ? " has-product" : ""}`;
    el.innerHTML = `
      <div class="segment-header">
        <span class="segment-number">分段 ${seg.segment_id}</span>
        ${seg.needs_product ? '<span class="segment-badge">产品植入</span>' : ""}
      </div>
      <div class="segment-narration">${escapeHtml(seg.narration)}</div>
      <div class="segment-action">${escapeHtml(seg.action_description)}</div>
    `;
    list.appendChild(el);
  });
}

function renderStoryboard(urls) {
  $("#storyboard-preview").style.display = "block";
  const grid = $("#storyboard-grid");
  grid.innerHTML = "";
  urls.forEach((url, i) => {
    const img = document.createElement("img");
    img.src = url; img.alt = `帧 ${i + 1}`; img.loading = "lazy";
    grid.appendChild(img);
  });
}

// ========== 结果视图 ==========

function showResult(data) {
  $("#result-video").src = data.final_video_url;
  $("#btn-download").href = data.final_video_url;
  const script = data.script || currentScript;
  if (script) {
    $("#result-title").textContent = `\u300C${script.title}\u300D`;
    const segs = $("#result-segments");
    segs.innerHTML = "";
    script.segments.forEach((seg) => {
      const el = document.createElement("div");
      el.className = `segment-item${seg.needs_product ? " has-product" : ""}`;
      el.innerHTML = `
        <div class="segment-header">
          <span class="segment-number">分段 ${seg.segment_id}</span>
          ${seg.needs_product ? '<span class="segment-badge">产品植入</span>' : ""}
        </div>
        <div class="segment-narration">${escapeHtml(seg.narration)}</div>
      `;
      segs.appendChild(el);
    });
  }
  showView("result");
}

// ========== 返回 / 新建 ==========

$("#btn-back").addEventListener("click", () => {
  if (eventSource) { eventSource.close(); eventSource = null; }
  showView("home");
  refreshAssets();
});

$("#btn-new-task").addEventListener("click", () => {
  currentJobId = null;
  currentScript = null;
  slotAssets = { item: null, model: null, scene: null };
  clearSlot("item");
  clearSlot("model");
  clearSlot("scene");
  showView("home");
  refreshAssets();
});

// ========== 初始化 ==========
document.addEventListener("DOMContentLoaded", () => { refreshAssets(); });
