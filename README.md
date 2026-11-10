# SocioLibrary · 本地优先的社会学文献知识库

项目包名与命令为 `sociolit`。这是可运行的 **0.3.0 Windows 桌面版**：Zotero 本地导入、按页全文检索、可选本地语义检索，以及可配置的期刊元数据发现。代码可开源；个人文献、PDF、笔记、全文索引和密钥保存在本机。

**当前重要状态：**《社会》《人口研究》已接入官网的当期和过刊目录，只获取题名、作者、刊出日期与来源链接。适配器每次核验站点 robots.txt，遇到目录异常停止并提示；它不覆盖未收录在期刊目录中的网络首发论文。《社会学研究》《中国人口科学》已接入官网当期目录快照，仅获取题名、作者、年份和来源链接；未提供准确发表日，长期未运行可能漏掉中间期次。《社会学评论》《人口学刊》《中国社会科学》仍显示“来源待接入”。详见[逐刊核验](docs/discovery-research.md)。

## Windows 软件下载

本轮以 **Windows 10 / 11 x64 桌面软件** 为唯一发布目标。

打开 [软件下载页](https://github.com/Yoesher/SocioLibrary/releases)，选择 `Windows-x64-Setup.exe` 安装版，或完整解压 `Windows-x64-Portable.zip` 免安装版。软件包含运行环境，不需要安装 Python。语义模型首次单独下载。部分机器需先安装微软 WebView2 Runtime。

首次启动后，在“资料与设置”中选择 PDF 文件夹并测试 Zotero 连接，即可同步。支持后台任务进度、作者与年份筛选、全文/语义/混合检索、出处片段复制。详见 [Windows 使用说明](docs/windows.md) 与 [同类项目调研](docs/similar-projects.md)。下方命令行说明主要供开发者使用。

## 获取项目

```sh
git clone https://github.com/Yoesher/SocioLibrary.git
cd SocioLibrary
```

也可以在 GitHub 页面通过 **Code → Download ZIP** 下载并解压。

## 快速启动（Windows）

需要 Python 3.11 或更新版本。推荐 3.11–3.13；首次安装依赖需要联网。

1. 在项目目录双击 `启动知识库.cmd`，或运行 `scripts/start.ps1`。它创建项目虚拟环境、安装程序、生成已忽略的 `config.local.toml` 并打开本地页面。
2. 在 Zotero 的 **设置 → 高级 → 允许此计算机上的其他应用程序与 Zotero 通信** 中启用 Local API，保持 Zotero 运行。
3. 只需配置一次 `config.local.toml`：将 `zotero.allowed_roots` 改为实际的 Zotero `storage` 目录，以及需要导入的链接 PDF 目录。例如 `allowed_roots = ["E:/ReferenceManager/storage", "E:/Research/Papers"]`。重启页面服务后点击 **一键导入 Zotero**。

空的许可目录仍可导入书目信息，但不会读取任意 PDF。不会自动查找、复制或操作 Zotero 的 SQLite 数据库。附件需先由 Zotero 合法下载到本机；文件仍留在原处，项目仅保存路径和索引。

如果系统不允许直接运行 PowerShell 脚本，可在终端逐步执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item config/local.example.toml config.local.toml
# 编辑 config.local.toml，添加 PDF 许可目录。
# 需要七刊登记信息时，把 config/public-journals.toml 的 [[journals]] 各段追加到本地配置。
.\.venv\Scripts\python.exe -m sociolit serve --config config.local.toml --open-browser
```

当前只维护 Windows 发布包。本地服务地址为 `http://127.0.0.1:8765`，仅监听本机。

## 本版已经实现

| 功能 | 行为与边界 |
| --- | --- |
| Zotero 一键导入 | 只读 Local API，读取条目、作者、摘要、标签、独立笔记与本地 PDF；当前仅个人库 `users/0`，不含群组库和 Zotero 批注对象 |
| 安全增量 | 每次完整核对元数据；Zotero 10 按稳定库版本分页，旧版回退单次快照；按指纹与 PDF SHA-256 只重建有变化的索引；完整快照才清理本程序中的失效索引 |
| 全文检索 | SQLite FTS5；英文词及中文单字/双字切分；查询词使用 AND，不支持任意 FTS 高级表达式 |
| 来源定位 | 每段只属于一个 PDF 页；结果显示 1 起算的实际 PDF 页序和 PDF 文件页标签，点击在浏览器打开对应页；页标签不一定是刊物印刷页码 |
| 语义检索 | 可选多语 E5 本地模型；向量增量存储，模型版本隔离，索引过期会明确提示；不向云端发送文献 |
| 期刊发现 | Crossref/OpenAlex/RSS 元数据及已核验的单刊官方目录；分页、有限重试、DOI 去重、保守无 DOI 去重、元数据更正、失败来源状态 |
| 月度更新 | 本地按来源保存成功日期；每日或启动时检查，当月成功则跳过，关机后可补查；生成新增/更新摘要并在页面提示 |
| GitHub Actions | 可选月度公共元数据报告；默认门控关闭，运行无仓库写权限；不会访问或上传本地库 |
| Windows OCR | 使用本机 Windows 文字识别组件，分批处理无文字层页面；保留实际页序，不改写原 PDF |
| 保存检索 | 保存关键词、检索方式及作者/年份条件，可在当前资料库重新执行 |
| 阅读笔记 | 新增、编辑、归档和恢复；来源摘录以快照保留，独立于 Zotero 条目删除 |

导入中的“清理”仅影响 SocioLit 的派生索引，绝不删除或更改 Zotero 原文件。书目以事务提交，PDF 按文件逐个提交，大型导入中断后可再次点击导入继续；完成前页面会提示部分 PDF 索引可能尚未刷新。切换旧版 Zotero 库时，需要更改 `zotero.library_name`；Zotero 10 的服务器实例标识可辅助区分资料库。JSON 导出与 Local API 被视为不同来源，跨导入方式不会自动合并私人文献。详见[Zotero 方案核实](docs/zotero-research.md)。

扫描 PDF 或空白文字层可在 Windows 桌面版“资料与设置”中识别。使用 Windows 自带 OCR 和已安装语言包，按批次处理，原 PDF 不修改，识别片段标注为 OCR。表格、脚注、双栏文字的提取顺序需要回到 PDF 核查。页码定位是来源导航，不是对引文正确性的自动保证。

## 本地语义模型

基础安装不包含体积较大的机器学习依赖和模型；全文检索可以独立使用。启用语义检索：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[semantic]"
.\.venv\Scripts\python.exe -m sociolit prepare-model --config config.local.toml
.\.venv\Scripts\python.exe -m sociolit embed --config config.local.toml
.\.venv\Scripts\python.exe -m sociolit search "照料责任如何影响就业连续性" --semantic --config config.local.toml
```

`prepare-model` 只下载 [intfloat/multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small) 模型资产，不上传资料。之后编码和查询强制本地加载，不启用远程模型代码。首次下载可能受网络限制；目录必须为空，下载中断时请使用新的 `semantic.model_path` 重试。模型 revision 记录在本地 manifest 中；升级模型后重建索引。

如果官方模型大文件下载反复中断，可在安装 `[semantic]` 依赖后运行 `python scripts/prepare_model_verified.py`：它从官方 Hugging Face 读取清单，以 ModelScope 传输模型权重，支持分段续传，并对照官方 SHA-256 校验完整文件；其他配置和分词文件也按官方清单核验。整个过程只下载公开模型，不发送文献。若设置了自定义 `semantic.model_path`，请同时向该脚本传入 `--target` 指向同一目录。若官方清单不可用或任何校验不一致，脚本会停止，且不将模型标记为可用。

可以在本地配置的 `[semantic]` 下设置 `collection_keywords = ["生育", "婚育"]`，将语义试点限定到 Zotero 中名称匹配的文件夹及其子文件夹，附属笔记随父条目进入试点。构建试点时需打开 Zotero，以识别文件夹；构建后可以离线搜索。页面会明确显示语义检索范围，全文检索仍覆盖整个本地库。同步过 Zotero 后，应重新点击“构建语义索引”以刷新范围及变化的片段；未变化的向量会复用。删除这一配置后，下次构建将覆盖全部资料。

构建索引期间，全文检索可用；为保护同一本地库的写入一致性，新的 Zotero 导入、语义索引构建和手动期刊更新需要等待当前构建结束。定时期刊检查若恰好需要写入而遇到占用，会在下次检查时重试，不会把失败记录成成功。

MVP 采用每页最多 400 字符、重叠 80 字符的片段与本地余弦检索。向量分批保存，中断后可以继续；在所选范围的全部片段完成前，语义搜索会提示索引不完整。CPU 推理默认限制为 2 个线程，可在启动进程时通过 `OMP_NUM_THREADS` 和 `MKL_NUM_THREADS` 调整。大文献库的首次构建可能需要很长时间及较多磁盘空间；查询采用线性扫描。模型有 token 长度限制，极端多语言字符可能被截断；暂不承诺长文检索召回率。真实模型及个人核心文献的相关性评测应在安装模型后开展，自动测试使用可控编码器检验索引逻辑。

## 期刊配置与按月更新

`config.local.toml` 只用于本机；`config/public-journals.toml` 用于可能公开的 GitHub Actions，两者不会自动合并。默认配置中四刊的官网目录已启用，其他三刊待接入。增加一个确实可用的来源后，可填写：

```toml
[[journals]]
name = "已核验期刊名称"
issns = ["实际 ISSN"]
enabled = true
sources = ["crossref"]  # 可选 crossref / openalex / rss；official_toc 和 cass_current_toc 只适用于各自已核验的两刊
# rss_url = "https://出版机构的实际订阅地址"
```

不要照抄占位值运行。RSS 只允许公开 HTTPS，校验证书，不自动绕过失效订阅源。无 DOI 记录只有题名、年份、第一作者一致且不与不同 DOI 冲突才合并。没有结果不等于没有发表新文章。

```powershell
# 手动更新；输出仍在本机
.\.venv\Scripts\python.exe -m sociolit discover --config config.local.toml
# 仅检查本月尚未成功的来源，用于日常定时任务
.\.venv\Scripts\python.exe -m sociolit discover --due --config config.local.toml
# 选择运行此脚本后，才会安装当前用户的 Windows 定时任务
.\scripts\register-monthly.ps1
```

默认回查 90 天、与上次成功日期至少重叠 7 天；久未开机时回溯至上次成功时间。《社会》《人口研究》官方目录沿“上一期”逐期回查到窗口之前，页面异常、政策禁止或达到上限时停止并报告。首次会收录一部分窗口之前的期刊目录，作为去重基线，不应将其理解为当月新发表。Crossref 使用索引日期，可发现旧文献的元数据变化。OpenAlex 免费过滤依赖发表日期，RSS 依赖当前 feed 保留范围，这两者不能保证补齐所有迟收录和漏期。分页上限或来源失败时不推进对应成功日期。

本地提醒是页面更新状态和本地 `digest.md`，**没有系统弹窗、邮件或微信推送**。程序不会代用户发送消息。Windows 任务需要登录用户及可用网络；每位使用者需自行选择是否安装定时任务。

OpenAlex 启用时从环境变量读取 `OPENALEX_API_KEY`；跨页要求有效 key，详见[当前接口核实](docs/discovery-research.md)。Crossref 的 `CROSSREF_MAILTO` 可选。`.env.example` 只是说明，程序不自动载入 `.env`；请在当前终端或系统环境中设置。不要在配置中硬编码密钥。

GitHub 的定时触发可能延迟或丢弃，公开仓库长期无活动时可能停用，且运行器不能访问个人电脑。GitHub 报告目前只做单次窗口去重，本地缓存才提供跨次去重。详见[自动化说明](docs/automation.md)。

## 命令与资料位置

```powershell
python -m sociolit import-zotero --config config.local.toml
python -m sociolit import-zotero --config config.local.toml --export "D:/Exports/library.json"
python -m sociolit search "劳动关系" --config config.local.toml
python -m sociolit status --config config.local.toml
```

CSL JSON 仅提供元数据；含附件的导出需要显式附件路径且仍受目录许可限制。导出文件不是 Zotero 数据库。

资料目录优先级：`--data-dir` → `local.data_dir` → `SOCIOLIT_DATA_DIR` → 默认 Windows `%LOCALAPPDATA%/SocioLit`，其他系统 `~/.local/share/SocioLit`。其中 `library.sqlite3` 保存全文/元数据/笔记/向量；`discovery/metadata-cache.json` 保存期刊历史；`discovery/digests/` 保存最新报告，`discovery/history/` 保存历次报告；`models/` 保存本地模型。这些内容不属于开源交付。

关闭应用后备份完整资料目录，并另行备份 Zotero 资料。MVP 暂无自动备份、多用户鉴权、RAG 问答、理论观点比较或知识图谱。它先提供可核查的检索基础。

## 开发、测试与开源准备

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check src tests
```

测试使用合成 PDF 和模拟来源，不访问个人文献、不要求密钥、不依赖外部网络。覆盖安全导入、PDF 变化、原文页码、跨库隔离、笔记标记、语义索引失效、分页去重、恶意 XML、来源失败与调度水位。实际运行环境及结果见[验证记录](docs/validation.md)。CI 当前只维护 Windows、Python 3.11/3.13，构建情况见 GitHub Actions。

项目采用 MIT 开源许可。参与开发时只提交经审查的代码、文档、公开配置和合成测试。`.gitignore` 屏蔽常见 PDF、数据库、模型和密钥文件，但不能保证识别任意命名的私人资料。先检查待提交文件，再创建远端仓库。代码采用 MIT 许可，论文与第三方模型的许可独立适用。详见 [SECURITY.md](SECURITY.md) 和[架构说明](docs/architecture.md)。

## 参与项目

- [贡献指南](CONTRIBUTING.md)：安装、检查和期刊适配要求。
- [开发计划](ROADMAP.md)：现有功能和后续方向。
- [版本记录](CHANGELOG.md)：发布变化。
- [第三方依赖说明](THIRD_PARTY_NOTICES.md)：代码、模型和论文的许可边界。

本项目尚处于早期阶段。欢迎使用合成样例报告问题；请不要上传私人论文、Zotero 导出或未经脱敏的日志。

## 保存检索、阅读笔记和扫描页

执行检索后可命名并保存条件，在“检索与笔记”中重新运行。结果中的“写阅读笔记”保留来源片段快照，也可新建独立笔记。笔记可以编辑、归档、恢复，不写回 Zotero，同步删除条目不会删除这些笔记。OCR 只给没有原生文本的页面增加派生片段；未改变的附件再次同步会复用 OCR，PDF 改变后移除旧 OCR。图像和识别文字只在本机处理。详情见 [0.3 使用说明](docs/windows.md)。
