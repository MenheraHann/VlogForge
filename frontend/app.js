/**
 * VlogForge 前端交互逻辑 (v4.1)
 * 主页：三列素材库 + 快速生成区
 * 生成视频页：从素材库选择组合（模式 A）
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
let selectedAssets = { item: null, model: null, scene: null };
let currentJobId = null;
let eventSource = null;
let currentScript = null;

// 快速生成区的上传文件
let quickFiles = { item: [], model: [], scene: [] };

// ========== 导航 ==========
const navLinks = $$(".nav-link");

function showView(viewId) {
  $$(".view").forEach((v) => v.classList.remove("active"));
  navLinks.forEach((l) => l.classList.remove("active"));
  const view = $(`#view-${viewId}`);
  if (view) view.classList.add("active");
  const link = $(`.nav-link[data-view="${viewId}"]`);
  if (link) link.classList.add("active");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

navLinks.forEach((link) => {
  link.addEventListener("click", () => {
    const viewId = link.dataset.view;
    showView(viewId);
    if (viewId === "home") refreshAssets();
    if (viewId === "generate") { refreshAssets().then(() => refreshGenerateView()); }
  });
});

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

function createMiniCard(type, asset) {
  const card = document.createElement("div");
  card.className = "asset-mini-card";

  // 缩略图
  const imgPath = asset.instruction_image_path || asset.selected_look || asset.selected_scene;
  let thumbHtml = "";
  if (imgPath) {
    const filename = imgPath.split("/").pop();
    thumbHtml = `<img class="asset-mini-thumb" src="/assets/${asset.id}/${filename}" alt="${escapeHtml(asset.name)}" onerror="this.style.display='none'">`;
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
  if (type === "models") {
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
      <button class="btn-sm btn-danger" data-delete="${asset.id}">删除</button>
    </div>
  `;

  card.querySelector("[data-delete]").addEventListener("click", async (e) => {
    e.stopPropagation();
    if (!confirm(`确定删除 ${asset.name}？`)) return;
    try {
      const res = await fetch(`/api/assets/${asset.id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("删除失败");
      showToast(`${asset.name} 已删除`, "success");
      refreshAssets();
    } catch (err) {
      showToast(`删除失败: ${err.message}`, "error");
    }
  });

  return card;
}

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
    const apiType = type === "items" ? "item" : type === "models" ? "model" : "scene";

    const formData = new FormData();
    formData.append("description", desc);
    createFiles.forEach((f) => formData.append("images", f));

    try {
      const res = await fetch(`/api/assets/${apiType}`, { method: "POST", body: formData });
      if (!res.ok) { const err = await res.json(); throw new Error(err.detail || "创建失败"); }
      const data = await res.json();

      if (data.status === "rejected") {
        showToast(`创建失败: ${data.reason}`, "error");
        closeCreateModal();
        return;
      }

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
  });

  modal.style.display = "flex";
}

function closeCreateModal() { $("#create-modal").style.display = "none"; }
$("#modal-close").addEventListener("click", closeCreateModal);
$("#create-modal").addEventListener("click", (e) => { if (e.target === e.currentTarget) closeCreateModal(); });

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

// ========== 快速生成区：上传逻辑 ==========

function setupQuickUpload(type, maxFiles) {
  const zone = $(`#upload-${type}-zone`);
  const input = $(`#upload-${type}-input`);

  zone.addEventListener("click", (e) => {
    if (e.target.closest(".remove-img")) return;
    input.click();
  });

  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("drag-over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    zone.classList.remove("drag-over");
    const files = Array.from(e.dataTransfer.files).filter((f) => f.type.startsWith("image/"));
    addQuickFiles(type, files, maxFiles);
  });

  input.addEventListener("change", () => {
    addQuickFiles(type, Array.from(input.files), maxFiles);
    input.value = "";
  });
}

function addQuickFiles(type, files, maxFiles) {
  const remaining = maxFiles - quickFiles[type].length;
  quickFiles[type].push(...files.slice(0, remaining));
  renderQuickPreview(type);
  updateQuickGenButton();
}

function renderQuickPreview(type) {
  const placeholder = $(`#upload-${type}-placeholder`);
  const preview = $(`#upload-${type}-preview`);

  if (quickFiles[type].length === 0) {
    placeholder.style.display = "flex";
    preview.innerHTML = "";
    return;
  }

  placeholder.style.display = "none";
  preview.innerHTML = "";
  quickFiles[type].forEach((file, i) => {
    const w = document.createElement("div"); w.className = "img-wrapper";
    const img = document.createElement("img"); img.src = URL.createObjectURL(file);
    const btn = document.createElement("button"); btn.className = "remove-img"; btn.textContent = "\u00D7";
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      quickFiles[type].splice(i, 1);
      renderQuickPreview(type);
      updateQuickGenButton();
    });
    w.appendChild(img); w.appendChild(btn); preview.appendChild(w);
  });
}

function updateQuickGenButton() {
  const btn = $("#btn-quick-gen");
  // 物品图片必传
  btn.disabled = quickFiles.item.length === 0;
}

// 初始化三个上传区
setupQuickUpload("item", 3);
setupQuickUpload("model", 1);
setupQuickUpload("scene", 1);

// ========== 快速生成：提交 ==========

$("#btn-quick-gen").addEventListener("click", async () => {
  if (quickFiles.item.length === 0) {
    showToast("请上传至少一张物品图片", "error");
    return;
  }

  const btn = $("#btn-quick-gen");
  btn.disabled = true;
  btn.classList.add("loading");

  const prompt = $("#quick-prompt").value.trim();
  const platform = $("#quick-platform").value;
  const duration = $("#quick-duration").value;

  try {
    // 步骤 1：创建物品素材
    showToast("正在分析物品...", "info");
    const itemFormData = new FormData();
    itemFormData.append("description", prompt || "请根据图片分析产品");
    quickFiles.item.forEach((f) => itemFormData.append("images", f));

    const itemRes = await fetch("/api/assets/item", { method: "POST", body: itemFormData });
    if (!itemRes.ok) throw new Error("物品创建失败");
    const itemData = await itemRes.json();

    if (itemData.status === "rejected") {
      showToast(`物品被拒绝: ${itemData.reason}`, "error");
      btn.disabled = false;
      btn.classList.remove("loading");
      return;
    }

    // 步骤 2：创建人物素材
    showToast("正在创建人物...", "info");
    const modelFormData = new FormData();
    modelFormData.append("description", prompt || "适合vlog带货的亲和女生");
    quickFiles.model.forEach((f) => modelFormData.append("images", f));

    const modelRes = await fetch("/api/assets/model", { method: "POST", body: modelFormData });
    if (!modelRes.ok) throw new Error("人物创建失败");
    const modelData = await modelRes.json();

    // 自动选择第一个造型
    if (modelData.look_options && modelData.look_options.length > 0) {
      const selectForm = new FormData();
      selectForm.append("look_index", 0);
      await fetch(`/api/assets/model/${modelData.asset.id}/select`, { method: "POST", body: selectForm });
    }

    // 步骤 3：创建场景素材
    showToast("正在创建场景...", "info");
    const sceneFormData = new FormData();
    sceneFormData.append("description", prompt || "适合vlog拍摄的室内场景");
    quickFiles.scene.forEach((f) => sceneFormData.append("images", f));

    const sceneRes = await fetch("/api/assets/scene", { method: "POST", body: sceneFormData });
    if (!sceneRes.ok) throw new Error("场景创建失败");
    const sceneData = await sceneRes.json();

    // 自动选择第一个场景方案
    if (sceneData.scene_options && sceneData.scene_options.length > 0) {
      const selectForm = new FormData();
      selectForm.append("scene_index", 0);
      await fetch(`/api/assets/scene/${sceneData.asset.id}/select`, { method: "POST", body: selectForm });
    }

    // 步骤 4：提交视频生成
    showToast("正在提交视频生成...", "info");
    const genFormData = new FormData();
    genFormData.append("item_id", itemData.asset.id);
    genFormData.append("model_id", modelData.asset.id);
    genFormData.append("scene_id", sceneData.asset.id);
    genFormData.append("platform", platform);
    genFormData.append("duration", duration);
    genFormData.append("extra_requirements", prompt);

    const genRes = await fetch("/api/generate/v2", { method: "POST", body: genFormData });
    if (!genRes.ok) { const err = await genRes.json(); throw new Error(err.detail || "生成失败"); }
    const genData = await genRes.json();

    currentJobId = genData.job_id;
    resetProgressUI();
    showView("progress");
    startSSE(currentJobId);
    showToast("视频生成任务已创建", "success");

    // 刷新素材库
    refreshAssets();
  } catch (err) {
    showToast(`快速生成失败: ${err.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.classList.remove("loading");
  }
});

// ========== 生成视频视图（模式 A） ==========

function refreshGenerateView() {
  renderGenSelector("item", assets.items, "#gen-item-selector");
  renderGenSelector("model", assets.models, "#gen-model-selector");
  renderGenSelector("scene", assets.scenes, "#gen-scene-selector");
  updateGenButton();
}

function renderGenSelector(type, list, containerSel) {
  const container = $(containerSel);
  if (list.length === 0) {
    container.innerHTML = `<div class="gen-empty"><p>暂无${type === "item" ? "物品" : type === "model" ? "人物" : "场景"}素材</p></div>`;
    return;
  }

  const listDiv = document.createElement("div");
  listDiv.className = "gen-asset-list";

  list.forEach((asset) => {
    const item = document.createElement("div");
    item.className = "gen-asset-item";
    if (selectedAssets[type] && selectedAssets[type].id === asset.id) item.classList.add("selected");

    const imgPath = asset.instruction_image_path || asset.selected_look || asset.selected_scene;
    let imgHtml = "";
    if (imgPath) {
      const filename = imgPath.split("/").pop();
      imgHtml = `<img src="/assets/${asset.id}/${filename}" alt="${escapeHtml(asset.name)}" onerror="this.style.display='none'">`;
    } else {
      const icons = { item: "&#128230;", model: "&#128100;", scene: "&#127968;" };
      imgHtml = `<div class="gen-asset-item-placeholder">${icons[type]}</div>`;
    }

    item.innerHTML = `${imgHtml}<div class="gen-asset-item-name">${escapeHtml(asset.name)}</div>`;

    item.addEventListener("click", () => {
      if (type === "model" && !asset.selected_look) { showToast("请先选择造型", "warning"); return; }
      if (type === "scene" && !asset.selected_scene) { showToast("请先选择方案", "warning"); return; }
      selectedAssets[type] = asset;
      container.querySelectorAll(".gen-asset-item").forEach((el) => el.classList.remove("selected"));
      item.classList.add("selected");
      updateGenButton();
    });

    listDiv.appendChild(item);
  });

  container.innerHTML = "";
  container.appendChild(listDiv);
}

function updateGenButton() {
  $("#btn-generate-v2").disabled = !(selectedAssets.item && selectedAssets.model && selectedAssets.scene);
}

// 模式 A 生成
$("#btn-generate-v2").addEventListener("click", async () => {
  if (!selectedAssets.item || !selectedAssets.model || !selectedAssets.scene) return;

  const btn = $("#btn-generate-v2");
  btn.disabled = true;
  btn.classList.add("loading");

  const formData = new FormData();
  formData.append("item_id", selectedAssets.item.id);
  formData.append("model_id", selectedAssets.model.id);
  formData.append("scene_id", selectedAssets.scene.id);
  formData.append("platform", $("#gen-platform").value);
  formData.append("duration", $("#gen-duration").value);
  formData.append("extra_requirements", $("#gen-extra").value.trim());

  try {
    const res = await fetch("/api/generate/v2", { method: "POST", body: formData });
    if (!res.ok) { const err = await res.json(); throw new Error(err.detail || "请求失败"); }
    const data = await res.json();
    currentJobId = data.job_id;
    resetProgressUI();
    showView("progress");
    startSSE(currentJobId);
    showToast("视频生成任务已创建", "info");
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
  selectedAssets = { item: null, model: null, scene: null };
  quickFiles = { item: [], model: [], scene: [] };
  renderQuickPreview("item");
  renderQuickPreview("model");
  renderQuickPreview("scene");
  updateQuickGenButton();
  showView("home");
  refreshAssets();
});

// ========== 初始化 ==========
document.addEventListener("DOMContentLoaded", () => { refreshAssets(); });
