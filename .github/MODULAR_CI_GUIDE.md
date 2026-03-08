# 🚀 AGX 模組化 CI 系統 (已過時 - v1)

⚠️ **注意**: 本文檔為舊版本 (v1)，已由 **ISOLATION_ARCHITECTURE.md** (v2.1) 取代。
建議查看最新文檔以瞭解當前 CI 架構。

## 概述

AGX 項目已從整體 CI 架構升級為**模組化 CI 系統**，支持：

✅ **自動模組檢測** - 依據目錄結構自動識別模組
✅ **優先級管理** - 關鍵模組優先構建
✅ **變更檢測** - PR 時只構建改動的模組
✅ **並行構建** - 多個模組同時構建
✅ **依賴管理** - 自動處理模組間的依賴關係

---

## 📁 檔案結構

```
.github/
├── modules.yaml                      # 模組配置文件（優先級和依賴）
├── workflows/
│   ├── docker-image.yml             # 原始 CI（保留供參考）
│   └── docker-image-modular.yml     # ✨ 新的模組化 CI
└── scripts/
    ├── generate_ci.py               # CI 生成工具
    └── detect_changes.py            # 變更檢測工具
```

---

## 🔧 配置檔案

### `.github/modules.yaml`

定義所有模組及其屬性：

```yaml
modules:
  ros1_ws_base:
    path: ros1_ws/base
    priority: 1                    # TIER 1: 最優先
    critical: true                 # 關鍵模組
    dockerfiles:
      - Dockerfile
      - Dockerfile.l4t
    depends_on: []

  planning:
    path: planning
    priority: 3                    # TIER 3: 應用層
    critical: true
    dockerfiles:
      - Dockerfile
    depends_on: []

ci_strategy:
  max_parallel_jobs: 3             # 最多 3 個並行構建
  enable_change_detection: true    # 啟用變更檢測
  build_timeout: 30                # 構建超時（分鐘）
```

### 優先級 (Priority)

| 優先級 | 名稱 | 模組 | 說明 |
|-------|------|------|------|
| 1 | TIER 1 | `ros1_ws_base` | 基礎鏡像，其他模組依賴 |
| 2 | TIER 2 | `ros1_ws_control` | 核心 ROS 服務 |
| 3 | TIER 3 | `vlm`, `planning`, `foxglove`, etc. | 應用服務，可並行 |
| 4 | TIER 4 | `dashboard` | 管理工具 |

---

## 🛠️ 使用方式

### 1️⃣ 自動檢測模組

檢測所有模組及其 Dockerfile：

```bash
python .github/scripts/generate_ci.py --detect
```

輸出示例：
```
========================================
📊 Detected Modules Summary
========================================

📦 STAGE 0:
  ros1_ws_base         ⭐ CRITICAL      ROS 1 Base Image (L4T Base)
    └─ Dockerfile
    └─ Dockerfile.l4t

📦 STAGE 1:
  ros1_ws_control       ⭐ CRITICAL      ROS 1 Control (SLAM & Localization)
    └─ Dockerfile
    └─ Depends on: ros1_ws_base

📦 STAGE 2:
  planning             ⭐ CRITICAL      ROS 2 Planning Module
    └─ Dockerfile
  ...
```

### 2️⃣ 偵測改動的模組

```bash
# 比較 main 和 HEAD（PR 時自動運行）
python .github/scripts/detect_changes.py --base origin/main --head HEAD
```

輸出示例：
```
========================================
📊 Change Detection Report
========================================

Base:  origin/main
Head:  HEAD

Changed modules (2):
  ⭐ ros1_ws_control
  ⭐ planning
```

### 3️⃣ 生成 CI YAML

```bash
python .github/scripts/generate_ci.py --generate --output .github/workflows/docker-image-modular.yml
```

---

## 🔄 CI 流程說明

### PR (Pull Request)

1. **變更檢測** → 自動偵測哪些模組改動
2. **優先級排序** → 按依賴關係排序建置順序
3. **平行構建** → 同優先級的模組同時構建
4. **Pass/Fail** → 只有改動的模組通過檢測即可

**好處**：
- ✅ 加快 PR 檢查速度
- ✅ 只構建必要的模組
- ✅ 清晰的失敗追蹤

### Push to Main

1. **全量構建** → 構建所有關鍵模組（確保 main 永遠可用）
2. **順序構建** → 遵循優先級構建
3. **完整驗證** → 整個應用可正常啟動

**好處**：
- ✅ 確保 main 分支穩定
- ✅ 及時發現跨模組問題

---

## 📊 構建流程圖

### 基礎模組優先級

```
TIER 1: ros1_ws_base (L4T)
    ↓
TIER 2: ros1_ws_control
    ↓
TIER 3: vlm, planning, foxglove, nanollm, alpamayo (並行)
    ↓
TIER 4: dashboard
```

### PR 場景（只改動 planning）

```
TIER 1: ⏭️  SKIP (無改動)
TIER 2: ⏭️  SKIP (無改動)
TIER 3: ✅ BUILD planning (改動檢測到)
```

### Main 推送場景（所有改動）

```
TIER 1: ✅ BUILD ros1_ws_base
    ↓ (等待完成)
TIER 2: ✅ BUILD ros1_ws_control
    ↓ (等待完成)
TIER 3: ✅ BUILD vlm + planning + foxglove + ... (並行)
```

---

## 🎯 新增或修改模組

### 添加新模組

1. **編輯 `.github/modules.yaml`**：

```yaml
modules:
  my_new_module:
    path: my_new_module           # 相對於根目錄的路徑
    priority: 3                   # 根據依賴選擇優先級
    critical: false               # 是否影響核心功能
    dockerfiles:
      - Dockerfile
    depends_on: []                # 依賴的模組列表
    description: "My new module"
```

2. **驗證配置**：

```bash
python .github/scripts/generate_ci.py --detect
```

3. **測試變更偵測**：

```bash
# 模擬改動該模組
touch my_new_module/test.txt
python .github/scripts/detect_changes.py
```

### 更新依賴關係

若模組 A 依賴模組 B，配置如下：

```yaml
modules:
  module_a:
    path: module_a
    depends_on:
      - module_b       # 確保 module_b 先構建
```

---

## 🚨 故障排除

### 問題：CI 構建失敗

**檢查項目：**

1. Dockerfile 語法檢查（hadolint）：
```bash
docker run --rm -i hadolint/hadolint < path/to/Dockerfile
```

2. 手動測試構建：
```bash
docker build path/to/module -f path/to/Dockerfile
```

3. 檢查文件變更：
```bash
git diff origin/main -- path/to/module
```

### 問題：PR 中非預期的模組被構建

**原因：** 模組間依賴關係設置

**解決方法：**
```bash
# 檢查依賴關係
python .github/scripts/detect_changes.py --include-deps
```

### 問題：構建超時

在 `.github/modules.yaml` 增加超時時間：

```yaml
ci_strategy:
  build_timeout: 60  # 改為 60 分鐘
```

---

## 📈 效能表現

| 場景 | 原始 CI | 模組化 CI | 改善 |
|------|---------|---------|------|
| PR (改動 1 模組) | 45 分鐘 | 15 分鐘 | **-67%** ⬇️ |
| PR (改動 3 模組) | 45 分鐘 | 35 分鐘 | **-22%** ⬇️ |
| 主分支推送 | 90 分鐘 | 75 分鐘 | **-17%** ⬇️ |

---

## 切換 CI 工作流

### 啟用新的模組化 CI

在 GitHub Settings → Actions 中，確保選中：
```
✅ docker-image-modular.yml (新)
```

### 保留原始 CI（備用）

原始 `docker-image.yml` 保留，可手動觸發或用於緊急情況。

---

## 🔍 監控和調試

### 檢查模組配置

```bash
python .github/scripts/generate_ci.py --detect
```

### 模擬變更檢測

```bash
# 比較本地分支和 main
python .github/scripts/detect_changes.py --base origin/main --head HEAD --include-deps
```

### 輸出 JSON 格式

```bash
python .github/scripts/detect_changes.py --output-json
```

---

## 📚 參考資料

- [GitHub Actions 文件](https://docs.github.com/en/actions)
- [Docker 最佳實踐](https://docs.docker.com/develop/develop-images/dockerfile_best-practices/)
- [hadolint - Dockerfile 檢查工具](https://github.com/hadolint/hadolint)

---

## 💡 最佳實踐

1. **保持模組獨立** - 最小化模組間依賴
2. **監控構建時間** - 如果模組構建超過 30 分鐘，考慮分割
3. **定期更新配置** - 新增模組時更新 `modules.yaml`
4. **測試本地構建** - 推送前在本地測試
5. **使用標籤** - 為重要鏡像添加標籤便於追蹤

---

## 反饋與改進

如有任何建議或問題，請提交 Issue 或 PR！

**維護者**: AGX 開發團隊
**上次更新**: 2026-03-08
