#!/bin/bash

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印带颜色的输出
print_header() {
    echo -e "${BLUE}════════════════════════════════════════${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}════════════════════════════════════════${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# 清理数据库
cleanup() {
    print_header "清理测试环境"
    rm -f ocr_tasks.db
    print_success "数据库已清理"
}

# 检查依赖
check_dependencies() {
    print_header "检查依赖"
    
    if ! command -v python3 &> /dev/null; then
        print_error "Python3 未安装"
        exit 1
    fi
    print_success "Python3 已安装"
    
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    print_success "Python 版本: $PYTHON_VERSION"
    
    if ! python3 -c "import pytest" 2>/dev/null; then
        print_warning "pytest 未安装，正在安装..."
        pip install -q pytest pytest-asyncio httpx
        print_success "测试依赖已安装"
    else
        print_success "测试依赖已就绪"
    fi
}

# 运行单元测试 - Book Service
run_book_service_tests() {
    print_header "运行 Book Service 测试"
    pytest tests/test_book_service.py -v --tb=short
    if [ $? -eq 0 ]; then
        print_success "Book Service 测试通过"
        return 0
    else
        print_error "Book Service 测试失败"
        return 1
    fi
}

# 运行单元测试 - PDF 格式
run_pdf_formatting_tests() {
    print_header "运行 PDF 格式处理测试"
    pytest tests/test_pdf_formatting.py -v --tb=short
    if [ $? -eq 0 ]; then
        print_success "PDF 格式测试通过"
        return 0
    else
        print_error "PDF 格式测试失败"
        return 1
    fi
}

# 运行集成测试 - API
run_api_tests() {
    print_header "运行 API 端点测试"
    pytest tests/test_api.py -v --tb=short
    if [ $? -eq 0 ]; then
        print_success "API 测试通过"
        return 0
    else
        print_error "API 测试失败"
        return 1
    fi
}

# 运行所有测试
run_all_tests() {
    print_header "运行所有测试"
    pytest tests/ -v --tb=short
    return $?
}

# 生成覆盖率报告
generate_coverage_report() {
    print_header "生成覆盖率报告"
    
    if ! python3 -c "import coverage" 2>/dev/null; then
        print_warning "coverage 未安装，正在安装..."
        pip install -q coverage
    fi
    
    pytest tests/ --cov=app --cov-report=html --cov-report=term-missing -q
    print_success "覆盖率报告已生成 (see htmlcov/index.html)"
}

# 显示帮助
show_help() {
    echo -e "${BLUE}PDF OCR Service 后端测试脚本${NC}"
    echo ""
    echo "用法: $0 [命令]"
    echo ""
    echo "命令:"
    echo "  all          - 运行所有测试"
    echo "  book         - 运行 Book Service 测试"
    echo "  pdf          - 运行 PDF 格式测试"
    echo "  api          - 运行 API 端点测试"
    echo "  coverage     - 生成覆盖率报告"
    echo "  quick        - 快速测试 (跳过覆盖率)"
    echo "  clean        - 清理测试环境"
    echo "  full         - 完整测试流程 (清理 -> 依赖 -> 所有测试 -> 覆盖率)"
    echo "  help         - 显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0 all       - 运行所有测试"
    echo "  $0 full      - 完整测试流程"
    echo "  $0 coverage  - 生成覆盖率报告"
}

# 主函数
main() {
    COMMAND=${1:-full}
    
    case $COMMAND in
        all)
            cleanup
            check_dependencies
            run_all_tests
            ;;
        book)
            cleanup
            check_dependencies
            run_book_service_tests
            ;;
        pdf)
            cleanup
            check_dependencies
            run_pdf_formatting_tests
            ;;
        api)
            cleanup
            check_dependencies
            run_api_tests
            ;;
        coverage)
            cleanup
            check_dependencies
            run_all_tests
            generate_coverage_report
            ;;
        quick)
            cleanup
            check_dependencies
            run_all_tests
            ;;
        clean)
            cleanup
            ;;
        full)
            cleanup
            check_dependencies
            run_book_service_tests || exit 1
            run_pdf_formatting_tests || exit 1
            run_api_tests || exit 1
            generate_coverage_report
            print_header "🎉 所有测试通过！"
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            print_error "未知命令: $COMMAND"
            show_help
            exit 1
            ;;
    esac
}

# 运行主函数
main "$@"
