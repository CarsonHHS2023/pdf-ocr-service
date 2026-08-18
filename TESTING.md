# Required and Manual CI Layers

## Required lightweight CI

Pull requests to `main`, pushes to `main`, and manual dispatches run the `Required Backend CI` workflow. This workflow installs `requirements-ci.txt` plus `requirements-test.txt`, intentionally excluding PaddleOCR/PaddleOCR-VL/PaddleX and MinerU dependencies so it does not download models, initialize local OCR, call `paddle-vl-api`, or require secrets.

Required CI runs:

```bash
python -m compileall -q app tests/test_api.py tests/test_phase2_light.py
python -m pytest --collect-only -q tests/test_api.py tests/test_phase2_light.py
python -m pytest -q tests/test_api.py tests/test_phase2_light.py
git diff --check
```

The selected required tests are `tests/test_api.py` for Reader-facing API contract coverage and `tests/test_phase2_light.py` for deterministic database/image/content service coverage. Heavy local OCR tests are not part of automatic PR or normal `main` push CI.

## Manual legacy local OCR tests

The `Legacy Local OCR Tests` workflow is `workflow_dispatch` only. Use it when explicitly validating old local OCR/MinerU/PaddleOCR behavior. It installs the full `requirements.txt` stack and runs:

```bash
python -m pytest -q tests/test_heavy.py tests/test_phase2_integration.py
```

These tests remain available for manual diagnostics, but they are not required PR checks because they can require local OCR/model dependencies and longer runtimes.

# 📋 后端测试计划 - PDF OCR Service

## 🎯 测试范围

### 1️⃣ **单元测试** (Unit Tests)
- ✅ Book Service 业务逻辑
- ✅ PDF 格式处理
- ✅ 数据库模型

### 2️⃣ **集成测试** (Integration Tests)
- ✅ API 端点功能
- ✅ 数据库操作
- ✅ 文件 I/O 操作

### 3️⃣ **API 端到端测试** (E2E Tests)
- ✅ HTTP 请求/响应验证
- ✅ 文档生成验证
- ✅ 错误处理验证

---

## 🚀 快速开始

### 安装依赖
```bash
# 安装主依赖
pip install -r requirements.txt

# 安装测试依赖
pip install -r requirements-test.txt
```

### 运行所有测试
```bash
# 运行所有测试（显示覆盖率）
pytest tests/ -v --tb=short

# 运行特定测试文件
pytest tests/test_book_service.py -v

# 运行特定测试类
pytest tests/test_api.py::TestBooksEndpoint -v

# 运行特定测试用例
pytest tests/test_book_service.py::TestBookService::test_create_book_success -v

# 运行测试并显示打印输出
pytest tests/ -v -s

# 运行测试并生成覆盖率报告
pytest tests/ --cov=app --cov-report=html
```

---

## 📂 测试文件说明

### **tests/test_book_service.py** 
单元测试 - Book Service 核心功能

**测试用例：**
```
✅ test_create_book_success       - 成功创建书籍
✅ test_get_book_success          - 成功获取书籍
✅ test_get_book_not_found        - 获取不存在的书籍
✅ test_get_all_books             - 获取所有书籍
✅ test_delete_book_success       - 成功删除书籍
✅ test_delete_book_not_found     - 删除不存在的书籍
```

**运行：**
```bash
pytest tests/test_book_service.py -v
```

---

### **tests/test_pdf_formatting.py**
单元测试 - PDF 格式处理

**测试用例：**
```
✅ test_paragraph_internal_newlines_removed  - 段落内换行完全移除
✅ test_paragraph_no_space_replacement       - 换行不替换为空格
✅ test_empty_paragraphs_skipped             - 空段落被跳过
✅ test_catalog_line_cleaning                - 目录行清理
✅ test_preserve_inline_text                 - 保留段落内容
```

**运行：**
```bash
pytest tests/test_pdf_formatting.py -v
```

---

### **tests/test_api.py**
集成测试 - API 端点功能

**测试用例：**
```
Root Endpoint Tests:
✅ test_root_endpoint                    - 根端点返回服务信息

Health Endpoint Tests:
✅ test_health_check                     - 健康检查端点

Books Endpoint Tests:
✅ test_list_empty_books                 - 列出空书籍
✅ test_list_books_with_metadata         - 列出包含元数据的书籍
✅ test_get_nonexistent_book             - 获取不存在的书籍

PDF Upload Tests:
✅ test_upload_pdf_missing_file          - 上传缺少文件
✅ test_upload_invalid_file_type         - 上传无效文件类型

Image Endpoint Tests:
✅ test_get_nonexistent_image            - 获取不存在的图表
✅ test_delete_nonexistent_image         - 删除不存在的图表

Documentation Tests:
✅ test_swagger_docs                     - Swagger 文档可用
✅ test_openapi_schema                   - OpenAPI Schema 可用
```

**运行：**
```bash
pytest tests/test_api.py -v
```

---

## 📊 测试场景详解

### **场景 1: 创建并管理书籍**
```bash
# 测试流程：
1. 创建空书籍列表
2. 添加带元数据的书籍
3. 验证元数据正确返回
4. 删除书籍
5. 验证列表为空

pytest tests/test_api.py::TestBooksEndpoint -v
```

### **场景 2: PDF 格式处理**
```bash
# 测试流程：
1. 测试多行段落被合并
2. 验证换行不被替换为空格
3. 测试空段落跳过
4. 验证目录格式正确清理

pytest tests/test_pdf_formatting.py -v
```

### **场景 3: 错误处理**
```bash
# 测试流程：
1. 访问不存在的资源 (404)
2. 上传无效文件 (400)
3. 验证错误消息正确

pytest tests/test_api.py::TestPDFUploadEndpoint -v
```

---

## 🔍 测试验证清单

### ✅ **数据验证**
- [ ] 书籍元数据（作者、出版日期、页数）正确存储
- [ ] PDF 内容正确格式化（段落、图表标记）
- [ ] 图表被正确提取和标记

### ✅ **API 验证**
- [ ] 所有端点返回正确的状态码
- [ ] 响应数据结构正确
- [ ] 错误响应包含适当的消息

### ✅ **业务逻辑验证**
- [ ] 书籍创建时自动生成 ID
- [ ] 元数据字段可选
- [ ] 删除书籍时级联删除关联数据

### ✅ **文件操作验证**
- [ ] TXT 文件正确保存
- [ ] 文件删除成功
- [ ] 目录自动创建

---

## 🎬 完整测试运行步骤

### 1️⃣ **本地开发测试**
```bash
# 清理之前的测试数据
rm -f ocr_tasks.db

# 安装依赖
pip install -r requirements.txt requirements-test.txt

# 运行全部测试
pytest tests/ -v --tb=short

# 查看测试覆盖率
pytest tests/ --cov=app --cov-report=term-missing
```

### 2️⃣ **启动开发服务器进行手动测试**
```bash
# 在另一个终端启动服务
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 7860

# 访问 Swagger 文档
open http://localhost:7860/docs

# 使用 curl 测试 API
curl -X GET http://localhost:7860/api/v1/health
curl -X GET http://localhost:7860/api/v1/books
```

### 3️⃣ **Docker 容器测试**
```bash
# 构建镜像
docker build -t pdf-ocr-service .

# 运行测试
docker run --rm pdf-ocr-service pytest tests/ -v

# 运行服务
docker run -p 7860:7860 pdf-ocr-service
```

---

## 📈 测试覆盖率目标

| 模块 | 目标 | 状态 |
|------|------|------|
| book_service.py | 95%+ | 🔄 |
| pdf_service.py | 90%+ | 🔄 |
| routers/books.py | 85%+ | 🔄 |
| models.py | 80%+ | 🔄 |

---

## 🐛 常见问题

### Q: 运行测试时出现 `ModuleNotFoundError`？
```bash
# 解决方案：确保当前目录在 Python 路径中
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
pytest tests/ -v
```

### Q: 测试数据库被锁定？
```bash
# 解决方案：删除测试数据库并重新创建
rm -f ocr_tasks.db
pytest tests/ -v
```

### Q: 如何只运行失败的测试？
```bash
pytest tests/ --lf  # 只运行上次失败的测试
pytest tests/ --ff  # 运行失败的测试，然后其他测试
```

---

## 📝 持续集成 (CI) 配置

建议在 GitHub Actions 中添加：

```yaml
name: Backend Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r requirements-test.txt
      - name: Run tests
        run: pytest tests/ -v --cov=app
```

---

## ✨ 下一步

1. 运行 `pytest tests/ -v` 验证所有测试通过
2. 检查覆盖率报告
3. 修复任何失败的测试
4. 设置 CI/CD 管道
5. 准备前端开发

---

**准备好开始测试了！** 🚀

## Alembic migration checks

Required Backend CI now includes lightweight Alembic validation without OCR/model dependencies:

```bash
alembic heads
alembic history
python -m pytest -q tests/test_migrations.py
```

For full local validation of the migration baseline, run:

```bash
python -m compileall -q app tests alembic
python -m pytest -q tests/test_migrations.py
```

Migration tests use temporary SQLite databases and apply `alembic upgrade head` / `alembic downgrade base`. Existing narrow Reader/API tests may still use fast `Base.metadata.create_all()` fixtures temporarily; production startup does not.

## M1-003D storage/source-retention checks

Lightweight backend validation includes:

```bash
python -m compileall -q app tests alembic
python -m pytest --collect-only -q tests/test_api.py tests/test_phase2_light.py tests/test_foundation_schema.py tests/test_foundation_models.py tests/test_migrations.py tests/test_storage_contract.py tests/test_source_retention.py
python -m pytest -q tests/test_api.py tests/test_phase2_light.py tests/test_foundation_schema.py tests/test_foundation_models.py tests/test_migrations.py tests/test_storage_contract.py tests/test_source_retention.py
git diff --check
```

These tests cover Local provider contract behavior, original TXT/PDF retention, no public storage-reference leakage, retained-source cleanup on book deletion, and the deferred processed TXT/DB BLOB compatibility boundary.

### M1-003D deployment note

The current Hugging Face Space is a disposable test deployment with no Persistent Storage configured. Local retained-source objects and SQLite data are therefore ephemeral in that environment. Runtime tests validate adapter behavior, not production durability; production must use persistent mounted storage or a durable provider before real user data is accepted.
