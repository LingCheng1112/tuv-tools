# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

TUV Tools 是一个 PySide6 桌面应用，用于自动化处理 TUV 测试文档。包含两大功能模块：
- **DOCX 拆分**：将多条款 DOCX 按条款号（如 `10.2`、`Annex A`）拆分为独立文件
- **条款管理**：通过 HTTP API 对后端条款数据进行 CRUD 操作，含 RSA 加密认证和目录树导航

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
pytest tests/test_xxx.py::TestClass::test_name    # 单个测试

# 非交互式 git
git --no-pager diff
git diff | cat
```

## 架构

应用采用三层结构：

- **UI 层** (`src/tuv_tools/ui/`) — PySide6 界面，侧边导航 + QStackedWidget 切换视图。新功能视图在 `main_window.py:_register_views()` 注册。
- **核心逻辑层** (`src/tuv_tools/core/`) — 按功能模块组织：`splitter/`（文档拆分）、`chapter/`（条款管理 API 封装）。
- **配置层** (`src/tuv_tools/config/`) — `AppSettings` 管理全局配置和资源路径。

### Splitter 模块处理流程

`parsing.py:build_sections()` 是主入口，流程为：

1. **解析** (`parse_document`) — 解压 DOCX ZIP，解析 `word/document.xml` 为 Block 列表（段落/表格）
2. **条款检测** (`detect_clause_in_text` / `detect_clause_in_cells`) — 用正则从段落或表格行中识别条款号
3. **Section 构建** — 将连续 Block 归属到对应条款的 Section 对象
4. **导出** (`exporting.py:export_docx_outputs`) — 按条款生成独立 DOCX（`clauses_docx/`），按主版本号合并生成 DOCX（`versions_docx/`）
5. **清洗** (`cleaning.py`) — 导出时根据 JSON 规则文件中的正则移除表格中的填写项（日期、设备号等）

导出使用原始 DOCX 作为 ZIP 模板，仅替换 `word/document.xml`，保留样式和媒体资源。数据模型均为 `dataclass`，定义在 `models.py`。

### Chapter 模块

通过 HTTP API 管理后端条款数据，所有网络操作在 `ChapterWorker`（QThread 子类）中执行，避免阻塞 UI。

- **`models.py`** — 数据模型：`Chapter`（snake_case 字段 → `to_api_dict()` 转 camelCase）、`PageResult`（分页结果）、`FolderNode`（目录树节点）、`ApiConfig`（连接配置）、`ChapterStatus` 枚举
- **`client.py`** — `TuvClient`：封装 `requests.Session`，设置 `token` 属性时自动附加 `Authorization: Bearer` 头，所有 HTTP 方法默认调用 `raise_for_status()`
- **`auth.py`** — `auto_login()` 流程：从 `.token_cache` JSON 恢复 token → 用 `/auth/info` 校验 → 失败则 `/auth/login`（密码 RSA 加密后发送）→ 保存新缓存。缓存在 `token_idle_timeout` 秒后过期
- **`crypto.py`** — RSA 密码加密：从 Base64 PKCS8 私钥推导公钥，PKCS1_v1_5 分块加密（兼容 Java 后端 RSAUtils），1024-bit key 块大小为 117 字节
- **`api.py`** — CRUD 函数：`get_folders()`（目录树查询，支持 pid/folderName 过滤）、`get_chapters()`（分页查询）、`create_chapter()`、`update_chapter()`、`delete_chapters()`（批量）

密钥分离设计：API 连接配置（URL/用户名/密码）保存在项目根目录 `api_config.json`，RSA 私钥独立保存在 `rsa_private.key`，两者分别加载后合并为 `ApiConfig` 对象。

## 关键文件

| 文件 | 说明 |
|------|------|
| `pyproject.toml` | 项目配置、依赖（PySide6, requests, pycryptodome）、pytest 设置、entry point |
| `api_config.json` | API 连接信息（baseUrl/username/password，不含私钥） |
| `rsa_private.key` | RSA 私钥（Base64 PKCS8 DER），仅用于密码加密 |
| `resources/inline_clean_rules.json` | DOCX 清洗规则，`{name, pattern}` 数组 |

## 约定

- 代码注释和文档字符串使用中文，代码中的字符串字面量（日志、提示、API 字段）使用英文
- 清洗规则定义在 `resources/inline_clean_rules.json`
- XML 命名空间常量和条款正则集中在 `core/splitter/constants.py`
- UI 后台任务使用 QThread + Signal 模式，Worker 引用需保持到 finished 信号，避免 Python GC 提前回收导致 Crash（参见 commit `a355a78`）
- 测试使用 class-based 风格（`TestXxx`），位于 `tests/` 目录，直接导入被测模块无需 mock 数据库
- API 字段名约定：Python 侧使用 snake_case（`test_content`、`draft_by`），API 传输使用 camelCase（`testContent`、`draftBy`），转换在 `Chapter.to_api_dict()` / `from_api_dict()` 中完成

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
