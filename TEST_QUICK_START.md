# CI Quick Start

## Required lightweight checks

Run the same deterministic checks used by `Required Backend CI` before opening a PR:

```bash
pip install -r requirements-ci.txt -r requirements-test.txt
python -m compileall -q app tests/test_api.py tests/test_phase2_light.py
python -m pytest --collect-only -q tests/test_api.py tests/test_phase2_light.py
python -m pytest -q tests/test_api.py tests/test_phase2_light.py
git diff --check
```

This layer must stay CPU-only and secret-free. It does not install PaddleOCR/PaddleOCR-VL/PaddleX, does not run real MinerU processing, and does not call `paddle-vl-api`.

## Manual heavyweight local OCR checks

Use the manual `Legacy Local OCR Tests` GitHub Actions workflow, or run locally only when the full local OCR stack is intentionally installed:

```bash
pip install -r requirements.txt -r requirements-test.txt
python -m pytest -q tests/test_heavy.py tests/test_phase2_integration.py
```

# 🧪 后端测试快速参考指南

## ⚡ 最快开始（3 步）

### 1️⃣ 给脚本执行权限
```bash
chmod +x run_tests.sh
```

### 2️⃣ 运行完整测试
```bash
./run_tests.sh full
```

### 3️⃣ 查看结果
```
✅ Book Service 测试通过
✅ PDF 格式测试通过
✅ API 端点测试通过
✅ 覆盖率报告已生成 (see htmlcov/index.html)
```

---

## 🎯 常用命令

### **完整测试流程**（推荐）
```bash
./run_tests.sh full
# 执行：清理 → 检查依赖 → 运行所有测试 → 生成覆盖率报告
```

### **快速测试**（跳过覆盖率）
```bash
./run_tests.sh quick
# 快速运行所有测试，不生成覆盖率
```

### **运行所有测试**
```bash
./run_tests.sh all
# 运行所有测试（带详细输出）
```

### **单独运行测试**
```bash
./run_tests.sh book      # 仅运行 Book Service 测试
./run_tests.sh pdf       # 仅运行 PDF 格式处理测试
./run_tests.sh api       # 仅运行 API 端点测试
```

### **生成覆盖率报告**
```bash
./run_tests.sh coverage
# 运行所有测试并生成详细覆盖率报告 (htmlcov/index.html)
```

### **清理测试环境**
```bash
./run_tests.sh clean
# 删除测试数据库文件
```

### **显示帮助**
```bash
./run_tests.sh help
```

---

## 📊 测试套件详解

### **Book Service 测试** (6 个用例)
```bash
./run_tests.sh book
```

**测试内容：**
- ✅ 创建书籍（含元数据）
- ✅ 查询单本书籍
- ✅ 处理不存在的书籍
- ✅ 获取所有书籍
- ✅ 删除书籍
- ✅ 级联删除验证

---

### **PDF 格式处理测试** (5 个用例)
```bash
./run_tests.sh pdf
```

**测试内容：**
- ✅ 段落内换行完全移除
- ✅ 换行不被替换为空格
- ✅ 空段落被跳过
- ✅ 目录行清理
- ✅ 内联文本保留

---

### **API 端点测试** (11 个用例)
```bash
./run_tests.sh api
```

**测试内容：**
- ✅ 根端点 (`GET /`)
- ✅ 健康检查 (`GET /api/v1/health`)
- ✅ 书籍列表 (`GET /api/v1/books`)
- ✅ 书籍详情 (`GET /api/v1/books/{id}`)
- ✅ PDF 上传 (`POST /api/v1/pdf/upload`)
- ✅ 图表管理 (`GET/DELETE /api/v1/images/{id}`)
- ✅ API 文档 (Swagger, OpenAPI)
- ✅ 错误处理 (404, 400 等)

---

## 📈 预期输出

### **成功的完整测试运行：**
```
════════════════════════════════════════
清理测试环境
════════════════════════════════════════
✅ 数据库已清理

════════════════════════════════════════
检查依赖
════════════════════════════════════════
✅ Python3 已安装
✅ Python 版本: 3.11.0
✅ 测试依赖已就绪

════════════════════════════════════════
运行 Book Service 测试
════════════════════════════════════════
tests/test_book_service.py::TestBookService::test_create_book_success PASSED
tests/test_book_service.py::TestBookService::test_get_book_success PASSED
tests/test_book_service.py::TestBookService::test_get_book_not_found PASSED
tests/test_book_service.py::TestBookService::test_get_all_books PASSED
tests/test_book_service.py::TestBookService::test_delete_book_success PASSED
tests/test_book_service.py::TestBookService::test_delete_book_not_found PASSED
✅ Book Service 测试通过

════════════════════════════════════════
运行 PDF 格式处理测试
════════════════════════════════════════
tests/test_pdf_formatting.py::TestPDFFormatting::test_paragraph_internal_newlines_removed PASSED
tests/test_pdf_formatting.py::TestPDFFormatting::test_paragraph_no_space_replacement PASSED
tests/test_pdf_formatting.py::TestPDFFormatting::test_empty_paragraphs_skipped PASSED
tests/test_pdf_formatting.py::TestPDFFormatting::test_catalog_line_cleaning PASSED
tests/test_pdf_formatting.py::TestPDFFormatting::test_preserve_inline_text PASSED
✅ PDF 格式测试通过

════════════════════════════════════════
运行 API 端点测试
════════════════════════════════════════
tests/test_api.py::TestRootEndpoint::test_root_endpoint PASSED
tests/test_api.py::TestHealthEndpoint::test_health_check PASSED
tests/test_api.py::TestBooksEndpoint::test_list_empty_books PASSED
tests/test_api.py::TestBooksEndpoint::test_list_books_with_metadata PASSED
tests/test_api.py::TestBooksEndpoint::test_get_nonexistent_book PASSED
tests/test_api.py::TestPDFUploadEndpoint::test_upload_pdf_missing_file PASSED
tests/test_api.py::TestPDFUploadEndpoint::test_upload_invalid_file_type PASSED
tests/test_api.py::TestImageEndpoint::test_get_nonexistent_image PASSED
tests/test_api.py::TestImageEndpoint::test_delete_nonexistent_image PASSED
tests/test_api.py::TestAPIDocumentation::test_swagger_docs PASSED
tests/test_api.py::TestAPIDocumentation::test_openapi_schema PASSED
✅ API 测试通过

════════════════════════════════════════
生成覆盖率报告
════════════════════════════════════════
✅ 覆盖率报告已生成 (see htmlcov/index.html)

════════════════════════════════════════
🎉 所有测试通过！
════════════════════════════════════════
```

---

## 📁 查看覆盖率报告

生成覆盖率报告后，用浏览器打开：

```bash
# macOS
open htmlcov/index.html

# Linux
xdg-open htmlcov/index.html

# Windows
start htmlcov/index.html
```

**覆盖率报告展示：**
- 📊 各模块代码覆盖率
- 🟢 已覆盖的代码行
- 🔴 未覆盖的代码行
- 📈 总体覆盖率统计

---

## 🐛 常见问题

### Q: 运行脚本时出现 "Permission denied"？
```bash
chmod +x run_tests.sh
./run_tests.sh full
```

### Q: pytest 未找到？
```bash
pip install pytest pytest-asyncio httpx
./run_tests.sh full
```

### Q: 数据库被锁定？
```bash
./run_tests.sh clean
./run_tests.sh full
```

### Q: 某个测试失败，如何调试？
```bash
# 查看详细错误信息
pytest tests/test_book_service.py -v -s

# 只运行特定测试
pytest tests/test_book_service.py::TestBookService::test_create_book_success -v
```

---

## 📋 工作流建议

### 开发过程中
```bash
# 快速检查
./run_tests.sh quick

# 修改代码后运行相关测试
./run_tests.sh book  # 修改 book_service.py
./run_tests.sh pdf   # 修改 pdf_service.py
./run_tests.sh api   # 修改 routers/books.py
```

### 提交前
```bash
# 完整测试确保没有回归
./run_tests.sh full
```

### CI/CD 流程
```bash
./run_tests.sh coverage
# 验证覆盖率达到目标
```

---

## ✨ 提示

| 场景 | 命令 |
|------|------|
| 首次运行 | `./run_tests.sh full` |
| 快速反馈 | `./run_tests.sh quick` |
| 调试单个测试 | `./run_tests.sh book` 或 `pytest tests/test_book_service.py -v -s` |
| 检查覆盖率 | `./run_tests.sh coverage` |
| 生产前检查 | `./run_tests.sh full` |

---

## 🎯 下一步

1. ✅ **运行完整测试** → `./run_tests.sh full`
2. ✅ **验证所有通过** → 检查最后的 ✅ 标记
3. ✅ **查看覆盖率** → `open htmlcov/index.html`
4. ✅ **准备前端开发** → 后端测试通过后开始

---

**准备好开始测试了吗？** 🚀

```bash
./run_tests.sh full
```

## Database migration quick commands

From the repository root:

```bash
alembic upgrade head
alembic current
alembic history
alembic downgrade base
```

During M1, local SQLite databases are disposable. To recreate the default local database only when it is safe to delete local data:

```bash
rm -f ocr_tasks.db
DATABASE_URL=sqlite:///./ocr_tasks.db alembic upgrade head
```

Do not run destructive downgrade/delete commands against future production data.

## Storage retention quick checks

Run `tests/test_storage_contract.py` for Local provider behavior and `tests/test_source_retention.py` for upload integration. The default Local Storage root is configured by `storage_root` / `STORAGE_ROOT` and defaults to `storage/objects`.

Current HF note: the test Space has no Persistent Storage configured, so `storage/objects` is ephemeral there. This is acceptable only for disposable testing; production needs persistent mounted storage or a durable provider.
