# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

TUV Tools 是一个 PySide6 桌面应用，用于自动化处理 TUV 测试文档。当前核心功能是 DOCX 测试模板拆分：将包含多个条款的 DOCX 文件按条款号（如 `10.2`、`1.2.3`、`Annex A`）拆分为独立文件。

## 常用命令

```bash
# 安装（开发模式）
pip install -e ".[dev]"

# 运行应用
python main.py
# 或通过 entry point
tuv-tools

# 运行测试
pytest
pytest tests/test_xxx.py::test_function_name  # 单个测试

# 非交互式 git
git --no-pager diff
git diff | cat
```

## 架构

应用采用三层结构：

- **UI 层** (`src/tuv_tools/ui/`) — PySide6 界面，侧边导航 + QStackedWidget 切换视图。新功能视图在 `main_window.py:_register_views()` 注册。
- **核心逻辑层** (`src/tuv_tools/core/`) — 按功能模块组织（当前只有 `splitter/`）。
- **配置层** (`src/tuv_tools/config/`) — `AppSettings` 管理全局配置和资源路径。

### Splitter 模块处理流程

`parsing.py:build_sections()` 是主入口，流程为：

1. **解析** (`parse_document`) — 解压 DOCX ZIP，解析 `word/document.xml` 为 Block 列表（段落/表格）
2. **条款检测** (`detect_clause_in_text` / `detect_clause_in_cells`) — 用正则从段落或表格行中识别条款号
3. **Section 构建** — 将连续 Block 归属到对应条款的 Section 对象
4. **导出** (`exporting.py:export_docx_outputs`) — 按条款生成独立 DOCX（`clauses_docx/`），按主版本号合并生成 DOCX（`versions_docx/`）
5. **清洗** (`cleaning.py`) — 导出时根据 JSON 规则文件中的正则移除表格中的填写项（日期、设备号等）

导出使用原始 DOCX 作为 ZIP 模板，仅替换 `word/document.xml`，保留样式和媒体资源。

## 约定

- 代码注释和文档字符串使用中文，代码中的字符串字面量（日志、提示、API 字段）使用英文
- 清洗规则定义在 `resources/inline_clean_rules.json`，格式为 `{name, pattern}` 数组
- XML 命名空间常量和正则定义集中在 `core/splitter/constants.py`
- 数据模型使用 `dataclass`，定义在 `core/splitter/models.py`
- UI 后台任务使用 QThread + Signal 模式（参考 `SplitWorker`）

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
