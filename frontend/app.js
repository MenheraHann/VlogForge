/**
 * VlogForge 前端交互逻辑
 * 三步向导：输入 → 生成中 → 结果
 * 使用 SSE 实时更新进度
 */

// ========== DOM 元素 ==========
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const stepInput = $("#step-input");
const stepProgress = $("#step-progress");
const stepResult = $("#step-result");

const form = $("#generate-form");
const btnGenerate = $("#btn-generate");
const btnBack = $("#btn-back");
const btnNew = $("#btn-new");

const uploadZone = $("#upload-zone");
const fileInput = $("#product_images");
const uploadPlaceholder = $("#upload-placeholder");
const uploadPreview = $("#upload-preview");

const progressFill = $("#progress-fill");
const progressMessage = $("#progress-message");
const scriptPreview = $("#script-preview");
const scriptTitle = $("#script-title");
const styleGuide = $("#style-guide");
const segmentsList = $("#segments-list");
const storyboardPreview = $("#storyboard-preview");
const storyboardGrid = $("#storyboard-grid");

const resultVideo = $("#result-video");
const btnDownload = $("#btn-download");
const resultTitle = $("#result-title");
const resultSegments = $("#result-segments");

// ========== 状态 ==========
let currentJobId = null;
let eventSource = null;
let uploadedFiles = [];

// 阶段映射（后端 status → 前端显示）
const STAGE_ORDER = ["script", "images", "videos", "qa", "stitching"];
const STATUS_TO_STAGE = {
  pending: null,
  script: "script",
  images: "images",
  videos: "videos",
  qa: "qa",
  stitching: "stitching",
  completed: "completed",
  failed: "failed",
};

// ========== 步骤切换 ==========
function showStep(stepId) {
  $$(".step").forEach((s) => s.classList.remove("active"));
  $(`#step-${stepId}`).classList.add("active");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

// ========== 图片上传 ==========
uploadZone.addEventListener("click", () => fileInput.click());

uploadZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  uploadZone.classList.add("drag-over");
});

uploadZone.addEventListener("dragleave", () => {
  uploadZone.classList.remove("drag-over");
});

uploadZone.addEventListener("drop", (e) => {
  e.preventDefault();
  uploadZone.classList.remove("drag-over");
  const files = Array.from(e.dataTransfer.files).filter((f) =>
    f.type.startsWith("image/")
  );
  addFiles(files);
});

fileInput.addEventListener("change", () => {
  addFiles(Array.from(fileInput.files));
  fileInput.value = "";
});

function addFiles(files) {
  // 最多 3 张
  const remaining = 3 - uploadedFiles.length;
  const toAdd = files.slice(0, remaining);
  uploadedFiles.push(...toAdd);
  renderUploadPreview();
}

function removeFile(index) {
  uploadedFiles.splice(index, 1);
  renderUploadPreview();
}

function renderUploadPreview() {
  if (uploadedFiles.length === 0) {
    uploadPlaceholder.style.display = "flex";
    uploadPreview.innerHTML = "";
    return;
  }
  uploadPlaceholder.style.display = "none";
  uploadPreview.innerHTML = "";

  uploadedFiles.forEach((file, i) => {
    const wrapper = document.createElement("div");
    wrapper.className = "img-wrapper";

    const img = document.createElement("img");
    img.src = URL.createObjectURL(file);
    img.alt = file.name;

    const removeBtn = document.createElement("button");
    removeBtn.className = "remove-img";
    removeBtn.textContent = "\u00D7";
    removeBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      removeFile(i);
    });

    wrapper.appendChild(img);
    wrapper.appendChild(removeBtn);
    uploadPreview.appendChild(wrapper);
  });
}

// ========== 表单提交 ==========
form.addEventListener("submit", async (e) => {
  e.preventDefault();

  if (uploadedFiles.length === 0) {
    alert("请上传至少一张产品参考图");
    return;
  }

  // 构建 FormData
  const formData = new FormData();
  formData.append("product_type", $("#product_type").value);
  formData.append("product_usage", $("#product_usage").value);
  formData.append("platform", $("#platform").value);
  formData.append("duration", $("#duration").value);
  formData.append("selling_point", $("#selling_point").value);
  uploadedFiles.forEach((f) => formData.append("product_images", f));

  // 禁用按钮
  btnGenerate.disabled = true;
  btnGenerate.classList.add("loading");

  try {
    const res = await fetch("/api/generate", {
      method: "POST",
      body: formData,
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "请求失败");
    }

    const data = await res.json();
    currentJobId = data.job_id;

    // 切到进度页
    resetProgressUI();
    showStep("progress");
    startSSE(currentJobId);
  } catch (err) {
    alert(`提交失败：${err.message}`);
  } finally {
    btnGenerate.disabled = false;
    btnGenerate.classList.remove("loading");
  }
});

// ========== 进度页 UI 重置 ==========
function resetProgressUI() {
  progressFill.style.width = "0%";
  progressMessage.textContent = "准备中...";
  scriptPreview.style.display = "none";
  scriptTitle.textContent = "";
  styleGuide.innerHTML = "";
  segmentsList.innerHTML = "";
  storyboardPreview.style.display = "none";
  storyboardGrid.innerHTML = "";

  // 重置流水线点
  $$(".pipeline-step").forEach((s) => {
    s.classList.remove("active", "done");
  });
  $$(".pipeline-line").forEach((l) => {
    l.classList.remove("done");
  });
}

// ========== SSE 实时进度 ==========
function startSSE(jobId) {
  if (eventSource) {
    eventSource.close();
  }

  eventSource = new EventSource(`/api/stream/${jobId}`);

  eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    updateProgress(data);

    // 完成或失败时关闭 SSE
    if (data.status === "completed" || data.status === "failed") {
      eventSource.close();
      eventSource = null;

      if (data.status === "completed" && data.final_video_url) {
        showResult(data);
      }
    }
  };

  eventSource.onerror = () => {
    // SSE 断开时改用轮询
    eventSource.close();
    eventSource = null;
    startPolling(jobId);
  };
}

function startPolling(jobId) {
  const interval = setInterval(async () => {
    try {
      const res = await fetch(`/api/status/${jobId}`);
      const data = await res.json();
      updateProgress(data);

      if (data.status === "completed" || data.status === "failed") {
        clearInterval(interval);
        if (data.status === "completed" && data.final_video_url) {
          showResult(data);
        }
      }
    } catch {
      // 网络错误，继续轮询
    }
  }, 2000);
}

// ========== 更新进度 UI ==========
function updateProgress(data) {
  // 进度条
  const pct = Math.round((data.progress || 0) * 100);
  progressFill.style.width = `${pct}%`;
  progressMessage.textContent = data.message || "";

  // 流水线阶段高亮
  const currentStage = STATUS_TO_STAGE[data.status];
  if (currentStage && currentStage !== "completed" && currentStage !== "failed") {
    updatePipelineStage(currentStage);
  }
  if (data.status === "completed") {
    // 全部标记完成
    STAGE_ORDER.forEach((stage) => markStageDone(stage));
  }

  // 脚本预览
  if (data.script && scriptPreview.style.display === "none") {
    renderScript(data.script);
  }

  // 分镜图预览
  if (data.storyboard_urls && data.storyboard_urls.length > 0) {
    renderStoryboard(data.storyboard_urls);
  }
}

function updatePipelineStage(stage) {
  const idx = STAGE_ORDER.indexOf(stage);
  if (idx === -1) return;

  const steps = $$(".pipeline-step");
  const lines = $$(".pipeline-line");

  steps.forEach((s, i) => {
    if (i < idx) {
      s.classList.remove("active");
      s.classList.add("done");
    } else if (i === idx) {
      s.classList.remove("done");
      s.classList.add("active");
    } else {
      s.classList.remove("active", "done");
    }
  });

  lines.forEach((l, i) => {
    if (i < idx) {
      l.classList.add("done");
    } else {
      l.classList.remove("done");
    }
  });
}

function markStageDone(stage) {
  const step = $(`.pipeline-step[data-stage="${stage}"]`);
  if (step) {
    step.classList.remove("active");
    step.classList.add("done");
  }
}

// ========== 渲染脚本 ==========
function renderScript(script) {
  scriptPreview.style.display = "block";
  scriptTitle.textContent = `\u300C${script.title}\u300D`;

  // 风格指南
  const guide = script.style_guide;
  styleGuide.innerHTML = `
    <div class="style-guide-item">
      <div class="label">\u4EBA\u7269</div>
      <div class="value">${guide.person_description}</div>
    </div>
    <div class="style-guide-item">
      <div class="label">\u573A\u666F</div>
      <div class="value">${guide.scene_description}</div>
    </div>
    <div class="style-guide-item">
      <div class="label">\u98CE\u683C</div>
      <div class="value">${guide.visual_style}</div>
    </div>
    <div class="style-guide-item">
      <div class="label">\u5149\u7EBF</div>
      <div class="value">${guide.lighting}</div>
    </div>
  `;

  // 分段
  segmentsList.innerHTML = "";
  script.segments.forEach((seg) => {
    const item = document.createElement("div");
    item.className = `segment-item${seg.needs_product ? " has-product" : ""}`;
    item.innerHTML = `
      <div class="segment-header">
        <span class="segment-number">\u5206\u6BB5 ${seg.segment_id}</span>
        ${seg.needs_product ? '<span class="segment-badge">\u4EA7\u54C1\u690D\u5165</span>' : ""}
      </div>
      <div class="segment-narration">${escapeHtml(seg.narration)}</div>
      <div class="segment-action">${escapeHtml(seg.action_description)}</div>
    `;
    segmentsList.appendChild(item);
  });
}

// ========== 渲染分镜图 ==========
function renderStoryboard(urls) {
  storyboardPreview.style.display = "block";
  storyboardGrid.innerHTML = "";
  urls.forEach((url, i) => {
    const img = document.createElement("img");
    img.src = url;
    img.alt = `\u5E27 ${i + 1}`;
    img.loading = "lazy";
    storyboardGrid.appendChild(img);
  });
}

// ========== 结果页 ==========
function showResult(data) {
  resultVideo.src = data.final_video_url;
  btnDownload.href = data.final_video_url;

  if (data.script) {
    resultTitle.textContent = `\u300C${data.script.title}\u300D`;
    resultSegments.innerHTML = "";
    data.script.segments.forEach((seg) => {
      const item = document.createElement("div");
      item.className = `segment-item${seg.needs_product ? " has-product" : ""}`;
      item.innerHTML = `
        <div class="segment-header">
          <span class="segment-number">\u5206\u6BB5 ${seg.segment_id}</span>
          ${seg.needs_product ? '<span class="segment-badge">\u4EA7\u54C1\u690D\u5165</span>' : ""}
        </div>
        <div class="segment-narration">${escapeHtml(seg.narration)}</div>
      `;
      resultSegments.appendChild(item);
    });
  }

  showStep("result");
}

// ========== 返回 / 新建 ==========
btnBack.addEventListener("click", () => {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
  showStep("input");
});

btnNew.addEventListener("click", () => {
  currentJobId = null;
  form.reset();
  uploadedFiles = [];
  renderUploadPreview();
  showStep("input");
});

// ========== 工具函数 ==========
function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
