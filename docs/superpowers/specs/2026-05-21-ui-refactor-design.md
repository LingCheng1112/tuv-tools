<!-- /autoplan restore point: /c/Users/Admin/.gstack/projects/LingCheng1112-tuv-tools/main-autoplan-restore-20260521-221049.md -->
# TUV Tools UI 重构设计 — 文档拆分 & 设置统一

日期: 2026-05-21
状态: 已设计，待实施

## 背景

当前工具存在以下问题：
- 文档拆分配置（输出路径、清洗规则）散落在页面顶部，不持久化
- 条款管理有独立的设置弹窗，两个模块设置不统一
- 文档拆分每次需重新选择文件，无导入历史记录
- 缺少批量操作、拖拽导入等效率功能

## 设计目标

1. 统一设置入口：侧边栏左下角齿轮按钮，弹窗内分标签页管理所有配置
2. SQLite 统一存储：替代 `api_config.json`、`inline_clean_rules.json`、用户偏好等分散文件
3. 文档拆分页面重做：导入→列表→勾选→批量拆分，状态持久化
4. 拖拽导入、右键菜单、文件存在性检测等体验增强

---

## Section 1: 数据层 — SQLite Schema

### 数据库文件

`~/.tuv-tools/tuv-tools.db`（Windows: `%USERPROFILE%/.tuv-tools/tuv-tools.db`）

### 表结构

```sql
-- 全局配置键值对（替代 api_config.json 中的非密钥字段 + 用户偏好）
CREATE TABLE config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- RSA 私钥（独立存储，后续可扩展加密）
CREATE TABLE rsa_key (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    private_key TEXT NOT NULL
);

-- 清洗规则（替代 resources/inline_clean_rules.json）
CREATE TABLE clean_rules (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL,
    pattern   TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0
);

-- 导入文档列表（核心新功能）
CREATE TABLE imported_documents (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path          TEXT NOT NULL UNIQUE,
    file_name          TEXT NOT NULL,
    standard_number    TEXT,
    status             TEXT NOT NULL DEFAULT 'pending',
    last_section_count INTEGER,
    last_split_at      TEXT,
    error_message      TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
```

### AppSettings 改造

新增 `DatabaseManager` 类（`config/database.py`），管理 SQLite 连接和 CRUD：

```python
class DatabaseManager:
    def get_config(self, key, default=None) -> str | None
    def set_config(self, key, value) -> None
    def load_clean_patterns(self) -> list[re.Pattern]
    def save_clean_rules(self, rules: list[dict]) -> None
    def get_documents(self) -> list[dict]
    def add_document(self, file_path: str) -> int
    def update_document_status(self, doc_id, status, section_count, error) -> None
    def delete_document(self, doc_id) -> None
    def load_api_config(self) -> ApiConfig | None
    def save_api_config(self, config: ApiConfig) -> None
```

`AppSettings` 改为通过 `DatabaseManager` 读写，对外接口保持不变。

### 首次启动迁移

1. 检测 `~/.tuv-tools/tuv-tools.db` 是否存在
2. 不存在 → 创建表结构
3. 检测旧文件（`api_config.json`、`rsa_private.key`、`resources/inline_clean_rules.json`）
4. 存在 → 自动导入到 SQLite → 删除旧文件
5. 迁移仅执行一次

---

## Section 2: UI 布局 — 导航栏 + 设置弹窗

### 侧边导航栏

```
┌─────────────────┐
│  TUV Tools       │
├─────────────────┤
│  文档拆分  ◄────│  ← 选中高亮
│  条款管理       │
│                 │
│                 │  ← 弹性空间
├─────────────────┤
│  ⚙ 设置   ◄────│  ← 固定在底部
└─────────────────┘
```

- 使用 `addStretch()` 将设置项推到底部
- 设置项点击弹出 SettingsDialog，不切换 QStackedWidget 页面
- 删除 ChapterView 顶部现有的 "⚙ 设置" 按钮

### 设置弹窗

三标签页 `QTabWidget`：

**拆分配置标签页：**
- 默认输出路径（QLineEdit + 选择按钮）
- 拆分后自动打开输出目录（QCheckBox）

**API 配置标签页：**
- 迁移自当前 `SettingsDialog`（API URL、用户名、密码）
- 新增 RSA 私钥可直接编辑或从文件加载

**清洗规则标签页：**
- QTableWidget 展示规则（名称、Pattern、排序）
- 支持新增、编辑、删除行
- 支持从 JSON 文件导入 / 导出为 JSON

保存时写入 SQLite，各 View 通过 AppSettings 读取。

---

## Section 3: 文档拆分页面重做

### 布局

```
┌──── 文档拆分 ────────────────────────────────────────┐
│  [导入文件] [导入文件夹]  [🔍 搜索筛选...________]    │
│                                                       │
│  ┌──┬────────┬────────┬────────┬──────┬──────┬────┐  │
│  │☑ │ 文件名  │ 标准号  │ 状态    │ 条款数│ 拆分时间│操作│  │
│  ├──┼────────┼────────┼────────┼──────┼──────┼────┤  │
│  │☑ │ IEC 60..│60335-..│ ✅ 已拆分│  64  │05-21 │ 🗑 │  │
│  │☐ │ EN 60.. │60335-..│ ◷ 未处理│  -   │  -   │ 🗑 │  │
│  │☐ │ UL ...  │-       │ ✗ 失败  │  -   │05-20 │ 🗑 │  │
│  └──┴────────┴────────┴────────┴──────┴──────┴────┘  │
│                                                       │
│  ☑ 全选  已选 2/3 项                                  │
│                                                       │
│  [🔽 展开条款预览]  [开始拆分选中]  [打开输出目录]      │
│                                                       │
│  ┌─ 进度条 ────────────────────────────────────┐     │
│  │ ████████████░░░░░░░░  2/3           [取消]   │     │
│  └──────────────────────────────────────────────┘     │
└───────────────────────────────────────────────────────┘
```

### 导入功能

- **导入文件** — QFileDialog 多选 `.docx`，去重后插入 DB 并刷新列表
- **导入文件夹** — QFileDialog 选目录，递归扫描 `.docx`
- **拖拽导入** — 列表区域接受文件/文件夹拖放，拖入时高亮边框
- **搜索筛选** — 顶部搜索框，按文件名/标准号实时过滤

### 文档列表

- 列：☑ 勾选 | 文件名 | 标准号 | 状态 | 条款数 | 上次拆分 | 操作
- 列头可点击排序
- 状态：`◷ 未处理` / `✅ 已拆分 (N条)` / `✗ 失败`
- 文件缺失时显示 ⚠ 标记，tooltip 提示 "原文件不存在"
- 操作列：🗑 删除按钮

### 右键菜单

| 菜单项 | 说明 |
|--------|------|
| 拆分此文档 | 单独拆分当前行 |
| 打开文件位置 | `QDesktopServices.openUrl(file_dir)` |
| 打开输出目录 | 仅已拆分过可见 |
| 复制文件名 | 文件名 → 剪贴板 |
| 删除记录 | 确认后从 DB 删除 |

### 批量操作

- `☑ 全选` — 一键勾选/取消所有项
- "已选 N/M 项" 实时计数
- "开始拆分选中" — 对勾选项逐一拆分，进度条显示
- "打开输出目录" — 取设置中的默认输出路径

### 条款预览

- 点击文件名或展开按钮，列表下方展开上次拆分出的条款列表（条款号 + 标题）
- 无记录时显示 "尚未拆分"

### 拆分完成通知

- 右下角 toast 通知（2 秒自动消失）
- 列表状态自动刷新

---

## Section 4: 文件变更范围

| 文件 | 操作 | 说明 |
|------|------|------|
| `config/database.py` | **新增** | DatabaseManager — SQLite 统一数据管理 |
| `config/settings.py` | 修改 | AppSettings 改为从 DB 读写，保留对外接口 |
| `config/__init__.py` | 修改 | 导出 DatabaseManager |
| `ui/main_window.py` | 修改 | 侧边栏底部加设置按钮，导航结构调整 |
| `ui/views/splitter_view.py` | **重写** | 新文档拆分页面 |
| `ui/views/chapter_view.py` | 修改 | 移除顶部设置按钮 |
| `ui/views/settings_dialog.py` | **新增** | 设置弹窗（三标签页） |
| `ui/widgets/document_list.py` | **新增** | 文档列表组件（QTableWidget 封装） |
| `ui/widgets/toast.py` | **新增** | Toast 通知组件 |
| `tests/test_database.py` | **新增** | 数据库层测试 |
| `tests/test_splitter_ui.py` | **新增** | 拆分 UI 测试 |

---

## 关键规则

- 删除文档记录时不删除原始文件
- RSA 私钥独立存储，不与通用配置混在一起
- 旧文件迁移成功后删除（api_config.json、rsa_private.key、inline_clean_rules.json）
- 导入去重：同一 file_path 不重复添加
- QThread + Signal 模式：后台拆分线程，Worker 引用需保持到 finished 信号
- 设置弹窗使用 `QDialog.exec()` 模态，保存时写入 DB，取消时丢弃

---

## GSTACK REVIEW REPORT

审查日期: 2026-05-21 | 审查方式: /autoplan (CEO + Design + Eng) | Commit: 5eac09d

### CEO Review Summary

**Mode**: SELECTIVE EXPANSION | **Approach**: A (SQLite — 推荐)

**扩展决策**:
| # | Proposal | Effort | Decision |
|---|----------|--------|----------|
| 1 | 最近打开文件列表 | S | Deferred |
| 2 | 导出结果摘要 | S | Deferred |
| 3 | 自动检测标准号 (从文件名) | M | **Accepted** |
| 4 | 拆分历史时间线 | M | Deferred |
| 5 | 快捷键支持 | S | Deferred |

### Design Review — 6/10

**已明确**: 信息层级、布局 ASCII、右键菜单、拖拽交互

**需补充到设计**:
- [ ] **空状态**: 文档列表为空时显示引导文案和导入按钮
- [ ] **加载状态**: 导入大文件夹时的进度指示
- [ ] **错误状态**: DB 损坏/写入失败时的用户提示
- [ ] **搜索无结果**: 筛选后无匹配项的空状态

### Eng Review — 关键发现

**Critical**:
- [ ] **DB 线程安全**: SQLite 连接策略需明确。建议 WAL 模式 + 每线程独立连接，或使用 `check_same_thread=False`
- [ ] **标准号提取**: `standard_number` 列填充逻辑缺失。建议从文件名用 `IEC\s*\d+[-\d]*` 等正则提取

**Gap**:
- [ ] `load_clean_patterns()` 返回 `list[re.Pattern]` 但 `save_clean_rules()` 接受 `list[dict]`，输入输出不对称
- [ ] 大列表性能: 超过 500 行建议虚拟列表

**测试缺口** (约 15-20 新测试):
- [ ] 迁移逻辑 (旧文件→DB→删除)
- [ ] 并发访问安全性
- [ ] 拖拽导入 (不同文件类型)
- [ ] 批量拆分中途取消
- [ ] 清洗规则 CRUD + JSON 导入/导出
- [ ] 设置弹窗保存/取消逻辑

### Deferred to TODOS.md

- 最近打开文件列表 (下拉菜单)
- 导出结果摘要 (CSV/Markdown)
- 拆分历史时间线
- 快捷键支持 (Ctrl+O 等)

### NOT in scope

- SQLAlchemy ORM / Alembic 迁移 (重型依赖，桌面应用不需要)
- 云同步/多设备同步
- 协作/多用户支持
