# 🚀 AGX 模組化 CI - 快速開始

**版本**: 2.0 (Reusable Workflows)

## ⚠️ 重要注意事項

### 應用層模組
- ✅ **支援的模組**: vlm, planning, foxglove, nanollm, cosmos, dashboard
- 各模組在 `.github/modules.yaml` 中定義

### ARM 架構支援
- ✅ **已啟用 QEMU** 用於 ARM64 模擬
- ✅ 支援 `linux/amd64` 和 `linux/arm64` 平台
- 💡 ROS 基礎模組會使用 QEMU 進行 ARM64 構建

---

## 5 分鐘快速設置

### 1️⃣ 檢查現有模組

```bash
# 自動檢測所有模組
python .github/scripts/generate_ci.py --detect
```

預期輸出：
```
✅ 所有模組自動檢測完成
📦 共 9 個模組，3 個優先級
⭐ 8 個關鍵模組
⚪ 1 個可選模組
```

### 2️⃣ 測試變更檢測

```bash
# 偵測已改動的模組
python .github/scripts/detect_changes.py
```

預期輸出：
```
📊 Change Detection Report
Changed modules: ros1_ws_base, planning, ...
```

### 3️⃣ 驗證 CI 配置

```bash
# 生成 CI YAML 並驗證語法
python .github/scripts/generate_ci.py --generate
```

### 4️⃣ 推送到 GitHub

```bash
git add .github/
git commit -m "feat: migrate to modular CI system

- Add module configuration (modules.yaml)
- Implement module auto-detection (generate_ci.py)
- Add change detection (detect_changes.py)
- New modular CI workflow (docker-image-modular.yml)
- Comprehensive documentation

Co-Authored-By: Claude <noreply@anthropic.com>"

git push origin feature/nano-llm
```

---

## 📋 檢查清單

### 配置驗證

- [ ] `.github/modules.yaml` 包含所有模組
- [ ] 優先級順序合理
- [ ] 關鍵模組標記為 `critical: true`
- [ ] 依賴關係配置正確

### 腳本驗證

- [ ] `generate_ci.py` 能正確檢測所有模組
- [ ] `detect_changes.py` 能正確識別改動
- [ ] CI YAML 生成無錯誤

### GitHub 驗證

- [ ] Actions 設定已啟用 `docker-image-modular.yml`
- [ ] 分支保護規則已更新
- [ ] PR 檢查通過

---

## 🔧 關鍵配置

### `.github/modules.yaml` 結構

```yaml
modules:
  # 每個模組必須有以下欄位
  module_name:
    path:         # 模組根目錄
    priority:     # 1(最優先) 到 5
    critical:     # true/false - 影響核心功能
    dockerfiles:  # 模組中的 Dockerfile 列表
    depends_on:   # 依賴的模組列表
    description:  # 模組描述

ci_strategy:
  max_parallel_jobs: 3    # 最多 3 個並行構建
  build_timeout: 30       # 構建超時（分鐘）
  enable_change_detection: true  # 啟用變更檢測
```

### 優先級說明

| 優先級 | 用途 | 構建時間 |
|-------|------|---------|
| 1 | 基礎鏡像 | 第一批 |
| 2 | 核心服務 | 第二批（等待 TIER 1） |
| 3 | 應用層 | 第三批（並行） |
| 4 | 管理工具 | 第四批 |
| 5 | 可選服務 | 最後一批 |

---

## 🎯 常見工作流

### 添加新模組

1. **創建 Dockerfile**
```bash
mkdir my_module
echo "FROM ubuntu:20.04" > my_module/Dockerfile
```

2. **編輯 modules.yaml**
```yaml
modules:
  my_module:
    path: my_module
    priority: 3
    critical: false
    dockerfiles:
      - Dockerfile
    depends_on: []
```

3. **驗證**
```bash
python .github/scripts/generate_ci.py --detect
```

### 修改依賴關係

```yaml
modules:
  module_a:
    path: module_a
    depends_on:
      - module_b  # 確保 module_b 先構建
```

### 修改優先級

```yaml
modules:
  critical_module:
    priority: 2   # 更高優先級（數字越小越優先）
```

---

## 🧪 本地測試

### 驗證 Dockerfile 語法

```bash
# 檢查特定模組的 Dockerfile
docker run --rm -i hadolint/hadolint < ros1_ws/base/Dockerfile

# 檢查所有模組
for dir in */; do
  if [ -f "$dir/Dockerfile" ]; then
    echo "Checking $dir..."
    docker run --rm -i hadolint/hadolint < "$dir/Dockerfile"
  fi
done
```

### 測試本地構建

```bash
# 構建特定模組
docker build ros1_ws/base -f ros1_ws/base/Dockerfile -t agx:ros1_ws_base

# 檢查變更偵測
python .github/scripts/detect_changes.py --base origin/main --head HEAD --output-json
```

### ARM 架構測試

```bash
# 檢查 QEMU 支援
docker run --rm --privileged multiarch/qemu-user-static --reset -p yes

# 構建 ARM64 鏡像（使用 QEMU 模擬）
docker buildx build --platform linux/arm64 \
  ros1_ws/base \
  -f ros1_ws/base/Dockerfile \
  -t agx:ros1_ws_base-arm64 \
  --load
```

---

## 📊 效能對比

### 原始 CI
- 檢查所有 Dockerfile（無論是否改動）
- 順序構建所有模組
- PR 檢查時間：45+ 分鐘

### 新模組化 CI
- 只檢查改動的 Dockerfile
- 並行構建獨立模組
- PR 檢查時間：15-35 分鐘（取決於改動範圍）

---

## 🐛 除錯

### 腳本無法運作

```bash
# 檢查 Python 版本
python --version  # 須 >= 3.8

# 安裝依賴
pip install pyyaml

# 運行詳細輸出
python -u .github/scripts/generate_ci.py --detect -v
```

### 模組未被檢測到

```bash
# 檢查模組路徑
ls -la my_module/

# 檢查 Dockerfile 名稱
ls -la my_module/Dockerfile*

# 確認配置
grep -A5 "my_module:" .github/modules.yaml
```

### 變更檢測失效

```bash
# 檢查 git 狀態
git status
git diff origin/main -- my_module/

# 手動測試
python .github/scripts/detect_changes.py --base origin/main --head HEAD --output-json
```

### ARM 架構問題

**症狀**: ROS 模組在 ARM64 上構建失敗

**解決方案**:
```bash
# 確認 QEMU 已安裝
docker run --rm --privileged tonistiigi/binfmt --install arm64

# 檢查 Buildx 配置
docker buildx ls

# 重新嘗試 ARM64 構建
docker buildx build --platform linux/arm64 \
  ros1_ws/base -f ros1_ws/base/Dockerfile
```

---

## 📚 進階主題

### 自定義 CI 邏輯

編輯 `.github/workflows/docker-image-modular.yml` 的步驟段落：

```yaml
- name: Build Dockerfile
  run: |
    # 自定義構建命令
    docker build ${{ matrix.module }} \
      --tag "ghcr.io/${{ github.repository }}/${{ matrix.module }}"
```

### 自動推送鏡像

```yaml
- name: Push to Registry
  if: github.event_name == 'push' && github.ref == 'refs/heads/main'
  run: |
    docker push ghcr.io/${{ github.repository }}/${{ matrix.module }}
```

### 條件性構建

```yaml
- name: Build if critical
  if: ${{ matrix.include.critical == true }}
  run: docker build ...
```

---

## 💡 最佳實踐

✅ **一路暢通**
- 保持模組獨立，最小化依賴
- 定期更新 `modules.yaml`
- 在本地驗證 Dockerfile
- 提交前測試變更檢測

❌ **要麼避免**
- 不要頻繁改動優先級
- 不要跳過依賴配置
- 不要忽略 hadolint 警告
- 不要在 main 上推送未測試的代碼

---

## 📞 獲取幫助

### 查看完整文檔
```bash
less .github/MODULAR_CI_GUIDE.md
```

### 測試變更偵測
```bash
python .github/scripts/detect_changes.py --help
```

### 列出所有命令
```bash
python .github/scripts/generate_ci.py --help
```

---

**下一步**: 提交 PR 並觀察新 CI 系統的運作！ 🚀
