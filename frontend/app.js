/**
 * VlogForge 前端交互逻辑 (v12)
 * 统一主页：素材库两列（物品+人物） + 生成区拖拽槽位
 * 智能问卷：物品创建走 analyze → 问卷确认 → confirm
 * 素材详情：点击卡片展开详情面板
 * v12: 删除前端假占位卡片，改为基于后端 status 渲染素材卡片
 *      generating 状态显示骨架动画，pending/confirmed 显示缩略图
 *      generating 状态自动轮询（每5秒）直到全部完成
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

// ========== 图片预览 Lightbox ==========
function initLightbox() {
  const overlay = $("#image-lightbox");
  if (!overlay) return;
  const img = overlay.querySelector(".lightbox-img");
  const closeBtn = overlay.querySelector(".lightbox-close");

  // 关闭
  function closeLightbox() { overlay.style.display = "none"; }
  closeBtn.addEventListener("click", closeLightbox);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) closeLightbox(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && overlay.style.display !== "none") closeLightbox(); });

  // 全局委托：点击 .asset-mini-thumb / .detail-image-item img / .model-review-image img 打开预览
  document.addEventListener("click", (e) => {
    const target = e.target;
    if (
      (target.matches(".asset-mini-thumb") ||
       target.matches(".detail-image-item img") ||
       target.matches(".model-review-image img")) &&
      target.src
    ) {
      e.stopPropagation();
      img.src = target.src;
      overlay.style.display = "flex";
    }
  });
}

// ========== 状态 ==========
let assets = { items: [], models: [] };
let currentJobId = null;
let eventSource = null;
let currentScript = null;

// 生成区槽位绑定的素材
let slotAssets = { item: null, model: null };

// v12: generating 状态轮询定时器（后端驱动状态，无需前端占位卡片）
let generatingPollTimer = null;

// ========== 渲染队列状态 ==========
let queuePollTimer = null;        // 队列轮询定时器
let queueCollapsed = false;       // 队列面板是否折叠
let queueJobs = [];               // 缓存当前任务列表
let queueApiAvailable = null;     // 标记 /api/jobs 接口是否可用（null=未知, true/false）

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
    if (!res.ok) throw new Error(t('asset.loadFailed'));
    const data = await res.json();
    assets.items = data.items || [];
    assets.models = data.models || [];

    $("#count-items").textContent = assets.items.length;
    $("#count-models").textContent = assets.models.length;

    renderColumnList("items", assets.items, "#col-items");
    renderColumnList("models", assets.models, "#col-models");

    // v12: 检查是否需要启动/停止 generating 轮询
    startGeneratingPollIfNeeded();
  } catch (err) {
    console.error("[Assets] 加载失败:", err);
  }
}

// v12: 渲染素材列表，所有卡片（含 generating 状态）均由后端数据驱动
function renderColumnList(type, list, containerSel) {
  const container = $(containerSel);
  container.innerHTML = "";

  if (list.length === 0) {
    container.innerHTML = `<div style="text-align:center;color:var(--text-muted);font-size:0.8rem;padding:1rem 0;">${t('asset.noAssets')}</div>`;
    return;
  }

  list.forEach((asset) => {
    const card = createMiniCard(type, asset);
    container.appendChild(card);
  });
}

// ========== v12: generating 状态轮询 ==========

/**
 * 检查是否有 generating 状态的素材，如果有则启动轮询
 * 每 5 秒刷新一次素材列表，直到没有 generating 状态的素材为止
 */
function startGeneratingPollIfNeeded() {
  const hasGenerating = [...assets.items, ...assets.models].some(a => a.status === "generating");
  if (hasGenerating && !generatingPollTimer) {
    console.log("[Poll] 检测到 generating 状态素材，启动轮询");
    generatingPollTimer = setInterval(async () => {
      await refreshAssets();
      const stillGenerating = [...assets.items, ...assets.models].some(a => a.status === "generating");
      if (!stillGenerating) {
        console.log("[Poll] 所有素材已完成生成，停止轮询");
        clearInterval(generatingPollTimer);
        generatingPollTimer = null;
      }
    }, 5000);
  } else if (!hasGenerating && generatingPollTimer) {
    // 没有 generating 素材但定时器还在运行，清理之
    clearInterval(generatingPollTimer);
    generatingPollTimer = null;
  }
}

function getAssetThumbUrl(asset) {
  // v10: 优先使用新字段（人物用 portrait_image）
  const imgPath =
    asset.thumbnail_image || asset.portrait_image ||
    asset.avatar_image || asset.selected_look ||
    asset.instruction_image;
  if (!imgPath) return null;
  const filename = imgPath.split("/").pop();
  return `/assets/${asset.id}/${filename}`;
}

function getAssetImageUrl(asset, field) {
  const imgPath = asset[field];
  if (!imgPath) return null;
  const filename = imgPath.split("/").pop();
  return `/assets/${asset.id}/${filename}`;
}

// v12: 根据 asset.status 渲染不同 UI（generating / pending / confirmed）
function createMiniCard(type, asset) {
  const card = document.createElement("div");
  const slotType = type === "items" ? "item" : "model";
  const isGenerating = asset.status === "generating";
  const isConfirmed = asset.status === "confirmed";

  // generating 状态：骨架卡片 + spinner，复用现有 CSS .generating 样式
  if (isGenerating) {
    card.className = "asset-mini-card generating";
    card.innerHTML = `
      <div class="asset-generating-bar"><div class="asset-generating-bar-fill"></div></div>
      <div class="asset-mini-card-inner">
        <div class="asset-mini-thumb-skeleton"></div>
        <div class="asset-mini-info">
          <div class="asset-mini-name">${escapeHtml(asset.name || t('asset.generatingName'))}</div>
          <div class="asset-mini-meta" style="color:#3b82f6;">${t('asset.generating')}</div>
        </div>
      </div>
      <div class="asset-generating-progress">
        <span class="gen-spinner"></span>
        <span class="gen-progress-text">${t('asset.generating')}</span>
      </div>
    `;
    return card;
  }

  // v16: failed 状态：显示错误信息 + 重试/删除按钮
  if (asset.status === "failed") {
    card.className = "asset-mini-card failed";
    // 根据后端返回的错误类型 key 映射 i18n 翻译
    let errorMsg = t('asset.genFailed') || "生成失败";
    if (asset.error_message === "safety_filtered") {
      errorMsg = t('asset.safetyFiltered');
    } else if (asset.error_message === "rate_limited") {
      errorMsg = t('asset.rateLimited');
    } else if (asset.error_message === "quota_exhausted") {
      errorMsg = t('asset.quotaExhausted');
    } else if (asset.error_message && asset.error_message.startsWith("error:")) {
      errorMsg = asset.error_message.slice(6);
    }
    card.innerHTML = `
      <div class="asset-mini-card-inner">
        <div class="asset-failed-icon">&#9888;</div>
        <div class="asset-mini-info">
          <div class="asset-mini-name">${escapeHtml(asset.name || t('asset.unknownAsset') || "未知素材")}</div>
          <div class="asset-failed-error">${escapeHtml(errorMsg)}</div>
        </div>
      </div>
      <div class="asset-mini-actions">
        ${type === "models" ? `<button class="btn-retry" data-edit="${asset.id}">${t('asset.retry') || "重新生成"}</button>` : ""}
        <button class="btn-sm btn-danger" data-delete="${asset.id}">${t('asset.delete') || "删除"}</button>
      </div>
    `;
    // 绑定重试按钮
    const retryBtn = card.querySelector("[data-edit]");
    if (retryBtn) {
      retryBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        openModelReviewModal(asset);
      });
    }
    // 绑定删除按钮
    card.querySelector("[data-delete]").addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm(t('asset.confirmDelete', {name: asset.name}) || `确认删除 ${asset.name}？`)) return;
      try {
        const res = await fetch(`/api/assets/${asset.id}`, { method: "DELETE" });
        if (!res.ok) throw new Error(t('asset.deleteFailed'));
        showToast(t('asset.deleted', {name: asset.name}), "success");
        refreshAssets();
      } catch (err) {
        showToast(err.message, "error");
      }
    });
    return card;
  }

  // pending / confirmed 状态：正常渲染缩略图 + 操作按钮
  card.className = "asset-mini-card";

  // v7: 只有已确认的素材可拖拽
  card.draggable = isConfirmed;
  if (isConfirmed) {
    card.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("application/vlogforge-asset", JSON.stringify({ type: slotType, id: asset.id }));
      e.dataTransfer.effectAllowed = "copy";
      card.classList.add("dragging");
    });
    card.addEventListener("dragend", () => card.classList.remove("dragging"));
  }

  // 缩略图
  const thumbUrl = getAssetThumbUrl(asset);
  let thumbHtml = "";
  if (thumbUrl) {
    thumbHtml = `<img class="asset-mini-thumb" src="${thumbUrl}" alt="${escapeHtml(asset.name)}" onerror="this.style.display='none'">`;
  } else {
    const icons = { items: "&#128230;", models: "&#128100;" };
    thumbHtml = `<div class="asset-mini-thumb-placeholder">${icons[type]}</div>`;
  }

  // 元数据
  let meta = "";
  if (type === "items") meta = asset.selling_point || asset.category || "";
  else if (type === "models") meta = asset.scene_context || asset.personality || "";

  // v12: 状态标签（generating 已提前 return，这里只有 pending / confirmed）
  let badge = "";
  if (isConfirmed) {
    badge = `<span class="asset-mini-badge success">${t('asset.confirmed')}</span>`;
  } else {
    badge = `<span class="asset-mini-badge warning">${t('asset.pending')}</span>`;
  }

  // v7: 按钮根据状态不同
  let actionBtns = "";
  if (isConfirmed) {
    actionBtns = `
      <button class="btn-sm btn-detail" data-detail="${asset.id}">${t('asset.detail')}</button>
      <button class="btn-sm btn-danger" data-delete="${asset.id}">${t('asset.delete')}</button>
    `;
  } else {
    actionBtns = `
      <button class="btn-sm btn-edit" data-edit="${asset.id}">${t('asset.edit')}</button>
      <button class="btn-sm btn-danger" data-delete="${asset.id}">${t('asset.delete')}</button>
    `;
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
      ${actionBtns}
    </div>
  `;

  // v7: 点击详情（已确认状态）
  const detailBtn = card.querySelector("[data-detail]");
  if (detailBtn) {
    detailBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      openDetailModal(type, asset);
    });
  }

  // v7: 点击编辑（物品 → 问卷，人物 → 方案选择）
  const editBtn = card.querySelector("[data-edit]");
  if (editBtn) {
    editBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (type === "items" && asset.questionnaire_fields && asset.questionnaire_fields.length > 0) {
        openQuestionnaireModal(asset);
      } else if (type === "models" && (asset.status === "pending" || asset.status === "failed" || asset.status === "confirmed")) {
        openModelReviewModal(asset);
      } else if (type === "models" && asset.status === "generating") {
        showToast(t('asset.generating') || "生成中，请稍候...", "info");
      } else {
        showToast(t('asset.editNotSupported'), "warning");
      }
    });
  }

  // 点击删除
  card.querySelector("[data-delete]").addEventListener("click", async (e) => {
    e.stopPropagation();
    if (!confirm(t('asset.confirmDelete', {name: asset.name}))) return;
    try {
      const res = await fetch(`/api/assets/${asset.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(t('asset.deleteFailed'));
      showToast(t('asset.deleted', {name: asset.name}), "success");
      if (slotAssets[slotType] && slotAssets[slotType].id === asset.id) clearSlot(slotType);
      refreshAssets();
    } catch (err) {
      showToast(t('asset.deleteFailedWith', {error: err.message}), "error");
    }
  });

  return card;
}

// ========== 素材详情模态框 ==========

// v7: tag 标签渲染（将文本拆分成 tag，支持逗号/顿号分隔）
function textToTags(text) {
  if (!text) return [];
  return text.split(/[,，、；;]+/).map(s => s.trim()).filter(Boolean);
}

function renderTagSection(sectionId, label, text, assetId, fieldKey) {
  const tags = textToTags(text);
  const tagsHtml = tags.map(t => `<span class="detail-tag">${escapeHtml(t)}</span>`).join("");
  return `
    <div class="detail-tag-section" data-section="${sectionId}">
      <div class="detail-tag-header">
        <span class="detail-tag-label">${escapeHtml(label)}</span>
        <button class="btn-sm btn-tag-edit" data-asset="${assetId}" data-field="${fieldKey}" data-section="${sectionId}">${t('detail.editBtn')}</button>
      </div>
      <div class="detail-tag-body">${tagsHtml || '<span class="detail-tag-empty">' + t('detail.empty') + '</span>'}</div>
    </div>
  `;
}

function renderImagesRow(asset, fields) {
  let html = '<div class="detail-images-row">';
  for (const { field, label } of fields) {
    const url = getAssetImageUrl(asset, field);
    if (url) {
      html += `<div class="detail-image-item"><img src="${url}" alt="${label}" onerror="this.parentElement.style.display='none'"><div class="detail-image-label">${escapeHtml(label)}</div></div>`;
    }
  }
  html += '</div>';
  return html;
}

function openDetailModal(type, asset) {
  const modal = $("#detail-modal");
  const title = $("#detail-modal-title");
  const body = $("#detail-modal-body");

  const detailTitleKey = type === "items" ? 'modal.itemDetail' : 'modal.modelDetail';
  title.textContent = t(detailTitleKey, {name: asset.name});

  let content = "";

  if (type === "items") {
    // v7: 三张产品图
    content += renderImagesRow(asset, [
      { field: "thumbnail_image", label: t('detail.thumbnail') },
      { field: "three_view_image", label: t('detail.threeView') },
    ]);

    // v7: tag 分区展示 + 编辑
    const pi = asset.product_info || {};
    for (const [key, value] of Object.entries(pi)) {
      if (value) content += renderTagSection(`item-${key}`, key, value, asset.id, `product_info.${key}`);
    }

    // 卖点
    const sp = asset.selling_points || {};
    if (sp.P0 && sp.P0.length) content += renderTagSection("sp-p0", t('detail.p0SellingPoint'), sp.P0.join("、"), asset.id, "selling_points.P0");
    if (sp.P1 && sp.P1.length) content += renderTagSection("sp-p1", t('detail.p1SellingPoint'), sp.P1.join("、"), asset.id, "selling_points.P1");

    content += `<div class="detail-section"><h4>${t('detail.fullDescription')}</h4><p class="detail-desc">${escapeHtml(asset.full_description)}</p></div>`;

  } else if (type === "models") {
    // v10: 一张大图（portrait_image，人在场景中的半身近景照）
    content += renderImagesRow(asset, [
      { field: "portrait_image", label: t('detail.portrait') },
    ]);

    content += renderTagSection("model-language", t('detail.language'), asset.language, asset.id, "language");
    content += renderTagSection("model-appearance", t('detail.appearance'), asset.appearance, asset.id, "appearance");
    content += renderTagSection("model-personality", t('detail.personality'), asset.personality, asset.id, "personality");
    content += renderTagSection("model-outfits", t('detail.outfits'), asset.outfits, asset.id, "outfits");
    content += renderTagSection("model-scene", t('detail.scene'), asset.scene_context, asset.id, "scene_context");

    content += `<div class="detail-section"><h4>${t('detail.fullDescription')}</h4><p class="detail-desc">${escapeHtml(asset.full_description)}</p></div>`;
  }

  body.innerHTML = content;
  modal.style.display = "flex";

  // v7: 绑定分区编辑按钮
  body.querySelectorAll(".btn-tag-edit").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const section = btn.closest(".detail-tag-section");
      const tagBody = section.querySelector(".detail-tag-body");
      const fieldPath = btn.dataset.field;
      const assetId = btn.dataset.asset;

      if (btn.textContent === t('detail.editBtn')) {
        // 进入编辑模式
        btn.textContent = t('detail.confirmBtn');
        btn.classList.add("btn-confirm");
        const currentTags = [...tagBody.querySelectorAll(".detail-tag")].map(t => t.textContent);
        tagBody.innerHTML = "";
        currentTags.forEach(t => {
          tagBody.appendChild(createEditableTag(t));
        });
        // 添加「+」按钮
        const addBtn = document.createElement("button");
        addBtn.className = "detail-tag-add";
        addBtn.textContent = "+";
        addBtn.addEventListener("click", () => {
          const newTag = createEditableTag("");
          tagBody.insertBefore(newTag, addBtn);
          newTag.querySelector("input").focus();
        });
        tagBody.appendChild(addBtn);
      } else {
        // 确认保存
        btn.textContent = t('detail.editBtn');
        btn.classList.remove("btn-confirm");
        const inputs = tagBody.querySelectorAll(".detail-tag-input");
        const newValues = [...inputs].map(i => i.value.trim()).filter(Boolean);
        const newText = newValues.join("、");

        // 更新显示
        tagBody.innerHTML = newValues.length > 0
          ? newValues.map(v => `<span class="detail-tag">${escapeHtml(v)}</span>`).join("")
          : '<span class="detail-tag-empty">' + t('detail.empty') + '</span>';

        // 保存到后端
        saveTagUpdate(assetId, fieldPath, newText);
      }
    });
  });
}

function createEditableTag(text) {
  const wrapper = document.createElement("span");
  wrapper.className = "detail-tag editing";
  const input = document.createElement("input");
  input.type = "text";
  input.className = "detail-tag-input";
  input.value = text;
  input.size = Math.max(text.length + 2, 4);
  input.addEventListener("input", () => { input.size = Math.max(input.value.length + 2, 4); });
  wrapper.appendChild(input);
  const delBtn = document.createElement("span");
  delBtn.className = "detail-tag-del";
  delBtn.textContent = "×";
  delBtn.addEventListener("click", () => wrapper.remove());
  wrapper.appendChild(delBtn);
  return wrapper;
}

async function saveTagUpdate(assetId, fieldPath, newValue) {
  // fieldPath 可以是 "appearance" 或 "product_info.selling_point" 或 "selling_points.P0"
  let updates = {};
  if (fieldPath.includes(".")) {
    const [parent, child] = fieldPath.split(".", 2);
    // 需要获取当前完整对象再局部更新
    try {
      const res = await fetch(`/api/assets/${assetId}`);
      const data = await res.json();
      const parentObj = data.asset[parent] || {};
      if (parent === "selling_points") {
        parentObj[child] = newValue.split(/[,，、]+/).map(s => s.trim()).filter(Boolean);
      } else {
        parentObj[child] = newValue;
      }
      updates[parent] = parentObj;
    } catch (err) {
      showToast(t('detail.saveFailed', {error: err.message}), "error");
      return;
    }
  } else {
    updates[fieldPath] = newValue;
  }

  try {
    const formData = new FormData();
    formData.append("updates", JSON.stringify(updates));
    const res = await fetch(`/api/assets/${assetId}`, { method: "PUT", body: formData });
    if (!res.ok) throw new Error(t('detail.saveFailed', {error: ''}));
    showToast(t('detail.saved'), "success");
    refreshAssets();
  } catch (err) {
    showToast(t('detail.saveFailed', {error: err.message}), "error");
  }
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
  const createTitleKey = type === "items" ? 'modal.createItem' : 'modal.createModel';
  title.textContent = t(createTitleKey);

  const placeholders = {
    items: t('form.itemPlaceholder'),
    models: t('form.modelPlaceholder'),
  };

  body.innerHTML = `
    <form id="create-asset-form">
      <div class="form-group">
        <label>${t('form.description')}</label>
        <textarea id="create-desc" rows="3" placeholder="${placeholders[type]}" required></textarea>
      </div>
      <div class="form-group">
        <label>${t('form.referenceImages')}</label>
        <div class="upload-zone" id="create-upload-zone">
          <input type="file" id="create-file-input" accept="image/*" multiple hidden>
          <div class="upload-placeholder" id="create-upload-placeholder">
            <span class="upload-icon">&#128247;</span>
            <span>${t('form.uploadRef')}</span>
          </div>
          <div class="upload-preview-sm" id="create-upload-preview"></div>
        </div>
      </div>
      <button type="submit" class="btn-submit" id="create-submit-btn">${type === "items" ? t('create.createItem') : t('create.createModel')}</button>
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
    submitBtn.textContent = t('button.creating');

    const desc = $("#create-desc").value.trim();

    if (type === "items") {
      // 物品走智能问卷流程
      await handleItemCreate(desc, createFiles, submitBtn, type);
    } else {
      // v12: 人物 → 关闭模态框，发送请求，通过 refreshAssets 渲染 generating 卡片
      const formData = new FormData();
      formData.append("description", desc);
      createFiles.forEach((f) => formData.append("images", f));

      closeCreateModal();
      showToast(t('toast.modelCreating'), "info");

      try {
        const res = await fetch("/api/assets/model", { method: "POST", body: formData });
        if (!res.ok) { const err = await res.json(); throw new Error(err.detail || t('toast.createFailed', {error: ''})); }
        const data = await res.json();

        console.log(`[ModelCreate] 成功: ${data.asset.name}`);
        // 刷新列表，后端已保存 generating/pending 状态的素材
        await refreshAssets();
        showToast(t('toast.modelCreateSuccess', {name: data.asset.name}), "success");

        // v15: 后端自动设置 portrait_image，pending 状态时用户通过审核弹窗确认
        if (data.asset && data.asset.status === "pending") {
          openModelReviewModal(data.asset);
        }
      } catch (err) {
        showToast(t('toast.createFailed', {error: err.message}), "error");
        await refreshAssets();
      }
    }
  });

  modal.style.display = "flex";
}

// 物品创建 → 走智能问卷
async function handleItemCreate(desc, files, submitBtn, type) {
  const formData = new FormData();
  formData.append("description", desc);
  files.forEach((f) => formData.append("images", f));

  try {
    // 第 1 步：analyze
    const res = await fetch("/api/assets/item/analyze", { method: "POST", body: formData });
    if (!res.ok) { const err = await res.json(); throw new Error(err.detail || t('toast.itemAnalyzeFailed', {error: ''})); }
    const data = await res.json();

    if (data.status === "rejected") {
      showToast(t('toast.itemRejected', {reason: data.reason}), "error");
      closeCreateModal();
      return;
    }

    showToast(t('toast.itemAnalyzed', {name: data.asset.name}), "success");
    closeCreateModal();

    // 打开问卷确认
    openQuestionnaireModal(data.asset, data.questionnaire, data.selling_points);
    refreshAssets();
  } catch (err) {
    showToast(t('toast.itemAnalyzeFailed', {error: err.message}), "error");
    submitBtn.disabled = false;
    submitBtn.textContent = type === "items" ? t('create.createItem') : t('create.createModel');
  }
}

function closeCreateModal() { $("#create-modal").style.display = "none"; }
$("#modal-close").addEventListener("click", closeCreateModal);
$("#create-modal").addEventListener("click", (e) => { if (e.target === e.currentTarget) closeCreateModal(); });

// ========== 智能问卷模态框（v7：逐题 A/B/C 选择式） ==========

function openQuestionnaireModal(asset, questionnaire, sellingPoints) {
  const modal = $("#questionnaire-modal");
  const title = $("#questionnaire-title");
  const body = $("#questionnaire-body");

  // 使用传入的问卷，或从 asset 中取
  const questions = questionnaire || asset.questionnaire_fields || [];
  if (questions.length === 0) {
    showToast(t('questionnaire.noQuestions'), "warning");
    return;
  }

  title.textContent = t('modal.productInfoConfirmWith', {name: asset.name});

  // 存储用户的回答
  const answers = questions.map(q => ({
    key: q.key,
    label: q.label,
    value: q.value || "",
    priority: q.priority,
    source: q.value ? "ai" : "user",
  }));

  let currentIndex = 0;

  // 生成进度点 HTML
  function renderDots(index, total) {
    let dots = '';
    for (let i = 0; i < total; i++) {
      const cls = i < index ? 'done' : i === index ? 'active' : '';
      dots += `<div class="q-dot ${cls}"></div>`;
    }
    return dots;
  }

  function renderQuestion(index) {
    const q = questions[index];
    const total = questions.length;
    const priorityClass = `priority-${q.priority.toLowerCase()}`;
    const isOptional = !q.required;
    const currentAnswer = answers[index].value;

    // 判断当前选中的是哪个选项
    let selectedOption = "";
    if (currentAnswer === q.option_a && q.option_a) selectedOption = "a";
    else if (currentAnswer === q.option_b && q.option_b) selectedOption = "b";
    else if (currentAnswer && currentAnswer !== q.option_a && currentAnswer !== q.option_b) selectedOption = "c";

    body.innerHTML = `
      <div class="q-container">
        <div class="q-stepper">
          ${total <= 15 ? `<div class="q-stepper-dots">${renderDots(index, total)}</div>` : ''}
          <div class="q-stepper-bar">
            <div class="q-stepper-fill" style="width: ${((index + 1) / total) * 100}%"></div>
          </div>
          <div class="q-stepper-meta">
            <span class="q-stepper-label">${t('questionnaire.levelQuestion', {priority: q.priority})}</span>
            <span class="q-stepper-counter">${t('questionnaire.counter', {current: index + 1, total: total})}</span>
          </div>
        </div>

        <div class="q-card ${priorityClass}">
          <div class="q-card-header">
            <span class="q-priority-badge">${q.priority}</span>
            ${isOptional
              ? '<span class="q-optional-badge">' + t('questionnaire.canSkip') + '</span>'
              : '<span class="q-required-badge">' + t('questionnaire.required') + '</span>'}
          </div>
          <h3 class="q-card-question">${escapeHtml(q.label)}</h3>

          <div class="q-options">
            ${q.option_a ? `
            <div class="q-option ${selectedOption === 'a' ? 'selected' : ''}" data-choice="a">
              <div class="q-option-label">A</div>
              <div class="q-option-text">${escapeHtml(q.option_a)}</div>
            </div>` : ''}

            ${q.option_b ? `
            <div class="q-option ${selectedOption === 'b' ? 'selected' : ''}" data-choice="b">
              <div class="q-option-label">B</div>
              <div class="q-option-text">${escapeHtml(q.option_b)}</div>
            </div>` : ''}

            <div class="q-option q-option-custom ${selectedOption === 'c' ? 'selected' : ''}" data-choice="c">
              <div class="q-option-label">C</div>
              <div class="q-option-text">${t('questionnaire.customAnswer')}</div>
            </div>
          </div>

          <div class="q-custom-input-wrap" id="q-custom-wrap" style="display:${selectedOption === 'c' ? 'block' : 'none'}">
            <textarea class="q-custom-input" id="q-custom-input" rows="2"
              placeholder="${t('questionnaire.customPlaceholder')}">${selectedOption === 'c' ? escapeHtml(currentAnswer) : ''}</textarea>
          </div>
        </div>

        <div class="q-nav">
          <button class="q-nav-btn q-nav-prev" id="q-prev" ${index === 0 ? 'disabled' : ''}>&#8592; ${t('questionnaire.prevQuestion')}</button>
          <div class="q-nav-center">
            ${isOptional ? '<button class="q-nav-btn q-nav-skip" id="q-skip">' + t('questionnaire.skip') + '</button>' : ''}
          </div>
          ${index < total - 1
            ? '<button class="q-nav-btn q-nav-next" id="q-next">' + t('questionnaire.nextQuestion') + ' &#8594;</button>'
            : '<button class="q-nav-btn q-nav-submit" id="q-submit">' + t('questionnaire.submitAndCreate') + '</button>'
          }
        </div>
      </div>
    `;

    // 绑定选项点击
    body.querySelectorAll(".q-option").forEach(opt => {
      opt.addEventListener("click", () => {
        body.querySelectorAll(".q-option").forEach(o => o.classList.remove("selected"));
        opt.classList.add("selected");
        const choice = opt.dataset.choice;
        const customWrap = $("#q-custom-wrap");

        if (choice === "a") {
          answers[index].value = q.option_a;
          answers[index].source = "ai";
          customWrap.style.display = "none";
        } else if (choice === "b") {
          answers[index].value = q.option_b;
          answers[index].source = "ai";
          customWrap.style.display = "none";
        } else {
          customWrap.style.display = "block";
          const input = $("#q-custom-input");
          input.focus();
          if (answers[index].source === "ai") input.value = "";
          answers[index].source = "user";
        }
      });
    });

    // 上一题
    const prevBtn = $("#q-prev");
    if (prevBtn) prevBtn.addEventListener("click", () => { saveCurrentAnswer(); currentIndex--; renderQuestion(currentIndex); });

    // 下一题
    const nextBtn = $("#q-next");
    if (nextBtn) nextBtn.addEventListener("click", () => {
      if (!validateCurrent()) return;
      saveCurrentAnswer();
      currentIndex++;
      renderQuestion(currentIndex);
    });

    // 跳过（P2 可选题）
    const skipBtn = $("#q-skip");
    if (skipBtn) skipBtn.addEventListener("click", () => {
      answers[index].value = "";
      answers[index].source = "skipped";
      currentIndex++;
      if (currentIndex < total) renderQuestion(currentIndex);
      else submitQuestionnaire();
    });

    // 最后一题提交
    const submitBtn = $("#q-submit");
    if (submitBtn) submitBtn.addEventListener("click", () => {
      if (!validateCurrent()) return;
      saveCurrentAnswer();
      submitQuestionnaire();
    });
  }

  function saveCurrentAnswer() {
    const customInput = $("#q-custom-input");
    if (customInput && answers[currentIndex].source === "user") {
      answers[currentIndex].value = customInput.value.trim();
    }
  }

  function validateCurrent() {
    const q = questions[currentIndex];
    saveCurrentAnswer();
    if (q.required && !answers[currentIndex].value) {
      showToast(t('questionnaire.selectOrWrite'), "warning");
      return false;
    }
    if (answers[currentIndex].source === "user" && q.required && !answers[currentIndex].value) {
      showToast(t('questionnaire.writeYourAnswer'), "warning");
      return false;
    }
    return true;
  }

  async function submitQuestionnaire() {
    const confirmed = answers.filter(a => a.source !== "skipped").map(a => ({
      key: a.key,
      label: a.label,
      value: a.value,
      priority: a.priority,
      source: a.source,
    }));

    // 检查必填项
    for (const q of questions) {
      if (q.required) {
        const ans = confirmed.find(a => a.key === q.key);
        if (!ans || !ans.value) {
          showToast(t('questionnaire.answerRequired', {label: q.label}), "error");
          return;
        }
      }
    }

    // v12: 关闭问卷模态框，发送确认请求，通过 refreshAssets 渲染 generating 卡片
    modal.style.display = "none";
    showToast(t('toast.itemConfirming'), "info");

    // 立即刷新一次，显示后端刚创建的 generating 状态卡片
    await refreshAssets();

    try {
      const formData = new FormData();
      formData.append("confirmed_fields", JSON.stringify(confirmed));

      const res = await fetch(`/api/assets/item/${asset.id}/confirm`, { method: "POST", body: formData });
      if (!res.ok) { const err = await res.json(); throw new Error(err.detail || t('toast.itemConfirmFailed', {error: ''})); }

      const data = await res.json();
      console.log(`[ItemConfirm] 成功: ${data.asset.name}`);
      // 刷新列表获取 confirmed 状态
      await refreshAssets();
      showToast(t('toast.itemConfirmSuccess', {name: data.asset.name || t('asset.items')}), "success");
    } catch (err) {
      showToast(t('toast.itemConfirmFailed', {error: err.message}), "error");
      await refreshAssets();
    }
  }

  // 渲染第一题
  renderQuestion(0);
  modal.style.display = "flex";
}

$("#questionnaire-close").addEventListener("click", () => { $("#questionnaire-modal").style.display = "none"; });
$("#questionnaire-modal").addEventListener("click", (e) => { if (e.target === e.currentTarget) $("#questionnaire-modal").style.display = "none"; });

// ========== 人物造型审核弹窗（v15） ==========

/**
 * 打开人物造型审核弹窗（单图审核模式）
 * - 展示 portrait_image 大图
 * - 确认 / 重新生成 / 输入调整意见
 */
function openModelReviewModal(asset) {
  // 移除已有弹窗（如果存在）
  let overlay = $(".model-review-overlay");
  if (overlay) overlay.remove();

  // 获取图片 URL
  const imgPath = asset.portrait_image;
  const imgUrl = imgPath ? `/assets/${asset.id}/${imgPath.split("/").pop()}` : "";

  // 创建弹窗 DOM
  overlay = document.createElement("div");
  overlay.className = "modal-overlay model-review-overlay";
  overlay.innerHTML = `
    <div class="modal model-review-modal">
      <div class="modal-header">
        <h2>${t('modal.modelReview', {name: escapeHtml(asset.name)})}</h2>
        <button class="modal-close model-review-close">&times;</button>
      </div>
      <div class="model-review-image">
        ${imgUrl
          ? `<img src="${imgUrl}" alt="${escapeHtml(asset.name)}" />`
          : `<div class="model-review-placeholder">${t('modal.noLookImage')}</div>`
        }
      </div>
      <div class="model-review-actions">
        <button class="btn-submit model-review-confirm">${t('modelReview.confirmBtn')}</button>
        <button class="btn-submit model-review-regenerate" style="background:rgba(255,255,255,0.08);color:var(--text-primary);">${t('modelReview.regenerateBtn')}</button>
      </div>
      <div class="model-review-feedback">
        <textarea class="model-review-textarea" placeholder="${t('modelReview.adjustPlaceholder')}" rows="3"></textarea>
        <button class="btn-submit model-review-submit">${t('modelReview.submitFeedback')}</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);

  // 缓存 DOM 引用
  const confirmBtn = overlay.querySelector(".model-review-confirm");
  const regenBtn = overlay.querySelector(".model-review-regenerate");
  const textarea = overlay.querySelector(".model-review-textarea");
  const submitBtn = overlay.querySelector(".model-review-submit");
  const closeBtn = overlay.querySelector(".model-review-close");

  // --- 关闭弹窗 ---
  function closeReview() {
    overlay.style.opacity = "0";
    setTimeout(() => overlay.remove(), 200);
  }
  closeBtn.addEventListener("click", closeReview);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) closeReview(); });

  // --- 确认按钮 ---
  confirmBtn.addEventListener("click", async () => {
    confirmBtn.disabled = true;
    confirmBtn.textContent = t('button.confirming');
    try {
      const res = await fetch(`/api/assets/model/${asset.id}/select`, { method: "POST" });
      if (!res.ok) throw new Error(t('modelReview.confirmFailed'));
      showToast(t('modelReview.confirmSuccess'), "success");
      closeReview();
      await refreshAssets();
    } catch (err) {
      showToast(t('modelReview.confirmFailedWith', {error: err.message}), "error");
      confirmBtn.disabled = false;
      confirmBtn.innerHTML = t('modelReview.confirmBtn');
    }
  });

  // --- 重新生成按钮 ---
  regenBtn.addEventListener("click", async () => {
    regenBtn.disabled = true;
    regenBtn.innerHTML = '<span class="spinner-inline"></span> ' + t('button.regenerating');
    try {
      const res = await fetch(`/api/assets/model/${asset.id}/regenerate`, { method: "POST" });
      if (!res.ok) { const err = await res.json(); throw new Error(err.detail || t('modelReview.regenerateFailed')); }
      showToast(t('modelReview.regenerateSuccess'), "info");
      closeReview();
      await refreshAssets();
      // 启动轮询，generating → pending 后自动弹出审核弹窗
      startModelReviewPoll(asset.id);
    } catch (err) {
      showToast(t('modelReview.regenerateFailedWith', {error: err.message}), "error");
      regenBtn.disabled = false;
      regenBtn.innerHTML = t('modelReview.regenerateBtn');
    }
  });

  // --- 调整意见：textarea 有文字时显示提交按钮 ---
  textarea.addEventListener("input", () => {
    submitBtn.classList.toggle("visible", textarea.value.trim().length > 0);
  });

  // --- 提交调整意见 ---
  submitBtn.addEventListener("click", async () => {
    const feedback = textarea.value.trim();
    if (!feedback) return;
    submitBtn.disabled = true;
    submitBtn.textContent = t('modelReview.submittingFeedback');
    try {
      const fd = new FormData();
      fd.append("feedback", feedback);
      const res = await fetch(`/api/assets/model/${asset.id}/adjust`, { method: "POST", body: fd });
      if (!res.ok) { const err = await res.json(); throw new Error(err.detail || t('modelReview.adjustFailed')); }
      showToast(t('modelReview.adjustSuccess'), "info");
      closeReview();
      await refreshAssets();
      // 启动轮询，generating → pending 后自动弹出审核弹窗
      startModelReviewPoll(asset.id);
    } catch (err) {
      showToast(t('modelReview.adjustFailedWith', {error: err.message}), "error");
      submitBtn.disabled = false;
      submitBtn.textContent = t('modelReview.submitFeedback');
    }
  });
}

/**
 * 轮询等待人物从 generating 变回 pending，然后自动弹出审核弹窗
 */
function startModelReviewPoll(assetId) {
  // 同时确保通用 generating 轮询也在运行
  startGeneratingPollIfNeeded();

  const pollInterval = setInterval(async () => {
    try {
      const res = await fetch("/api/assets");
      if (!res.ok) return;
      const data = await res.json();
      const model = (data.models || []).find(m => m.id === assetId);
      if (!model) {
        // 素材已删除，停止轮询
        clearInterval(pollInterval);
        return;
      }
      if (model.status === "pending") {
        clearInterval(pollInterval);
        // 刷新列表 UI
        assets.items = data.items || [];
        assets.models = data.models || [];
        renderColumnList("items", assets.items, "#col-items");
        renderColumnList("models", assets.models, "#col-models");
        // 自动弹出审核弹窗
        openModelReviewModal(model);
      } else if (model.status === "failed") {
        clearInterval(pollInterval);
        showToast(t('modelReview.generationFailed'), "error");
        await refreshAssets();
      }
    } catch (err) {
      console.error("[ModelReviewPoll] 轮询出错:", err);
    }
  }, 5000);
}

// ========== 选择方案模态框 ==========

function openSelectModal(assetType, asset, options) {
  const modal = $("#select-modal");
  const title = $("#select-modal-title");
  const body = $("#select-modal-body");

  const label = t('modal.lookPlan');
  title.textContent = t('modal.selectLook', {label: label, name: asset.name});

  let cardsHtml = "";
  options.forEach((path, i) => {
    const filename = path.split("/").pop();
    cardsHtml += `
      <div class="option-card" data-index="${i}">
        <img src="/assets/${asset.id}/${filename}" alt="${label} ${String.fromCharCode(65 + i)}" onerror="this.src=''">
        <div class="option-card-label">${t('modal.planLabel', {letter: String.fromCharCode(65 + i)})}</div>
      </div>
    `;
  });

  body.innerHTML = `
    <p style="color:var(--text-secondary);font-size:0.9rem;margin-bottom:1rem;">${t('modal.selectHint', {label: label})}</p>
    <div class="options-grid">${cardsHtml}</div>
    <button class="btn-submit" id="confirm-select-btn" disabled>${t('button.confirmSelect')}</button>
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
    confirmBtn.textContent = t('button.submitting');

    try {
      const endpoint = `/api/assets/model/${asset.id}/select`;
      const formData = new FormData();
      formData.append("look_index", selectedIndex);
      const res = await fetch(endpoint, { method: "POST", body: formData });
      if (!res.ok) throw new Error(t('toast.selectFailed', {error: ''}));
      // v10: 选择后设置 portrait_image
      asset.portrait_image = options[selectedIndex];
      showToast(t('toast.lookSelected', {label: label}), "success");
      closeSelectModal();
      refreshAssets();
    } catch (err) {
      showToast(t('toast.selectFailed', {error: err.message}), "error");
      confirmBtn.disabled = false;
      confirmBtn.textContent = t('button.confirmSelect');
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
        showToast(t('slot.typeMismatch', {type: slotType === "item" ? t('slot.typeItem') : t('slot.typeModel')}), "warning");
        return;
      }

      // 查找素材
      const listKey = type === "item" ? "items" : "models";
      const asset = assets[listKey].find((a) => a.id === id);
      if (!asset) { showToast(t('asset.notFound'), "error"); return; }

      // 验证状态
      if (type === "model" && !asset.portrait_image) { showToast(t('slot.selectLookFirst'), "warning"); return; }
      if (type === "item" && asset.questionnaire_status && asset.questionnaire_status !== "completed") { showToast(t('slot.confirmInfoFirst'), "warning"); return; }

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
  const icons = { item: "&#128230;", model: "&#128100;" };

  slotBody.classList.add("slot-empty");
  slotBody.innerHTML = `
    <span class="slot-icon">${icons[slotType]}</span>
    <span class="slot-hint">${t('slot.dragOrUpload')}</span>
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
  const formData = new FormData();
  formData.append("description", t('form.analyzeByImage'));
  files.forEach((f) => formData.append("images", f));

  if (slotType === "item") {
    // 走问卷流程（analyze 较快，不需要占位卡片）
    try {
      showToast(t('toast.analyzingItem'), "info");
      const res = await fetch("/api/assets/item/analyze", { method: "POST", body: formData });
      if (!res.ok) throw new Error(t('toast.itemAnalyzeFailed', {error: ''}));
      const data = await res.json();
      if (data.status === "rejected") { showToast(data.reason, "error"); return; }
      showToast(t('toast.itemAnalyzeComplete', {name: data.asset.name}), "success");
      openQuestionnaireModal(data.asset, data.questionnaire, data.selling_points);
      refreshAssets();
    } catch (err) {
      showToast(t('toast.itemAnalyzeFailed', {error: err.message}), "error");
    }
  } else {
    // v12: 人物 → 发送请求，通过 refreshAssets 渲染后端状态卡片
    showToast(t('toast.modelCreating'), "info");

    try {
      const res = await fetch("/api/assets/model", { method: "POST", body: formData });
      if (!res.ok) throw new Error(t('toast.createFailed', {error: ''}));
      const data = await res.json();

      // v15: 后端自动设置 portrait_image，不再前端自动 select
      await refreshAssets();
      if (data.asset) {
        // generating 状态不绑定槽位，等用户确认后再绑定
        if (data.asset.status === "confirmed") {
          bindSlot(slotType, data.asset);
        }
        const statusMsg = data.status_detail === "generating" ? t('toast.statusCreating') : t('toast.statusCreated');
        showToast(t('toast.modelSlotCreating', {name: data.asset.name, status: statusMsg}), "success");
      }
      // 启动轮询，等后台生成完成后自动刷新
      startGeneratingPollIfNeeded();
    } catch (err) {
      showToast(t('toast.createFailed', {error: err.message}), "error");
      await refreshAssets();
    }
  }
}

// 初始化两个槽位
setupSlot("item");
setupSlot("model");

// ========== 一句话快速创建素材 ==========

$("#btn-quickstart").addEventListener("click", async () => {
  const sentence = $("#gen-prompt").value.trim();
  if (!sentence) {
    showToast(t('toast.inputSentenceFirst'), "warning");
    $("#gen-prompt").focus();
    return;
  }

  const btn = $("#btn-quickstart");
  btn.disabled = true;
  btn.innerHTML = '<span class="btn-quickstart-icon">⏳</span> ' + t('button.quickstartProcessing');

  // v12: 通过 refreshAssets 渲染后端 generating 状态卡片，无需前端占位
  try {
    // 调用快速创建 API（拆解 + 创建两类素材）
    const formData = new FormData();
    formData.append("sentence", sentence);

    // 如果物品槽位有临时上传的文件，一并发送
    const itemSlotInput = document.querySelector("#slot-item-body .slot-file-input");
    if (itemSlotInput && itemSlotInput.files && itemSlotInput.files.length > 0) {
      Array.from(itemSlotInput.files).forEach(f => formData.append("images", f));
    }

    const res = await fetch("/api/quickstart/create", { method: "POST", body: formData });
    if (!res.ok) { const err = await res.json(); throw new Error(err.detail || t('toast.quickstartFailed', {error: ''})); }
    const data = await res.json();

    // 刷新列表，后端已保存 generating/pending 状态的素材
    await refreshAssets();
    showToast(t('toast.quickstartCreated'), "success");

    // 处理物品：打开问卷确认
    if (data.assets.item && data.assets.item.asset) {
      const itemAsset = data.assets.item.asset;
      if (data.assets.item.status !== "rejected") {
        openQuestionnaireModal(itemAsset, data.assets.item.questionnaire, data.assets.item.selling_points);
      } else {
        showToast(t('toast.quickstartItemRejected', {reason: data.assets.item.reason}), "error");
      }
    }

    // 处理人物：问卷关闭后弹出审核弹窗
    if (data.assets.model && data.assets.model.asset) {
      const modelData = data.assets.model;
      window._pendingModelReview = modelData.asset;
    }

    // 监听问卷模态框关闭 → 弹出人物造型选择
    setupQuickstartChain();

  } catch (err) {
    showToast(t('toast.quickstartFailed', {error: err.message}), "error");
    await refreshAssets();
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span class="btn-quickstart-icon">&#9889;</span> ' + t('button.quickstart');
  }
});

function setupQuickstartChain() {
  // 监听问卷模态框关闭，弹出人物审核弹窗
  const qModal = $("#questionnaire-modal");
  const observer = new MutationObserver(() => {
    if (qModal.style.display === "none" || qModal.style.display === "") {
      observer.disconnect();
      // 弹出人物审核弹窗
      if (window._pendingModelReview) {
        const asset = window._pendingModelReview;
        window._pendingModelReview = null;
        // pending 状态：直接打开审核弹窗
        // generating 状态：等轮询结束后再由用户手动点击编辑
        if (asset.status === "pending") {
          setTimeout(() => openModelReviewModal(asset), 300);
        }
      }
    }
  });
  observer.observe(qModal, { attributes: true, attributeFilter: ["style"] });
}

// ========== 渲染队列面板 ==========

/**
 * 阶段中文映射表
 * 后端返回的 status 字段对应的中文显示名
 */
const STAGE_LABELS = {
  queued: t('status.queued'),
  script: t('status.script'),
  images: t('status.images'),
  videos: t('status.videos'),
  stitching: t('status.stitching'),
  completed: t('status.completed'),
  failed: t('status.failed'),
  cancelled: t('status.cancelled'),
};

/**
 * 判断任务是否处于「渲染中」状态（包括各个阶段）
 */
function isJobRunning(status) {
  return ["script", "images", "videos", "stitching"].includes(status);
}

/**
 * 获取所有任务列表
 * 优雅降级：如果后端还没实现 /api/jobs，标记为不可用并跳过
 */
async function fetchJobQueue() {
  // 已确认接口不可用，直接跳过
  if (queueApiAvailable === false) return;

  try {
    const resp = await fetch("/api/jobs");
    if (!resp.ok) {
      // 404 说明后端还没实现该接口，标记不可用
      if (resp.status === 404) {
        queueApiAvailable = false;
        console.warn("[Queue] /api/jobs 接口不可用，队列面板已禁用");
        stopQueuePoll();
        return;
      }
      throw new Error(`HTTP ${resp.status}`);
    }

    queueApiAvailable = true;
    const jobs = await resp.json();
    queueJobs = Array.isArray(jobs) ? jobs : (jobs.jobs || []);
    renderQueuePanel(queueJobs);

    // 如果没有活跃任务（排队中或渲染中），停止轮询
    const hasActive = queueJobs.some(j => j.status === "queued" || isJobRunning(j.status));
    if (!hasActive) {
      stopQueuePoll();
    }
  } catch (err) {
    console.error("[Queue] 获取任务列表失败:", err);
  }
}

/**
 * 渲染队列面板
 * 根据任务列表更新面板内容和显示状态
 */
function renderQueuePanel(jobs) {
  const panel = $("#render-queue-panel");
  const countEl = $("#queue-count");
  const list = $("#queue-list");

  // 没有任何任务时隐藏面板
  if (!jobs || jobs.length === 0) {
    panel.style.display = "none";
    return;
  }

  // 显示面板
  panel.style.display = "block";

  // 更新计数（仅统计活跃任务数量：排队 + 渲染中）
  const activeCount = jobs.filter(j => j.status === "queued" || isJobRunning(j.status)).length;
  countEl.textContent = activeCount > 0 ? activeCount : jobs.length;

  // 按时间倒序排列（最新的在上面），活跃任务优先
  const sorted = [...jobs].sort((a, b) => {
    // 活跃任务优先
    const aActive = a.status === "queued" || isJobRunning(a.status) ? 1 : 0;
    const bActive = b.status === "queued" || isJobRunning(b.status) ? 1 : 0;
    if (aActive !== bActive) return bActive - aActive;
    // 同类按创建时间倒序
    return new Date(b.created_at || 0) - new Date(a.created_at || 0);
  });

  // 清空并重新渲染
  list.innerHTML = "";
  sorted.forEach(job => {
    const card = createJobCard(job);
    list.appendChild(card);
  });
}

/**
 * 创建单个任务卡片
 * 根据任务状态显示不同内容
 */
function createJobCard(job) {
  const card = document.createElement("div");
  const status = job.status || "queued";
  const running = isJobRunning(status);

  // 状态分类 CSS class
  let statusClass = "status-queued";
  if (running) statusClass = "status-running";
  else if (status === "completed") statusClass = "status-completed";
  else if (status === "failed") statusClass = "status-failed";
  else if (status === "cancelled") statusClass = "status-cancelled";

  card.className = `job-card ${statusClass}`;

  // 任务名称（优先用 name 字段，回退到 job_id 前8位）
  const name = job.name || t('queue.jobName', {id: (job.job_id || "").substring(0, 8)});

  // 状态标签
  const badgeLabel = STAGE_LABELS[status] || status;
  let badgeClass = "queued";
  if (running) badgeClass = "running";
  else if (status === "completed") badgeClass = "completed";
  else if (status === "failed") badgeClass = "failed";
  else if (status === "cancelled") badgeClass = "cancelled";

  // 消息/进度文字
  let messageHtml = "";
  if (status === "queued") {
    messageHtml = `<div class="job-card-message">${t('queue.waitingMsg')}</div>`;
  } else if (running) {
    const pct = Math.round((job.progress || 0) * 100);
    messageHtml = `
      <div class="job-card-message">
        <span class="job-stage-label">${escapeHtml(STAGE_LABELS[status])}</span>
        ${job.message ? ` — ${escapeHtml(job.message)}` : ""}
      </div>
      <div class="job-progress-bar">
        <div class="job-progress-fill" style="width: ${pct}%"></div>
      </div>
    `;
  } else if (status === "completed") {
    messageHtml = `<div class="job-card-message" style="color:var(--success);">${t('queue.videoComplete')}</div>`;
  } else if (status === "failed") {
    // 根据后端错误类型 key 映射 i18n 翻译（安全过滤器/限流等）
    let reason = job.message || t('queue.unknownError');
    if (reason === "safety_filtered") {
      reason = t('asset.safetyFiltered');
    }
    messageHtml = `<div class="job-card-message" style="color:var(--error);">&#10007; ${escapeHtml(reason)}</div>`;
  } else if (status === "cancelled") {
    messageHtml = `<div class="job-card-message">${t('queue.cancelledMsg')}</div>`;
  }

  // 操作按钮
  let actionsHtml = "";
  if (status === "queued" || running) {
    // 排队中 / 渲染中：可取消
    actionsHtml = `<button class="job-btn job-btn-cancel" data-cancel="${job.job_id}">${t('queue.cancelBtn')}</button>`;
  } else if (status === "completed") {
    // 已完成：预览（跳到进度详情页查看结果） + 下载
    actionsHtml = `
      <button class="job-btn job-btn-preview" data-preview="${job.job_id}">${t('queue.previewBtn')}</button>
      ${job.final_video_url ? `<a class="job-btn job-btn-download" href="${job.final_video_url}" download>${t('queue.downloadBtn')}</a>` : ""}
    `;
  }
  // failed / cancelled 不显示操作按钮

  // 时间显示
  let timeStr = "";
  if (job.created_at) {
    try {
      const d = new Date(job.created_at);
      timeStr = `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
    } catch {
      timeStr = "";
    }
  }

  card.innerHTML = `
    <div class="job-card-top">
      <div class="job-card-name">${escapeHtml(name)}</div>
      <span class="job-status-badge ${badgeClass}">${escapeHtml(badgeLabel)}</span>
    </div>
    ${messageHtml}
    <div class="job-card-bottom">
      <span class="job-card-time">${escapeHtml(timeStr)}</span>
      <div class="job-card-actions">${actionsHtml}</div>
    </div>
  `;

  // 绑定取消按钮事件
  const cancelBtn = card.querySelector("[data-cancel]");
  if (cancelBtn) {
    cancelBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      cancelJob(cancelBtn.dataset.cancel);
    });
  }

  // 绑定预览按钮事件（跳转到进度/结果视图）
  const previewBtn = card.querySelector("[data-preview]");
  if (previewBtn) {
    previewBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      viewJobResult(previewBtn.dataset.preview);
    });
  }

  // 点击渲染中的卡片，也可以跳到进度视图查看详情
  if (running) {
    card.style.cursor = "pointer";
    card.addEventListener("click", () => {
      viewJobProgress(job.job_id);
    });
  }

  return card;
}

/**
 * 取消任务
 */
async function cancelJob(jobId) {
  if (!confirm(t('queue.cancelConfirm'))) return;
  try {
    const resp = await fetch(`/api/jobs/${jobId}/cancel`, { method: "POST" });
    if (!resp.ok) throw new Error(t('queue.cancelFailed', {status: resp.status}));
    showToast(t('toast.jobCancelled'), "info");
    // 立即刷新队列
    await fetchJobQueue();
  } catch (err) {
    showToast(t('toast.cancelFailed', {error: err.message}), "error");
  }
}

/**
 * 查看渲染中任务的详细进度
 * 复用现有的进度视图（view-progress）
 */
function viewJobProgress(jobId) {
  currentJobId = jobId;
  localStorage.setItem("vlogforge_job_id", jobId);
  resetProgressUI();
  showView("progress");
  startSSE(jobId);
}

/**
 * 查看已完成任务的结果
 * 先查询状态，如果有 final_video_url 则展示结果页
 */
async function viewJobResult(jobId) {
  try {
    const resp = await fetch(`/api/status/${jobId}`);
    if (!resp.ok) throw new Error(t('toast.queryFailed', {error: ''}));
    const data = await resp.json();
    if (data.status === "completed" && data.final_video_url) {
      currentJobId = jobId;
      showResult(data);
    } else {
      showToast(t('toast.videoNotReady'), "warning");
    }
  } catch (err) {
    showToast(t('toast.queryFailed', {error: err.message}), "error");
  }
}

/**
 * 启动队列轮询（3秒刷新一次）
 * 仅当有活跃任务时运行
 */
function startQueuePoll() {
  if (queuePollTimer) return;
  console.log("[Queue] 启动队列轮询");
  queuePollTimer = setInterval(fetchJobQueue, 3000);
}

/**
 * 停止队列轮询
 */
function stopQueuePoll() {
  if (queuePollTimer) {
    console.log("[Queue] 停止队列轮询");
    clearInterval(queuePollTimer);
    queuePollTimer = null;
  }
}

/**
 * 初始化队列面板交互（折叠/展开）
 */
function initQueuePanel() {
  const header = $(".queue-header");
  const toggleBtn = $("#queue-toggle");
  const list = $("#queue-list");

  if (header) {
    header.addEventListener("click", () => {
      queueCollapsed = !queueCollapsed;
      list.classList.toggle("collapsed", queueCollapsed);
      toggleBtn.classList.toggle("collapsed", queueCollapsed);
    });
  }
}

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
  const segmentCount = $("#gen-segments").value;
  const extra = $("#gen-prompt").value.trim();

  try {
    // 如果人物槽位为空，先自动创建并确认
    if (!slotAssets.model) {
      showToast(t('toast.autoCreatingModel'), "info");
      const fd = new FormData();
      fd.append("description", extra || t('form.autoModelDesc'));
      const res = await fetch("/api/assets/model", { method: "POST", body: fd });
      const data = await res.json();
      // v15: 后端自动设置 portrait_image，直接调 select 确认
      if (data.asset && data.asset.portrait_image) {
        await fetch(`/api/assets/model/${data.asset.id}/select`, { method: "POST" });
      }
      slotAssets.model = data.asset;
    }

    // 提交生成
    showToast(t('toast.submittingVideo'), "info");
    const genForm = new FormData();
    genForm.append("item_id", slotAssets.item.id);
    genForm.append("model_id", slotAssets.model.id);
    genForm.append("platform", platform);
    genForm.append("segment_count", segmentCount);
    genForm.append("extra_requirements", extra);

    const genRes = await fetch("/api/generate/v2", { method: "POST", body: genForm });
    if (!genRes.ok) { const err = await genRes.json(); throw new Error(err.detail || t('toast.generateFailed', {error: ''})); }
    const genData = await genRes.json();

    currentJobId = genData.job_id;
    localStorage.setItem('vlogforge_job_id', currentJobId);

    // 刷新队列面板并启动轮询，让用户看到新任务已加入
    await fetchJobQueue();
    startQueuePoll();

    // 同时跳转到进度视图查看详细进度
    resetProgressUI();
    showView("progress");
    startSSE(currentJobId);
    showToast(t('toast.videoTaskCreated'), "success");
    refreshAssets();
  } catch (err) {
    showToast(t('toast.generateFailed', {error: err.message}), "error");
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
  $("#progress-message").textContent = t('pipeline.preparing');
  $("#script-preview").style.display = "none";
  $("#script-title").textContent = "";
  $("#style-guide").innerHTML = "";
  $("#segments-list").innerHTML = "";
  $("#storyboard-preview").style.display = "none";
  $("#storyboard-grid").innerHTML = "";
  const segPreview = $("#segments-preview");
  if (segPreview) { segPreview.style.display = "none"; }
  const segGrid = $("#segments-grid");
  if (segGrid) { segGrid.innerHTML = ""; }
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
      localStorage.removeItem('vlogforge_job_id');
      // 刷新队列面板，反映最新状态
      fetchJobQueue();
      if (data.status === "completed" && data.final_video_url) showResult(data);
      else if (data.status === "failed") {
        const errMsg = data.message === "safety_filtered" ? t('asset.safetyFiltered') : (data.message || t('queue.unknownError'));
        showToast(t('toast.generationFailed', {error: errMsg}), "error");
      }
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
        localStorage.removeItem('vlogforge_job_id');
        // 刷新队列面板，反映最新状态
        fetchJobQueue();
        if (data.status === "completed" && data.final_video_url) showResult(data);
        else if (data.status === "failed") {
          const errMsg = data.message === "safety_filtered" ? t('asset.safetyFiltered') : (data.message || t('queue.unknownError'));
          showToast(t('toast.generationFailed', {error: errMsg}), "error");
        }
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
  if (data.segment_urls && data.segment_urls.length > 0) renderSegments(data.segment_urls);
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
    <div class="style-guide-item"><div class="label">${t('script.person')}</div><div class="value">${escapeHtml(guide.person_description)}</div></div>
    <div class="style-guide-item"><div class="label">${t('script.scene')}</div><div class="value">${escapeHtml(guide.scene_context || guide.scene_description)}</div></div>
    <div class="style-guide-item"><div class="label">${t('script.style')}</div><div class="value">${escapeHtml(guide.visual_style)}</div></div>
    <div class="style-guide-item"><div class="label">${t('script.lighting')}</div><div class="value">${escapeHtml(guide.lighting)}</div></div>
  `;
  const list = $("#segments-list");
  list.innerHTML = "";
  script.segments.forEach((seg) => {
    const el = document.createElement("div");
    el.className = `segment-item${seg.needs_product ? " has-product" : ""}`;
    el.innerHTML = `
      <div class="segment-header">
        <span class="segment-number">${t('result.segmentNumber', {id: seg.segment_id})}</span>
        ${seg.needs_product ? '<span class="segment-badge">' + t('result.productPlacement') + '</span>' : ""}
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
  const existingCount = grid.children.length;

  // 仅追加新帧，避免每次清空重绘
  for (let i = existingCount; i < urls.length; i++) {
    const img = document.createElement("img");
    img.src = urls[i];
    img.alt = t('result.frame', {index: i + 1});
    img.loading = "lazy";
    grid.appendChild(img);
  }
}

function renderSegments(urls) {
  let container = $("#segments-preview");
  if (!container) return;
  container.style.display = "block";
  const grid = $("#segments-grid");
  if (!grid) return;
  const existingCount = grid.children.length;

  // 仅追加新片段，增量渲染
  for (let i = existingCount; i < urls.length; i++) {
    const video = document.createElement("video");
    video.src = urls[i];
    video.muted = true;
    video.loop = true;
    video.autoplay = true;
    video.playsInline = true;
    video.style.width = "100%";
    video.style.borderRadius = "8px";
    grid.appendChild(video);
  }
}

// ========== 结果视图 ==========

function showResult(data) {
  // 最终视频
  $("#result-video").src = data.final_video_url;
  $("#btn-download").href = data.final_video_url;

  // 分镜图
  const storyboardSection = $("#result-storyboard-section");
  const storyboardGrid = $("#result-storyboard-grid");
  storyboardGrid.innerHTML = "";
  if (data.storyboard_urls && data.storyboard_urls.length > 0) {
    storyboardSection.style.display = "";
    data.storyboard_urls.forEach((url, i) => {
      const item = document.createElement("div");
      item.className = "result-frame-item";
      item.innerHTML = `
        <img src="${url}" alt="${t('result.frame', {index: i + 1})}" loading="lazy">
        <a class="result-frame-download" href="${url}" download title="${t('result.download')}">&#11015;</a>
        <div class="result-frame-label">${t('result.frame', {index: i + 1})}</div>
      `;
      storyboardGrid.appendChild(item);
    });
  } else {
    storyboardSection.style.display = "none";
  }

  // 分段视频
  const segVideoSection = $("#result-segments-video-section");
  const segVideoGrid = $("#result-segments-video-grid");
  segVideoGrid.innerHTML = "";
  if (data.segment_urls && data.segment_urls.length > 0) {
    segVideoSection.style.display = "";
    data.segment_urls.forEach((url, i) => {
      const item = document.createElement("div");
      item.className = "result-seg-item";
      item.innerHTML = `
        <video src="${url}" controls preload="metadata"></video>
        <div class="result-seg-actions">
          <span class="result-seg-label">${t('result.segment', {index: i + 1})}</span>
          <a class="result-seg-download" href="${url}" download>${t('result.download')}</a>
        </div>
      `;
      segVideoGrid.appendChild(item);
    });
  } else {
    segVideoSection.style.display = "none";
  }

  // 脚本信息
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
          <span class="segment-number">${t('result.segmentNumber', {id: seg.segment_id})}</span>
          ${seg.needs_product ? '<span class="segment-badge">' + t('result.productPlacement') + '</span>' : ""}
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
  fetchJobQueue(); // 返回首页时刷新队列
});

$("#btn-new-task").addEventListener("click", () => {
  currentJobId = null;
  localStorage.removeItem('vlogforge_job_id');
  currentScript = null;
  slotAssets = { item: null, model: null };
  clearSlot("item");
  clearSlot("model");
  showView("home");
  refreshAssets();
  fetchJobQueue(); // 返回首页时刷新队列
});

// ========== 初始化 ==========

/**
 * 页面加载时恢复正在进行的视频生成任务
 * 从 localStorage 读取 job_id，向后端查询状态，按结果恢复对应视图
 */
async function restoreJobIfNeeded() {
  const savedJobId = localStorage.getItem('vlogforge_job_id');
  if (!savedJobId) return;

  try {
    const res = await fetch(`/api/status/${savedJobId}`);
    if (!res.ok) {
      // 任务不存在或接口异常，清除并回到首页
      localStorage.removeItem('vlogforge_job_id');
      return;
    }
    const data = await res.json();

    if (data.status === "completed") {
      // 任务已完成 → 展示结果页
      localStorage.removeItem('vlogforge_job_id');
      currentJobId = savedJobId;
      if (data.final_video_url) {
        showResult(data);
      }
    } else if (data.status === "failed") {
      // 任务已失败 → 清除，留在首页
      localStorage.removeItem('vlogforge_job_id');
      showToast(t('toast.lastJobFailed'), "error");
    } else {
      // 任务仍在进行中 → 恢复进度视图并重连 SSE
      currentJobId = savedJobId;
      resetProgressUI();
      showView("progress");
      updateProgress(data);
      startSSE(savedJobId);
      showToast(t('toast.jobRestored'), "info");
    }
  } catch (err) {
    // 网络错误等，清除存储，不阻塞正常加载
    localStorage.removeItem('vlogforge_job_id');
    console.warn("恢复任务失败:", err);
  }
}

// 时长滑块联动
function updateDurationLabel() {
  const slider = $("#gen-segments");
  if (!slider) return;
  const n = parseInt(slider.value);
  const label = $("#gen-duration-label");
  if (label) label.textContent = t('form.durationLabel', {segments: n, seconds: n * 6});
}

document.addEventListener("DOMContentLoaded", async () => {
  // 等待 i18n 翻译加载完成，避免 t() 返回 key 而非翻译文本
  if (window.i18nPromise) {
    await window.i18nPromise;
  }

  // 初始化时长滑块
  const slider = $("#gen-segments");
  if (slider) {
    slider.addEventListener("input", updateDurationLabel);
    updateDurationLabel();
  }

  // 初始化图片预览 Lightbox
  initLightbox();

  // 初始化素材库
  refreshAssets();

  // 初始化渲染队列面板交互
  initQueuePanel();

  // 尝试加载队列（优雅降级：后端未实现时自动跳过）
  await fetchJobQueue();

  // 如果队列中有活跃任务，启动轮询
  const hasActive = queueJobs.some(j => j.status === "queued" || isJobRunning(j.status));
  if (hasActive) {
    startQueuePoll();
  }

  // 恢复上次进行中的单任务进度视图
  restoreJobIfNeeded();
});
