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
    if (!res.ok) throw new Error("加载素材失败");
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
    container.innerHTML = `<div style="text-align:center;color:var(--text-muted);font-size:0.8rem;padding:1rem 0;">暂无素材</div>`;
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
          <div class="asset-mini-name">${escapeHtml(asset.name || "素材")}</div>
          <div class="asset-mini-meta" style="color:#3b82f6;">制作中...</div>
        </div>
      </div>
      <div class="asset-generating-progress">
        <span class="gen-spinner"></span>
        <span class="gen-progress-text">制作中...</span>
      </div>
    `;
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
    badge = `<span class="asset-mini-badge success">已确认</span>`;
  } else {
    badge = `<span class="asset-mini-badge warning">待确认</span>`;
  }

  // v7: 按钮根据状态不同
  let actionBtns = "";
  if (isConfirmed) {
    actionBtns = `
      <button class="btn-sm btn-detail" data-detail="${asset.id}">详情</button>
      <button class="btn-sm btn-danger" data-delete="${asset.id}">删除</button>
    `;
  } else {
    actionBtns = `
      <button class="btn-sm btn-edit" data-edit="${asset.id}">编辑</button>
      <button class="btn-sm btn-danger" data-delete="${asset.id}">删除</button>
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
      } else if (type === "models" && asset.status === "pending") {
        openModelReviewModal(asset);
      } else {
        showToast("该素材暂不支持编辑", "warning");
      }
    });
  }

  // 点击删除
  card.querySelector("[data-delete]").addEventListener("click", async (e) => {
    e.stopPropagation();
    if (!confirm(`确定删除 ${asset.name}？`)) return;
    try {
      const res = await fetch(`/api/assets/${asset.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("删除失败");
      showToast(`${asset.name} 已删除`, "success");
      if (slotAssets[slotType] && slotAssets[slotType].id === asset.id) clearSlot(slotType);
      refreshAssets();
    } catch (err) {
      showToast(`删除失败: ${err.message}`, "error");
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
        <button class="btn-sm btn-tag-edit" data-asset="${assetId}" data-field="${fieldKey}" data-section="${sectionId}">编辑</button>
      </div>
      <div class="detail-tag-body">${tagsHtml || '<span class="detail-tag-empty">暂无</span>'}</div>
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

  const labels = { items: "物品", models: "人物" };
  title.textContent = `${labels[type]}详情 - ${asset.name}`;

  let content = "";

  if (type === "items") {
    // v7: 三张产品图
    content += renderImagesRow(asset, [
      { field: "thumbnail_image", label: "缩略图" },
      { field: "three_view_image", label: "三视图" },
    ]);

    // v7: tag 分区展示 + 编辑
    const pi = asset.product_info || {};
    for (const [key, value] of Object.entries(pi)) {
      if (value) content += renderTagSection(`item-${key}`, key, value, asset.id, `product_info.${key}`);
    }

    // 卖点
    const sp = asset.selling_points || {};
    if (sp.P0 && sp.P0.length) content += renderTagSection("sp-p0", "P0 核心卖点", sp.P0.join("、"), asset.id, "selling_points.P0");
    if (sp.P1 && sp.P1.length) content += renderTagSection("sp-p1", "P1 辅助卖点", sp.P1.join("、"), asset.id, "selling_points.P1");

    content += `<div class="detail-section"><h4>完整描述</h4><p class="detail-desc">${escapeHtml(asset.full_description)}</p></div>`;

  } else if (type === "models") {
    // v10: 一张大图（portrait_image，人在场景中的半身近景照）
    content += renderImagesRow(asset, [
      { field: "portrait_image", label: "人物形象" },
    ]);

    content += renderTagSection("model-appearance", "外貌特征", asset.appearance, asset.id, "appearance");
    content += renderTagSection("model-personality", "气质风格", asset.personality, asset.id, "personality");
    content += renderTagSection("model-outfits", "穿搭", asset.outfits, asset.id, "outfits");
    content += renderTagSection("model-scene", "拍摄场景", asset.scene_context, asset.id, "scene_context");

    content += `<div class="detail-section"><h4>完整描述</h4><p class="detail-desc">${escapeHtml(asset.full_description)}</p></div>`;
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

      if (btn.textContent === "编辑") {
        // 进入编辑模式
        btn.textContent = "确认";
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
        btn.textContent = "编辑";
        btn.classList.remove("btn-confirm");
        const inputs = tagBody.querySelectorAll(".detail-tag-input");
        const newValues = [...inputs].map(i => i.value.trim()).filter(Boolean);
        const newText = newValues.join("、");

        // 更新显示
        tagBody.innerHTML = newValues.length > 0
          ? newValues.map(v => `<span class="detail-tag">${escapeHtml(v)}</span>`).join("")
          : '<span class="detail-tag-empty">暂无</span>';

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
      showToast(`保存失败: ${err.message}`, "error");
      return;
    }
  } else {
    updates[fieldPath] = newValue;
  }

  try {
    const formData = new FormData();
    formData.append("updates", JSON.stringify(updates));
    const res = await fetch(`/api/assets/${assetId}`, { method: "PUT", body: formData });
    if (!res.ok) throw new Error("保存失败");
    showToast("已保存", "success");
    refreshAssets();
  } catch (err) {
    showToast(`保存失败: ${err.message}`, "error");
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
  const labels = { items: "物品", models: "人物" };
  title.textContent = `创建${labels[type]}素材`;

  const placeholders = {
    items: "描述产品信息，如：一瓶氨基酸洗面奶，温和配方不紧绷，适合敏感肌",
    models: "描述人物形象，如：20多岁亚洲女生，短发，在客厅拍摄vlog",
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
      // v12: 人物 → 关闭模态框，发送请求，通过 refreshAssets 渲染 generating 卡片
      const formData = new FormData();
      formData.append("description", desc);
      createFiles.forEach((f) => formData.append("images", f));

      closeCreateModal();
      showToast("人物素材创建中，请稍候...", "info");

      try {
        const res = await fetch("/api/assets/model", { method: "POST", body: formData });
        if (!res.ok) { const err = await res.json(); throw new Error(err.detail || "创建失败"); }
        const data = await res.json();

        console.log(`[ModelCreate] 成功: ${data.asset.name}`);
        // 刷新列表，后端已保存 generating/pending 状态的素材
        await refreshAssets();
        showToast(`${data.asset.name} 创建成功`, "success");

        // v15: 后端自动设置 portrait_image，pending 状态时用户通过审核弹窗确认
        if (data.asset && data.asset.status === "pending") {
          openModelReviewModal(data.asset);
        }
      } catch (err) {
        showToast(`创建失败: ${err.message}`, "error");
        await refreshAssets();
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

// ========== 智能问卷模态框（v7：逐题 A/B/C 选择式） ==========

function openQuestionnaireModal(asset, questionnaire, sellingPoints) {
  const modal = $("#questionnaire-modal");
  const title = $("#questionnaire-title");
  const body = $("#questionnaire-body");

  // 使用传入的问卷，或从 asset 中取
  const questions = questionnaire || asset.questionnaire_fields || [];
  if (questions.length === 0) {
    showToast("没有需要确认的问题", "warning");
    return;
  }

  title.textContent = `产品信息确认 — ${asset.name}`;

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
            <span class="q-stepper-label">${q.priority} 级问题</span>
            <span class="q-stepper-counter">${index + 1} / ${total}</span>
          </div>
        </div>

        <div class="q-card ${priorityClass}">
          <div class="q-card-header">
            <span class="q-priority-badge">${q.priority}</span>
            ${isOptional
              ? '<span class="q-optional-badge">可跳过</span>'
              : '<span class="q-required-badge">必答</span>'}
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
              <div class="q-option-text">我来填写</div>
            </div>
          </div>

          <div class="q-custom-input-wrap" id="q-custom-wrap" style="display:${selectedOption === 'c' ? 'block' : 'none'}">
            <textarea class="q-custom-input" id="q-custom-input" rows="2"
              placeholder="输入你的回答...">${selectedOption === 'c' ? escapeHtml(currentAnswer) : ''}</textarea>
          </div>
        </div>

        <div class="q-nav">
          <button class="q-nav-btn q-nav-prev" id="q-prev" ${index === 0 ? 'disabled' : ''}>&#8592; 上一题</button>
          <div class="q-nav-center">
            ${isOptional ? '<button class="q-nav-btn q-nav-skip" id="q-skip">跳过</button>' : ''}
          </div>
          ${index < total - 1
            ? '<button class="q-nav-btn q-nav-next" id="q-next">下一题 &#8594;</button>'
            : '<button class="q-nav-btn q-nav-submit" id="q-submit">提交并生成素材</button>'
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
      showToast("请选择一个选项或自行填写", "warning");
      return false;
    }
    if (answers[currentIndex].source === "user" && q.required && !answers[currentIndex].value) {
      showToast("请填写你的回答", "warning");
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
          showToast(`请回答必填项：${q.label}`, "error");
          return;
        }
      }
    }

    // v12: 关闭问卷模态框，发送确认请求，通过 refreshAssets 渲染 generating 卡片
    modal.style.display = "none";
    showToast("物品素材确认中，请稍候...", "info");

    // 立即刷新一次，显示后端刚创建的 generating 状态卡片
    await refreshAssets();

    try {
      const formData = new FormData();
      formData.append("confirmed_fields", JSON.stringify(confirmed));

      const res = await fetch(`/api/assets/item/${asset.id}/confirm`, { method: "POST", body: formData });
      if (!res.ok) { const err = await res.json(); throw new Error(err.detail || "确认失败"); }

      const data = await res.json();
      console.log(`[ItemConfirm] 成功: ${data.asset.name}`);
      // 刷新列表获取 confirmed 状态
      await refreshAssets();
      showToast(`${data.asset.name || "物品"} 档案创建完成`, "success");
    } catch (err) {
      showToast(`确认失败: ${err.message}`, "error");
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
        <h2>人物造型审核 - ${escapeHtml(asset.name)}</h2>
        <button class="modal-close model-review-close">&times;</button>
      </div>
      <div class="model-review-image">
        ${imgUrl
          ? `<img src="${imgUrl}" alt="${escapeHtml(asset.name)} 造型图" />`
          : `<div class="model-review-placeholder">暂无造型图</div>`
        }
      </div>
      <div class="model-review-actions">
        <button class="btn-submit model-review-confirm">&#10003; 确认</button>
        <button class="btn-submit model-review-regenerate" style="background:rgba(255,255,255,0.08);color:var(--text-primary);">&#8635; 重新生成</button>
      </div>
      <div class="model-review-feedback">
        <textarea class="model-review-textarea" placeholder="输入调整意见，例如：头发再长一点..." rows="3"></textarea>
        <button class="btn-submit model-review-submit">提交</button>
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
    confirmBtn.textContent = "确认中...";
    try {
      const res = await fetch(`/api/assets/model/${asset.id}/select`, { method: "POST" });
      if (!res.ok) throw new Error("确认失败");
      showToast("人物造型已确认", "success");
      closeReview();
      await refreshAssets();
    } catch (err) {
      showToast(`确认失败: ${err.message}`, "error");
      confirmBtn.disabled = false;
      confirmBtn.innerHTML = "&#10003; 确认";
    }
  });

  // --- 重新生成按钮 ---
  regenBtn.addEventListener("click", async () => {
    regenBtn.disabled = true;
    regenBtn.innerHTML = '<span class="spinner-inline"></span> 重新生成中...';
    try {
      const res = await fetch(`/api/assets/model/${asset.id}/regenerate`, { method: "POST" });
      if (!res.ok) { const err = await res.json(); throw new Error(err.detail || "重新生成失败"); }
      showToast("正在重新生成造型，请稍候...", "info");
      closeReview();
      await refreshAssets();
      // 启动轮询，generating → pending 后自动弹出审核弹窗
      startModelReviewPoll(asset.id);
    } catch (err) {
      showToast(`重新生成失败: ${err.message}`, "error");
      regenBtn.disabled = false;
      regenBtn.innerHTML = "&#8635; 重新生成";
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
    submitBtn.textContent = "提交中...";
    try {
      const fd = new FormData();
      fd.append("feedback", feedback);
      const res = await fetch(`/api/assets/model/${asset.id}/adjust`, { method: "POST", body: fd });
      if (!res.ok) { const err = await res.json(); throw new Error(err.detail || "提交失败"); }
      showToast("正在根据意见调整造型，请稍候...", "info");
      closeReview();
      await refreshAssets();
      // 启动轮询，generating → pending 后自动弹出审核弹窗
      startModelReviewPoll(asset.id);
    } catch (err) {
      showToast(`提交失败: ${err.message}`, "error");
      submitBtn.disabled = false;
      submitBtn.textContent = "提交";
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
        showToast("人物造型生成失败，请重试", "error");
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

  const label = "造型方案";
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
      const endpoint = `/api/assets/model/${asset.id}/select`;
      const formData = new FormData();
      formData.append("look_index", selectedIndex);
      const res = await fetch(endpoint, { method: "POST", body: formData });
      if (!res.ok) throw new Error("选择失败");
      // v10: 选择后设置 portrait_image
      asset.portrait_image = options[selectedIndex];
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
        showToast(`类型不匹配：需要${slotType === "item" ? "物品" : "人物"}素材`, "warning");
        return;
      }

      // 查找素材
      const listKey = type === "item" ? "items" : "models";
      const asset = assets[listKey].find((a) => a.id === id);
      if (!asset) { showToast("素材不存在", "error"); return; }

      // 验证状态
      if (type === "model" && !asset.portrait_image) { showToast("请先选择造型方案", "warning"); return; }
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
  const icons = { item: "&#128230;", model: "&#128100;" };

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
  const formData = new FormData();
  formData.append("description", "请根据图片分析");
  files.forEach((f) => formData.append("images", f));

  if (slotType === "item") {
    // 走问卷流程（analyze 较快，不需要占位卡片）
    try {
      showToast("正在分析物品...", "info");
      const res = await fetch("/api/assets/item/analyze", { method: "POST", body: formData });
      if (!res.ok) throw new Error("分析失败");
      const data = await res.json();
      if (data.status === "rejected") { showToast(data.reason, "error"); return; }
      showToast(`${data.asset.name} 分析完成`, "success");
      openQuestionnaireModal(data.asset, data.questionnaire, data.selling_points);
      refreshAssets();
    } catch (err) {
      showToast(`分析失败: ${err.message}`, "error");
    }
  } else {
    // v12: 人物 → 发送请求，通过 refreshAssets 渲染后端状态卡片
    showToast("人物素材创建中，请稍候...", "info");

    try {
      const res = await fetch("/api/assets/model", { method: "POST", body: formData });
      if (!res.ok) throw new Error("创建失败");
      const data = await res.json();

      // v15: 后端自动设置 portrait_image，不再前端自动 select
      await refreshAssets();
      if (data.asset) {
        // generating 状态不绑定槽位，等用户确认后再绑定
        if (data.asset.status === "confirmed") {
          bindSlot(slotType, data.asset);
        }
        const statusMsg = data.status_detail === "generating" ? "创建中" : "已创建";
        showToast(`${data.asset.name} ${statusMsg}`, "success");
      }
      // 启动轮询，等后台生成完成后自动刷新
      startGeneratingPollIfNeeded();
    } catch (err) {
      showToast(`创建失败: ${err.message}`, "error");
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
    showToast("请先输入一句话描述", "warning");
    $("#gen-prompt").focus();
    return;
  }

  const btn = $("#btn-quickstart");
  btn.disabled = true;
  btn.innerHTML = '<span class="btn-quickstart-icon">⏳</span> AI 拆解中...';

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
    if (!res.ok) { const err = await res.json(); throw new Error(err.detail || "快速创建失败"); }
    const data = await res.json();

    // 刷新列表，后端已保存 generating/pending 状态的素材
    await refreshAssets();
    showToast("两类素材已创建，请依次确认", "success");

    // 处理物品：打开问卷确认
    if (data.assets.item && data.assets.item.asset) {
      const itemAsset = data.assets.item.asset;
      if (data.assets.item.status !== "rejected") {
        openQuestionnaireModal(itemAsset, data.assets.item.questionnaire, data.assets.item.selling_points);
      } else {
        showToast(`物品被拒绝: ${data.assets.item.reason}`, "error");
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
    showToast(`快速创建失败: ${err.message}`, "error");
    await refreshAssets();
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span class="btn-quickstart-icon">&#9889;</span> 一句话快速创建素材';
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
  queued: "排队中",
  script: "生成脚本",
  images: "生成分镜图",
  videos: "生成视频片段",
  stitching: "拼接视频",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
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
  const name = job.name || `任务 ${(job.job_id || "").substring(0, 8)}`;

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
    messageHtml = `<div class="job-card-message">等待前面的任务完成...</div>`;
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
    messageHtml = `<div class="job-card-message" style="color:var(--success);">&#10003; 视频生成完成</div>`;
  } else if (status === "failed") {
    const reason = job.message || "未知错误";
    messageHtml = `<div class="job-card-message" style="color:var(--error);">&#10007; ${escapeHtml(reason)}</div>`;
  } else if (status === "cancelled") {
    messageHtml = `<div class="job-card-message">已取消</div>`;
  }

  // 操作按钮
  let actionsHtml = "";
  if (status === "queued" || running) {
    // 排队中 / 渲染中：可取消
    actionsHtml = `<button class="job-btn job-btn-cancel" data-cancel="${job.job_id}">取消</button>`;
  } else if (status === "completed") {
    // 已完成：预览（跳到进度详情页查看结果） + 下载
    actionsHtml = `
      <button class="job-btn job-btn-preview" data-preview="${job.job_id}">预览</button>
      ${job.final_video_url ? `<a class="job-btn job-btn-download" href="${job.final_video_url}" download>下载</a>` : ""}
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
  if (!confirm("确定要取消这个任务吗？")) return;
  try {
    const resp = await fetch(`/api/jobs/${jobId}/cancel`, { method: "POST" });
    if (!resp.ok) throw new Error(`取消失败: HTTP ${resp.status}`);
    showToast("任务已取消", "info");
    // 立即刷新队列
    await fetchJobQueue();
  } catch (err) {
    showToast(`取消失败: ${err.message}`, "error");
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
    if (!resp.ok) throw new Error("查询失败");
    const data = await resp.json();
    if (data.status === "completed" && data.final_video_url) {
      currentJobId = jobId;
      showResult(data);
    } else {
      showToast("视频文件尚未就绪", "warning");
    }
  } catch (err) {
    showToast(`查询失败: ${err.message}`, "error");
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
  const duration = $("#gen-duration").value;
  const extra = $("#gen-prompt").value.trim();

  try {
    // 如果人物槽位为空，先自动创建并确认
    if (!slotAssets.model) {
      showToast("正在自动创建人物...", "info");
      const fd = new FormData();
      fd.append("description", extra || "适合vlog带货的亲和女生，客厅拍摄");
      const res = await fetch("/api/assets/model", { method: "POST", body: fd });
      const data = await res.json();
      // v15: 后端自动设置 portrait_image，直接调 select 确认
      if (data.asset && data.asset.portrait_image) {
        await fetch(`/api/assets/model/${data.asset.id}/select`, { method: "POST" });
      }
      slotAssets.model = data.asset;
    }

    // 提交生成
    showToast("正在提交视频生成...", "info");
    const genForm = new FormData();
    genForm.append("item_id", slotAssets.item.id);
    genForm.append("model_id", slotAssets.model.id);
    genForm.append("platform", platform);
    genForm.append("duration", duration);
    genForm.append("extra_requirements", extra);

    const genRes = await fetch("/api/generate/v2", { method: "POST", body: genForm });
    if (!genRes.ok) { const err = await genRes.json(); throw new Error(err.detail || "生成失败"); }
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
        localStorage.removeItem('vlogforge_job_id');
        // 刷新队列面板，反映最新状态
        fetchJobQueue();
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
    <div class="style-guide-item"><div class="label">人物</div><div class="value">${escapeHtml(guide.person_description)}</div></div>
    <div class="style-guide-item"><div class="label">场景</div><div class="value">${escapeHtml(guide.scene_context || guide.scene_description)}</div></div>
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
  const existingCount = grid.children.length;

  // 仅追加新帧，避免每次清空重绘
  for (let i = existingCount; i < urls.length; i++) {
    const img = document.createElement("img");
    img.src = urls[i];
    img.alt = `帧 ${i + 1}`;
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
      showToast("上次的生成任务已失败", "error");
    } else {
      // 任务仍在进行中 → 恢复进度视图并重连 SSE
      currentJobId = savedJobId;
      resetProgressUI();
      showView("progress");
      updateProgress(data);
      startSSE(savedJobId);
      showToast("已恢复进行中的生成任务", "info");
    }
  } catch (err) {
    // 网络错误等，清除存储，不阻塞正常加载
    localStorage.removeItem('vlogforge_job_id');
    console.warn("恢复任务失败:", err);
  }
}

document.addEventListener("DOMContentLoaded", async () => {
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
