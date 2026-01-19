# run_extraction.py 输入模式详解

## 两种输入方式

### 1️⃣ 本地 PDF 模式（推荐用于已下载的文件）

```bash
python scripts/run_extraction.py \
  --input papers/pdfs/ \
  --out output/extraction \
  --method mineru \
  --template early_numeracy
```

**特点：**

- 直接读取本地 PDF 文件
- 无需网络连接
- 处理速度最快
- 适合已经通过 `get_scihub_urls.py --download` 下载的 PDF

**工作流程：**

```
papers/pdfs/10.1111_cdev.12676.pdf
  → 读取本地文件
  → MinerU提取文本
  → LLM结构化提取
  → 输出Excel
```

---

### 2️⃣ 远程 URL 模式（支持但不推荐）

```bash
python scripts/run_extraction.py \
  --input papers/scihub_urls.txt \
  --out output/extraction \
  --method mineru \
  --template early_numeracy
```

**特点：**

- 实时从 URL 下载 PDF（使用 cloudscraper 绕过 DDoS-Guard）
- 需要稳定的网络连接
- 下载到临时文件再处理
- **可能遇到 403 错误**（无法像 get_scihub_urls.py 那样启用 Playwright）

**工作流程：**

```
scihub_urls.txt:
  https://sci.bban.top/pdf/10.1111/cdev.12676.pdf
  ↓
cloudscraper下载 → 临时文件
  ↓
MinerU提取文本
  ↓
LLM结构化提取
  ↓
输出Excel
```

---

## 推荐的完整工作流

### 🌟 最佳实践：两步法

**步骤 1：批量下载 PDF**

```bash
python scripts/get_scihub_urls.py --download
```

- ✅ sci.bban.top 优先（速度快）
- ✅ Playwright 兜底（绕过 403）
- ✅ 记录 download_url 到 jsonl
- ✅ 本地保存到 `papers/pdfs/`

**步骤 2：本地提取数据**

```bash
python scripts/run_extraction.py \
  --input papers/pdfs/ \
  --out output/extraction \
  --method mineru \
  --template early_numeracy
```

- ✅ 无网络依赖
- ✅ 可重复运行
- ✅ 调试方便

---

## 输入文件格式

### 本地 PDF 目录

```
papers/pdfs/
├── 10.1111_cdev.12676.pdf
├── 10.1177_1534508409346053.pdf
└── 10.1016_j.learninstruc.2018.11.006.pdf
```

### URL 列表文件（scihub_urls.txt）

```txt
https://sci.bban.top/pdf/10.1111/cdev.12676.pdf
https://sci.bban.top/pdf/10.1177/1534508409346053.pdf
https://sci.bban.top/pdf/10.1016/j.learninstruc.2018.11.006.pdf
```

### JSONL 格式（scihub_urls.jsonl）

```json
{"doi": "10.1111/cdev.12676", "urls": [{"url": "https://sci.bban.top/pdf/10.1111/cdev.12676.pdf", "status": "available"}]}
{"doi": "10.1177/1534508409346053", "urls": [{"url": "https://sci.bban.top/pdf/10.1177/1534508409346053.pdf", "status": "available"}]}
```

脚本会自动从 jsonl 中提取第一个可用的 URL。

---

## URL 模式的局限性

### ❌ 为什么不推荐直接用 URL？

1. **无 Playwright 支持**

   - `run_extraction.py` 只用 `cloudscraper` 下载
   - 遇到 403 时**无法自动启动浏览器**
   - 而 `get_scihub_urls.py` 有 Playwright 兜底机制

2. **临时文件开销**

   - 每次都重新下载
   - 占用网络带宽
   - 下载失败需要重新运行整个流程

3. **调试困难**
   - PDF 下载失败和提取失败混在一起
   - 难以单独排查问题

### ✅ URL 模式适用场景

只在以下情况使用：

- 论文数量极少（1-5 篇）
- sci.bban.top 稳定可用
- 不想保存本地 PDF 文件

---

## 对比表格

| 特性         | 本地 PDF 模式               | URL 模式              |
| ------------ | --------------------------- | --------------------- |
| **网络依赖** | ❌ 无                       | ✅ 必需               |
| **速度**     | ⚡ 最快                     | 🐌 较慢（含下载时间） |
| **403 处理** | ✅ 预先通过 Playwright 解决 | ❌ 无法处理           |
| **可重复性** | ✅ 高                       | ⚠️ 依赖 URL 稳定性    |
| **调试**     | ✅ 简单                     | ⚠️ 复杂               |
| **存储**     | 📁 需要磁盘空间             | 💨 临时文件自动清理   |
| **推荐度**   | ⭐⭐⭐⭐⭐                  | ⭐⭐                  |

---

## 完整示例

### 场景：提取 3 篇论文的数据

#### 方案 A：推荐流程（两步法）

```bash
# 1. 配置DOI列表
cat > papers/doi.txt << EOF
10.1111/cdev.12676
10.1177/1534508409346053
10.1016/j.learninstruc.2018.11.006
EOF

# 2. 批量下载PDF（自动处理403）
python scripts/get_scihub_urls.py --download

# 3. 本地提取数据
python scripts/run_extraction.py \
  --input papers/pdfs/ \
  --out output/extraction \
  --method mineru \
  --template early_numeracy
```

**优点：**

- ✅ 步骤清晰，易于排查问题
- ✅ 下载失败可单独重试
- ✅ PDF 可重复使用

---

#### 方案 B：URL 直连（不推荐）

```bash
# 1. 手动生成URL列表
cat > papers/urls.txt << EOF
https://sci.bban.top/pdf/10.1111/cdev.12676.pdf
https://sci.bban.top/pdf/10.1177/1534508409346053.pdf
https://sci.bban.top/pdf/10.1016/j.learninstruc.2018.11.006.pdf
EOF

# 2. 直接提取（含下载）
python scripts/run_extraction.py \
  --input papers/urls.txt \
  --out output/extraction \
  --method mineru \
  --template early_numeracy
```

**缺点：**

- ❌ URL 可能 403 失败（无 Playwright 兜底）
- ❌ 下载失败和提取失败混在一起
- ❌ 无法保存 PDF 供后续使用

---

## Debug 模式

两种输入模式都支持 debug 模式（只处理前 3 个）：

```bash
# 本地PDF debug
python scripts/run_extraction.py \
  --input papers/pdfs/ \
  --mode debug \
  --method mineru

# URL debug
python scripts/run_extraction.py \
  --input papers/scihub_urls.txt \
  --mode debug \
  --method mineru
```

---

## 常见问题

### Q1: 我用 URL 模式遇到 403，怎么办？

**A:** 改用两步法：

1. `python scripts/get_scihub_urls.py --download`（会启用 Playwright）
2. `python scripts/run_extraction.py --input papers/pdfs/`

### Q2: 本地 PDF 和 URL 能混用吗？

**A:** 不能。`--input` 参数要么是目录（本地 PDF），要么是 URL 列表文件。

### Q3: 如何知道 PDF 是从哪个 URL 下载的？

**A:** 查看 `papers/scihub_urls.jsonl` 中的 `download_url` 字段：

```bash
cat papers/scihub_urls.jsonl | jq '.urls[0].download_url'
```

### Q4: URL 模式会保存 PDF 吗？

**A:** 不会。下载到临时文件，提取后自动删除。如需保存，用 `get_scihub_urls.py --download`。

---

## 总结

| 你的目标            | 使用命令                                                                   |
| ------------------- | -------------------------------------------------------------------------- |
| 🎯 生产环境批量提取 | `get_scihub_urls.py --download` → `run_extraction.py --input papers/pdfs/` |
| 🧪 快速测试单个 PDF | `run_extraction.py --input papers/pdfs/test.pdf`                           |
| 🌐 试验 URL 直连    | `run_extraction.py --input papers/urls.txt`（不推荐）                      |
| 🐛 调试前 3 个      | `run_extraction.py --input papers/pdfs/ --mode debug`                      |
