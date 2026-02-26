/**
 * VlogForge 前端交互逻辑 (v10)
 * 统一主页：素材库两列（物品+人物） + 生成区拖拽槽位
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
let assets = { items: [], models: [] };
let currentJobId = null;
let eventSource = null;
let currentScript = null;

// 生成区槽位绑定的素材
let slotAssets = { item: null, model: null };

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

function createMiniCard(type, asset) {
  const card = document.createElement("div");
  card.className = "asset-mini-card";

  const slotType = type === "items" ? "item" : "model";
  const isConfirmed = asset.status === "confirmed";

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

  // v7: 状态标签（待确认/已确认）
  const badge = isConfirmed
    ? `<span class="asset-mini-badge success">已确认</span>`
    : `<span class="asset-mini-badge warning">待确认</span>`;

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

  // v7: 点击编辑（待确认状态 — 继续问卷）
  const editBtn = card.querySelector("[data-edit]");
  if (editBtn) {
    editBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (type === "items" && asset.questionnaire_fields && asset.questionnaire_fields.length > 0) {
        openQuestionnaireModal(asset);
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
      { field: "feature_image", label: "功能介绍图" },
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
      // 人物走原有流程
      const formData = new FormData();
      formData.append("description", desc);
      createFiles.forEach((f) => formData.append("images", f));

      try {
        const res = await fetch("/api/assets/model", { method: "POST", body: formData });
        if (!res.ok) { const err = await res.json(); throw new Error(err.detail || "创建失败"); }
        const data = await res.json();
        showToast(`${data.asset.name} 创建成功`, "success");
        closeCreateModal();

        if (data.look_options) {
          openSelectModal("model", data.asset, data.look_options);
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

    // 显示加载状态（带步骤提示）
    body.innerHTML = `
      <div class="q-loading-screen">
        <div class="q-submit-spinner"></div>
        <div class="q-loading-title">正在生成产品档案</div>
        <div class="q-loading-desc">AI 正在整合你的回答并生成产品素材图...</div>
        <div class="q-loading-steps">
          <div class="q-loading-step active" id="ql-step-1">
            <span class="q-loading-step-icon">&#9679;</span>
            <span>整合产品信息，优化文案</span>
          </div>
          <div class="q-loading-step" id="ql-step-2">
            <span class="q-loading-step-icon">&#9675;</span>
            <span>生成缩略图（产品白底主图）</span>
          </div>
          <div class="q-loading-step" id="ql-step-3">
            <span class="q-loading-step-icon">&#9675;</span>
            <span>生成三视图（正/侧/背）</span>
          </div>
          <div class="q-loading-step" id="ql-step-4">
            <span class="q-loading-step-icon">&#9675;</span>
            <span>生成功能介绍图</span>
          </div>
        </div>
      </div>
    `;

    // 模拟步骤进度动画（实际后端是串行生成，这里做视觉反馈）
    let stepTimer = null;
    let currentStep = 1;
    function advanceLoadingStep() {
      stepTimer = setInterval(() => {
        currentStep++;
        if (currentStep > 4) { clearInterval(stepTimer); return; }
        const prev = $(`#ql-step-${currentStep - 1}`);
        const curr = $(`#ql-step-${currentStep}`);
        if (prev) { prev.classList.remove("active"); prev.classList.add("done"); prev.querySelector(".q-loading-step-icon").innerHTML = "&#10003;"; }
        if (curr) { curr.classList.add("active"); curr.querySelector(".q-loading-step-icon").innerHTML = "&#9679;"; }
      }, 6000);
    }
    advanceLoadingStep();

    try {
      const formData = new FormData();
      formData.append("confirmed_fields", JSON.stringify(confirmed));

      const res = await fetch(`/api/assets/item/${asset.id}/confirm`, { method: "POST", body: formData });
      clearInterval(stepTimer);
      if (!res.ok) { const err = await res.json(); throw new Error(err.detail || "确认失败"); }

      const data = await res.json();
      const updatedAsset = data.asset;

      // 显示完成画面（含生成的图片）
      renderDoneScreen(updatedAsset);
      refreshAssets();
    } catch (err) {
      clearInterval(stepTimer);
      showToast(`确认失败: ${err.message}`, "error");
      renderQuestion(currentIndex);
    }
  }

  function renderDoneScreen(updatedAsset) {
    // 构建图片展示
    const imageFields = [
      { field: "thumbnail_image", label: "缩略图" },
      { field: "three_view_image", label: "三视图" },
      { field: "feature_image", label: "功能介绍图" },
    ];

    let imagesHtml = '';
    let imageCount = 0;
    for (const { field, label } of imageFields) {
      const url = getAssetImageUrl(updatedAsset, field);
      if (url) {
        imageCount++;
        imagesHtml += `
          <div class="q-done-image-card">
            <img src="${url}" alt="${escapeHtml(label)}" onerror="this.style.display='none';this.nextElementSibling.style.display='flex';">
            <div class="q-done-image-placeholder" style="display:none;">加载失败</div>
            <div class="q-done-image-label">${escapeHtml(label)}</div>
          </div>`;
      } else {
        imagesHtml += `
          <div class="q-done-image-card">
            <div class="q-done-image-placeholder">未生成</div>
            <div class="q-done-image-label">${escapeHtml(label)}</div>
          </div>`;
      }
    }

    const imageNote = imageCount === 3
      ? '3 张产品素材图已生成'
      : imageCount > 0
        ? `${imageCount}/3 张图片已生成，部分图片生成失败`
        : '产品图片生成失败，可稍后在详情页中查看';

    body.innerHTML = `
      <div class="q-done-screen">
        <div class="q-done-icon">&#10003;</div>
        <div class="q-done-title">产品档案创建完成</div>
        <div class="q-done-desc">${escapeHtml(imageNote)}</div>
        <div class="q-done-images">${imagesHtml}</div>
        <button class="q-done-btn" id="q-done-close">完成</button>
      </div>
    `;

    $("#q-done-close").addEventListener("click", () => {
      modal.style.display = "none";
    });
  }

  // 渲染第一题
  renderQuestion(0);
  modal.style.display = "flex";
}

$("#questionnaire-close").addEventListener("click", () => { $("#questionnaire-modal").style.display = "none"; });
$("#questionnaire-modal").addEventListener("click", (e) => { if (e.target === e.currentTarget) $("#questionnaire-modal").style.display = "none"; });

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
  const apiType = slotType;
  showToast(`正在创建${slotType === "item" ? "物品" : "人物"}...`, "info");

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

      // 自动选择第一个方案，设置 portrait_image
      if (slotType === "model" && data.look_options && data.look_options.length > 0) {
        const sf = new FormData(); sf.append("look_index", 0);
        await fetch(`/api/assets/model/${data.asset.id}/select`, { method: "POST", body: sf });
        data.asset.portrait_image = data.look_options[0];
      }

      bindSlot(slotType, data.asset);
      showToast(`${data.asset.name} 已创建`, "success");
      refreshAssets();
    }
  } catch (err) {
    showToast(`创建失败: ${err.message}`, "error");
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

    showToast("两类素材已创建，请依次确认", "success");
    await refreshAssets();

    // 处理物品：打开问卷确认
    if (data.assets.item && data.assets.item.asset) {
      const itemAsset = data.assets.item.asset;
      if (data.assets.item.status !== "rejected") {
        openQuestionnaireModal(itemAsset, data.assets.item.questionnaire, data.assets.item.selling_points);
      } else {
        showToast(`物品被拒绝: ${data.assets.item.reason}`, "error");
      }
    }

    // 处理人物：打开造型选择
    if (data.assets.model && data.assets.model.look_options) {
      // 问卷关闭后自动弹出造型选择（用 setTimeout 避免同时弹出多个模态框）
      const modelData = data.assets.model;
      window._pendingModelSelect = { asset: modelData.asset, options: modelData.look_options };
    }

    // 监听问卷模态框关闭 → 弹出人物造型选择
    setupQuickstartChain();

  } catch (err) {
    showToast(`快速创建失败: ${err.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span class="btn-quickstart-icon">&#9889;</span> 一句话快速创建素材';
  }
});

function setupQuickstartChain() {
  // 监听问卷模态框关闭，弹出人物造型选择
  const qModal = $("#questionnaire-modal");
  const observer = new MutationObserver(() => {
    if (qModal.style.display === "none" || qModal.style.display === "") {
      observer.disconnect();
      // 弹出人物造型选择
      if (window._pendingModelSelect) {
        const { asset, options } = window._pendingModelSelect;
        window._pendingModelSelect = null;
        setTimeout(() => openSelectModal("model", asset, options), 300);
      }
    }
  });
  observer.observe(qModal, { attributes: true, attributeFilter: ["style"] });
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
    // 如果人物槽位为空，先自动创建
    if (!slotAssets.model) {
      showToast("正在自动创建人物...", "info");
      const fd = new FormData();
      fd.append("description", extra || "适合vlog带货的亲和女生，客厅拍摄");
      const res = await fetch("/api/assets/model", { method: "POST", body: fd });
      const data = await res.json();
      if (data.look_options && data.look_options.length > 0) {
        const sf = new FormData(); sf.append("look_index", 0);
        await fetch(`/api/assets/model/${data.asset.id}/select`, { method: "POST", body: sf });
      }
      slotAssets.model = data.asset;
      slotAssets.model.portrait_image = data.look_options?.[0] || null;
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
  slotAssets = { item: null, model: null };
  clearSlot("item");
  clearSlot("model");
  showView("home");
  refreshAssets();
});

// ========== 初始化 ==========
document.addEventListener("DOMContentLoaded", () => { refreshAssets(); });
