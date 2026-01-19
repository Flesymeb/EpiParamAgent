# Sci-Hub PDF Download Guide

## 改进功能

### 1. 智能镜像优先级

- **sci.bban.top 优先**：直接 PDF 格式，无需 DDoS-Guard 绕过，速度最快
- **自动降级**：sci.bban.top 失败时自动尝试其他镜像（sci-hub.se, sci-hub.st, sci-hub.ru）
- **Playwright 兜底**：遇到 403 时自动启用 Playwright 浏览器绕过人机验证

### 2. 代理支持

通过环境变量配置 HTTP/HTTPS 代理：

```bash
# Windows (PowerShell)
$env:HTTP_PROXY="http://proxy.example.com:8080"
$env:HTTPS_PROXY="http://proxy.example.com:8080"
python scripts/get_scihub_urls.py --download

# Linux/Mac
export HTTP_PROXY="http://proxy.example.com:8080"
export HTTPS_PROXY="http://proxy.example.com:8080"
python scripts/get_scihub_urls.py --download
```

### 3. 完整下载记录

JSONL 文件现在包含：

- `download_url`: 真实下载 URL（sci.bban.top 直接 URL 或 Playwright 捕获的 URL）
- `local_path`: 本地 PDF 文件路径（如使用--download）
- `status`: 下载状态（available/downloaded）

示例：

```json
{
  "doi": "10.1111/cdev.12676",
  "urls": [
    {
      "url": "https://sci.bban.top/pdf/10.1111/cdev.12676.pdf",
      "download_url": "https://sci.bban.top/pdf/10.1111/cdev.12676.pdf",
      "status": "available",
      "code": 200,
      "size": 171323
    }
  ],
  "downloaded_pdf": "D:\\...\\papers\\pdfs\\10.1111_cdev.12676.pdf"
}
```

## 使用场景

### 场景 1：直接下载（推荐）

大多数 DOI 通过 sci.bban.top 直接下载，无需人工干预：

```bash
python scripts/get_scihub_urls.py --download
```

### 场景 2：仅获取 URL

不下载 PDF，只获取可用 URL 列表：

```bash
python scripts/get_scihub_urls.py
```

### 场景 3：通过代理下载

在网络受限环境中使用代理：

```bash
$env:HTTP_PROXY="http://127.0.0.1:7890"
python scripts/get_scihub_urls.py --download
```

### 场景 4：Playwright 半自动模式

当遇到 DDoS-Guard 保护时（403 错误）：

1. 脚本自动打开浏览器窗口
2. 等待用户手动点击下载按钮（或自动检测到下载链接后点击）
3. PDF 在浏览器会话中直接下载到本地
4. 关闭浏览器，继续处理下一个 DOI

## 工作流程

```
DOI输入
  ↓
尝试 sci.bban.top (直接PDF)
  ↓
成功？ ──Yes─→ 下载 → 跳过其余镜像
  ↓ No
尝试 sci-hub.se
  ↓
403错误？ ──Yes─→ 启动Playwright → 手动/自动点击 → 下载
  ↓ No
继续尝试其他镜像...
```

## 性能优化

1. **找到第一个可用 URL 后立即停止**：不再重复测试所有镜像
2. **随机延迟**：请求间隔 0.5-1.5 秒，避免被限流
3. **随机 User-Agent**：使用 fake-useragent 模拟真实浏览器
4. **Playwright 仅在必要时使用**：减少浏览器启动开销

## 故障排除

### 问题 1：所有镜像都 403

**解决**：

- 设置代理（见上方代理支持部分）
- 确保 Playwright 已安装：`playwright install chromium`
- 手动在浏览器窗口中点击下载按钮

### 问题 2：sci.bban.top 速度慢

**解决**：

- 使用代理加速
- 或手动调整镜像顺序（修改`get_scihub_urls.py`中的`self.mirrors`列表）

### 问题 3：OpenRouter 余额不足

**问题**：运行提取时报错 "Error code: 402"
**解决**：

- 方案 1：充值 OpenRouter 账户
- 方案 2：降低 max_tokens 配置（当前 100000 太高）
- 方案 3：使用本地 LLM（修改.env 文件）

## 输出文件

- `papers/scihub_urls.jsonl`: 详细的下载记录（推荐，包含 download_url）
- `papers/scihub_urls.txt`: 简单的 URL 列表（向后兼容）
- `papers/pdfs/*.pdf`: 下载的 PDF 文件（使用--download 时）

## 配置文件

需要在`papers/`目录下创建`doi.txt`文件，每行一个 DOI：

```
10.1111/cdev.12676
10.1177/1534508409346053
10.1016/j.learninstruc.2018.11.006
```

## 技术细节

- **cloudscraper**: 绕过 Cloudflare/DDoS-Guard 的简单 JS challenge
- **Playwright**: 真实浏览器自动化，绕过复杂的人机验证
- **Cookie 隔离问题已解决**: PDF 在 Playwright 会话中直接下载，避免 cookie 传递问题
- **镜像优先级**: sci.bban.top > sci-hub.se > sci-hub.st > sci-hub.ru
