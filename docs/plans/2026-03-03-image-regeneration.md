# 单张图片重新生成功能 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 用户在详情弹窗中可以对物品缩略图/三视图、人物肖像进行单张重新生成

**Architecture:** 新增统一的 `POST /api/assets/{id}/regenerate-image` 端点，ada_agent 新增 `regenerate_single_image()` 函数提取单张生成逻辑。前端在 `renderImagesRow()` 中每张图片下方添加"重新生成"按钮，点击后显示 loading 蒙层，轮询 asset 状态直到图片更新。

**Tech Stack:** FastAPI (backend), vanilla JS (frontend), Gemini image gen API

---

## Task 1: 后端 — ADA 新增单张图片重新生成函数

**Files:**
- Modify: `backend/agents/ada_agent.py`

**Step 1: 在 ada_agent.py 中新增 `regenerate_item_image()` 函数**

在 `_load_original_images` 函数之后添加：

```python
async def regenerate_item_image(
    asset: ItemAsset,
    image_type: str,  # "thumbnail" | "three_view"
) -> str:
    """
    重新生成物品的单张图片（缩略图或三视图）。
    使用原始产品图做 img2img 参考，失败则降级为 text2img。
    返回新图片路径。
    """
    from backend.prompts.ada_prompts import ADA_ITEM_THUMBNAIL_PROMPT, ADA_ITEM_THREE_VIEW_PROMPT

    asset_dir = os.path.join(ASSETS_DIR, asset.id)
    os.makedirs(asset_dir, exist_ok=True)

    ref_images = _load_original_images(asset)

    if image_type == "thumbnail":
        prompt = ADA_ITEM_THUMBNAIL_PROMPT.format(
            name=asset.name, full_description=asset.full_description,
        )
        filename = "thumbnail.png"
    elif image_type == "three_view":
        prompt = ADA_ITEM_THREE_VIEW_PROMPT.format(
            name=asset.name, full_description=asset.full_description,
        )
        filename = "three_view.png"
    else:
        raise ValueError(f"未知的图片类型: {image_type}")

    logger.info(f"[ADA] 重新生成物品图片: {asset.id}, type={image_type}")

    # 优先 img2img，降级 text2img
    try:
        if ref_images:
            img_bytes = await image_to_image(ref_images, prompt, aspect_ratio="1:1")
        else:
            img_bytes = await text_to_image(prompt, aspect_ratio="1:1")
    except Exception:
        logger.warning(f"[ADA] {image_type} img2img 失败，降级 text2img")
        img_bytes = await text_to_image(prompt, aspect_ratio="1:1")

    path = os.path.join(asset_dir, filename)
    save_image(img_bytes, path)
    logger.info(f"[ADA] 物品图片重新生成完成: {path}")
    return path
```

**Step 2: 验证语法**

Run: `python3 -c "import ast; ast.parse(open('backend/agents/ada_agent.py').read()); print('OK')"`

**Step 3: Commit**

```bash
git add backend/agents/ada_agent.py
git commit -m "feat: add regenerate_item_image() to ADA agent"
```

---

## Task 2: 后端 — 新增统一图片重新生成 API 端点

**Files:**
- Modify: `backend/main.py`

**Step 1: 在 main.py 中添加 import 和端点**

在 ada_agent import 中添加 `regenerate_item_image`：
```python
from backend.agents.ada_agent import (
    analyze_item,
    confirm_item,
    create_item_asset,
    create_model_asset,
    quickstart_parse,
    regenerate_item_image,  # 新增
)
```

在 `# ========== 人物：重新生成` 区域之前，添加新端点：

```python
# ========== 素材图片：单张重新生成 ==========

async def _regenerate_item_image_task(
    asset_id: str,
    image_type: str,
    asset_manager: AssetManager,
):
    """后台异步重新生成物品的单张图片"""
    try:
        asset = asset_manager.get_item(asset_id)
        if not asset:
            logger.error(f"[Item] {asset_id} 已被删除，重新生成结果丢弃")
            return

        new_path = await regenerate_item_image(asset, image_type)

        # 更新对应字段
        if image_type == "thumbnail":
            asset.thumbnail_image = new_path
        elif image_type == "three_view":
            asset.three_view_image = new_path

        asset.status = AssetStatus.CONFIRMED
        asset_manager.save_item(asset)
        logger.info(f"[Item] {asset_id} 图片 {image_type} 重新生成完成")

    except Exception as e:
        logger.error(f"[Item] {asset_id} 图片重新生成失败: {e}", exc_info=True)
        asset = asset_manager.get_item(asset_id)
        if asset:
            asset.status = AssetStatus.CONFIRMED  # 保持 CONFIRMED，图片生成失败不影响素材状态
            asset_manager.save_item(asset)


@app.post("/api/assets/{asset_id}/regenerate-image")
async def regenerate_asset_image(
    asset_id: str,
    image_type: str = Form(..., description="要重新生成的图片类型: thumbnail / three_view / portrait"),
):
    """
    v19: 单张图片重新生成。
    物品：thumbnail / three_view（使用原始产品图做 img2img 参考）
    人物：portrait（生成新的 look 选项让用户选择）
    """
    # 物品
    if asset_id.startswith("item_"):
        item = asset_manager.get_item(asset_id)
        if not item:
            raise HTTPException(status_code=404, detail=f"物品素材 {asset_id} 不存在")
        if image_type not in ("thumbnail", "three_view"):
            raise HTTPException(status_code=400, detail=f"物品不支持的图片类型: {image_type}")
        if not item.full_description:
            raise HTTPException(status_code=400, detail="缺少 full_description，无法重新生成")

        # 后台异步重新生成
        asyncio.create_task(
            _regenerate_item_image_task(
                asset_id=asset_id,
                image_type=image_type,
                asset_manager=asset_manager,
            )
        )

        return {
            "status": "ok",
            "asset_id": asset_id,
            "image_type": image_type,
            "message": f"正在重新生成{image_type}，请稍候",
        }

    # 人物：复用已有的重新生成逻辑（生成新 look 让用户选择）
    elif asset_id.startswith("model_"):
        model = asset_manager.get_model(asset_id)
        if not model:
            raise HTTPException(status_code=404, detail=f"人物素材 {asset_id} 不存在")
        if image_type != "portrait":
            raise HTTPException(status_code=400, detail=f"人物不支持的图片类型: {image_type}")
        if not model.full_description:
            raise HTTPException(status_code=400, detail="缺少 full_description，无法重新生成")

        # 设为 GENERATING，复用已有的人物重新生成流程
        model.status = AssetStatus.GENERATING
        asset_manager.save_model(model)

        ref_images = _load_model_reference_images(model)
        asyncio.create_task(
            _regenerate_model_task(
                model_id=asset_id,
                description=model.full_description,
                reference_images=ref_images if ref_images else None,
                asset_manager=asset_manager,
            )
        )

        return {
            "status": "ok",
            "asset_id": asset_id,
            "image_type": image_type,
            "message": "正在重新生成人物形象，请稍候",
        }

    else:
        raise HTTPException(status_code=400, detail=f"未知的素材 ID 格式: {asset_id}")
```

**Step 2: 验证语法**

Run: `python3 -c "import ast; ast.parse(open('backend/main.py').read()); print('OK')"`

**Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat: add POST /api/assets/{id}/regenerate-image endpoint"
```

---

## Task 3: 前端 — 详情弹窗图片下方添加重新生成按钮

**Files:**
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css`

**Step 1: 修改 `renderImagesRow()` 添加重新生成按钮**

将 `app.js` 中 `renderImagesRow` 函数替换为：

```javascript
function renderImagesRow(asset, fields) {
  let html = '<div class="detail-images-row">';
  for (const { field, label } of fields) {
    const url = getAssetImageUrl(asset, field);
    // 映射 field → image_type 参数
    const imageTypeMap = {
      "thumbnail_image": "thumbnail",
      "three_view_image": "three_view",
      "portrait_image": "portrait",
    };
    const imageType = imageTypeMap[field] || "";
    if (url) {
      html += `<div class="detail-image-item" data-asset-id="${asset.id}" data-image-type="${imageType}" data-field="${field}">
        <div class="detail-image-wrapper">
          <img src="${url}" alt="${escapeHtml(label)}" onerror="this.parentElement.style.display='none'">
          <div class="detail-image-loading" style="display:none;"><span class="spinner-inline"></span></div>
        </div>
        <div class="detail-image-label">${escapeHtml(label)}</div>
        ${imageType ? `<button class="btn-regen-image" data-asset-id="${asset.id}" data-image-type="${imageType}" data-field="${field}">${t('button.regenerate') || '重新生成'}</button>` : ''}
      </div>`;
    }
  }
  html += '</div>';
  return html;
}
```

**Step 2: 在 `openDetailModal` 函数的末尾绑定重新生成按钮事件**

在 `body.innerHTML = content;` 之后、`modal.style.display = "flex";` 之前添加：

```javascript
  // v19: 绑定图片重新生成按钮
  body.querySelectorAll(".btn-regen-image").forEach(btn => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const assetId = btn.dataset.assetId;
      const imageType = btn.dataset.imageType;
      const field = btn.dataset.field;
      const imageItem = btn.closest(".detail-image-item");
      const loadingOverlay = imageItem.querySelector(".detail-image-loading");

      // 显示 loading 蒙层，禁用按钮
      if (loadingOverlay) loadingOverlay.style.display = "flex";
      btn.disabled = true;
      btn.textContent = t('button.regenerating') || '重新生成中...';

      try {
        const formData = new FormData();
        formData.append("image_type", imageType);
        const res = await fetch(`/api/assets/${assetId}/regenerate-image`, {
          method: "POST",
          body: formData,
        });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "重新生成失败");
        }

        // 人物：关闭详情弹窗，打开审核弹窗让用户选择
        if (assetId.startsWith("model_")) {
          modal.style.display = "none";
          showToast(t('modelReview.regenerateSuccess') || "正在重新生成，请稍候...", "info");
          await refreshAssets();
          startGeneratingPollIfNeeded();
          // 轮询等待人物生成完成后自动弹出审核弹窗
          startModelReviewPoll(assetId);
          return;
        }

        // 物品：轮询等待图片更新
        let retries = 0;
        const maxRetries = 30;
        const pollInterval = setInterval(async () => {
          retries++;
          try {
            const assetRes = await fetch(`/api/assets/${assetId}`);
            if (assetRes.ok) {
              const assetData = await assetRes.json();
              const newUrl = assetData[field];
              if (newUrl) {
                const img = imageItem.querySelector("img");
                if (img) img.src = `/assets/${assetId}/${newUrl.split('/').pop()}?t=${Date.now()}`;
              }
              // 检查是否还在生成中（物品不改 status，用时间戳判断）
              if (retries >= 3) {
                clearInterval(pollInterval);
                if (loadingOverlay) loadingOverlay.style.display = "none";
                btn.disabled = false;
                btn.textContent = t('button.regenerate') || '重新生成';
                showToast(t('toast.imageRegenSuccess') || "图片已重新生成", "success");
                await refreshAssets();
              }
            }
          } catch {}
          if (retries >= maxRetries) {
            clearInterval(pollInterval);
            if (loadingOverlay) loadingOverlay.style.display = "none";
            btn.disabled = false;
            btn.textContent = t('button.regenerate') || '重新生成';
            showToast(t('toast.imageRegenFailed') || "图片重新生成超时", "error");
          }
        }, 2000);

      } catch (err) {
        if (loadingOverlay) loadingOverlay.style.display = "none";
        btn.disabled = false;
        btn.textContent = t('button.regenerate') || '重新生成';
        showToast(err.message, "error");
      }
    });
  });
```

**Step 3: 在 styles.css 中添加样式**

在 `.detail-image-label` 样式之后添加：

```css
/* v19: 图片重新生成按钮 */
.detail-image-wrapper {
  position: relative;
}
.detail-image-loading {
  position: absolute; top: 0; left: 0; right: 0; bottom: 0;
  display: flex; align-items: center; justify-content: center;
  background: rgba(0,0,0,0.5); border-radius: var(--radius-sm);
}
.btn-regen-image {
  width: 100%; padding: 0.3rem 0; margin-top: 0.25rem;
  font-size: 0.7rem; color: var(--text-secondary);
  background: rgba(255,255,255,0.06); border: 1px solid var(--border-color);
  border-radius: var(--radius-sm); cursor: pointer;
  transition: all 0.2s;
}
.btn-regen-image:hover {
  background: rgba(255,255,255,0.12); color: var(--text-primary);
}
.btn-regen-image:disabled {
  opacity: 0.5; cursor: not-allowed;
}
```

**Step 4: Commit**

```bash
git add frontend/app.js frontend/styles.css
git commit -m "feat: add per-image regenerate button in detail modal"
```

---

## Task 4: 前端 — i18n 翻译键

**Files:**
- Modify: `frontend/i18n/zh-CN.json`
- Modify: `frontend/i18n/en.json`
- Modify: `frontend/i18n/ja.json`
- Modify: `frontend/i18n/ko.json`
- Modify: `frontend/i18n/es.json`
- Modify: `frontend/i18n/pt.json`

**Step 1: 在 6 个语言文件的 button 和 toast 区域添加新键**

需要添加的键（如果不存在）：
- `button.regenerate` — 重新生成
- `button.regenerating` — 重新生成中...（已存在则跳过）
- `toast.imageRegenSuccess` — 图片已重新生成
- `toast.imageRegenFailed` — 图片重新生成超时

各语言翻译：
| Key | zh-CN | en | ja | ko | es | pt |
|-----|-------|----|----|----|----|-----|
| button.regenerate | 重新生成 | Regenerate | 再生成 | 재생성 | Regenerar | Regenerar |
| toast.imageRegenSuccess | 图片已重新生成 | Image regenerated | 画像を再生成しました | 이미지가 재생성되었습니다 | Imagen regenerada | Imagem regenerada |
| toast.imageRegenFailed | 图片重新生成超时 | Image regeneration timed out | 画像の再生成がタイムアウトしました | 이미지 재생성 시간 초과 | Regeneración de imagen expiró | Regeneração de imagem expirou |

**Step 2: Commit**

```bash
git add frontend/i18n/*.json
git commit -m "feat: add i18n keys for image regeneration"
```

---

## Task 5: 补全 PRD

**Files:**
- Modify: `docs/PRD.md`

**Step 1: 在 PRD 的素材管理部分添加图片重新生成功能描述**

添加以下内容：

```markdown
### 5.x 单张图片重新生成（v19）

**用户故事**：作为用户，我希望在查看素材详情时，能够对不满意的单张图片重新生成，而不需要重新创建整个素材。

**物品**：
- 详情弹窗中，缩略图和三视图下方各有一个「重新生成」按钮
- 点击后该图片显示 loading 蒙层，按钮变为"重新生成中..."
- 后台使用原始上传图做 img2img 参考重新生成该图片
- 生成完成后自动替换显示，物品保持 CONFIRMED 状态

**人物**：
- 详情弹窗中，肖像图下方有「重新生成」按钮
- 点击后关闭详情弹窗，进入人物审核流程
- 后台生成新的 look 选项
- 生成完成后自动弹出审核弹窗让用户确认/继续调整

**API**：`POST /api/assets/{id}/regenerate-image`
- 参数：`image_type` = thumbnail | three_view | portrait
- 物品：异步生成单张图，不改变素材状态
- 人物：复用已有的人物重新生成流程
```

**Step 2: Commit**

```bash
git add docs/PRD.md
git commit -m "docs: add image regeneration feature to PRD"
```

---

## 执行顺序

Task 1 → Task 2 → Task 3 → Task 4 → Task 5

Task 1-2 是后端，Task 3-4 是前端，Task 5 是文档。Task 1 和 2 有依赖（2 import 1 的函数），其余互相独立。
