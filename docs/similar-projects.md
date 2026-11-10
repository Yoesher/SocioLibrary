# 同类项目调研与 Windows 产品改进

检索日期：2026-11-10。范围是公开可访问的项目仓库、README 和工具官方文档。这是有针对性的多项目检索，不是对整个互联网的穷尽抓取，也不把项目自述的速度或效果当作独立评测。只借鉴产品和架构思路，没有复制这些项目的代码。

| 项目和一手来源 | 文档中值得关注的做法 | 本项目采用或保留的方向 |
| --- | --- | --- |
| [Paperlib](https://github.com/Future-Scholars/paperlib) | 文献元数据、全文检索、筛选、笔记与 RSS | 统一检索工作台、作者和年份筛选、期刊动态独立页面 |
| [ZotSeek](https://github.com/introfini/ZotSeek) | Zotero 内本地语义检索及原文页面定位 | 保留本地模型和可追溯片段；按文件夹试点 |
| [PapersGPT](https://github.com/papersgpt/papersgpt-for-zotero) | 全库检索、文献雷达、引用回跳；支持多种本地或云端模型 | 明确区分检索与生成，保留来源，不默认接入云端 |
| [zotero-semantic-search](https://github.com/ilDon/zotero-semantic-search) | 后台索引、筛选、保存检索及逐页证据 | 后台任务进度、失败可见、片段与出处复制；0.3 增加保存检索 |
| [RAG-Assistant-for-Zotero](https://github.com/Quiet-Signals-Lab/RAG-Assistant-for-Zotero) | 混合排名、按论文组织证据 | RRF 合并关键词和语义排名，每篇限制展示片段数量 |
| [Kotaemon](https://github.com/Cinnamon/kotaemon) | 本地文档问答及安装流程 | 减少首次使用的环境配置；本轮提供 Windows 安装包 |
| [LocalGPT](https://github.com/PromtEngineer/localGPT) | 本机文档检索与多组件本地模型系统 | 保留隐私原则，桌面用户无需手动运行多个开发服务 |
| [RAGFlow](https://github.com/infiniflow/ragflow) | 文档处理与检索基础设施 | 保留原文证据链；复杂文档解析后续独立评估 |

## 0.2 落地

1. Windows 独立窗口，内含 Python 和语义计算运行组件；模型首次单独下载。不要求安装 Python、Node、Docker 或 GPU。
2. 图形界面设置 PDF 许可目录、语义试点收藏夹，设置保存在用户资料目录。
3. 后台同步、索引、期刊检查与模型准备任务；显示阶段和数量，失败提示保留。
4. 作者、年份筛选在召回前生效；混合检索使用 RRF，不比较不同检索器的原始分值；每篇最多展示三个片段。
5. 每条结果展示出处并支持复制；个人笔记和 PDF 原文保持区分。
6. 使用随机回环端口与单实例锁；安装程序不删除研究数据；第三方依赖许可随二进制分发。
7. Windows 两个 Python 版本的源代码检查，独立 Windows 构建和打包后冒烟检查。

## 技术依据

- [pywebview Windows 渲染引擎](https://pywebview.flowrl.com/guide/web_engine.html)：使用 Edge Chromium / WebView2，不降级到过时 IE 内核。
- [pywebview 打包说明](https://pywebview.flowrl.com/guide/freezing.html)与 [PyInstaller spec 文档](https://pyinstaller.org/en/stable/spec-files.html)：显式包含静态资源、动态导入和运行库。
- [Inno Setup 用户级安装](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm)：安装到当前用户目录，使用最低权限。

## 仍需后续工作

向量数据库和重排器的速度评测、笔记组织、结构化论文比较和代码签名。新增来源仍须逐刊核实权限和完整性。

0.3 已增加 Windows 离线 OCR、保存检索、基础阅读笔记和可验证的公开 RSS 设置。OCR 阅读顺序、识别质量及检索相关性仍需独立评估；三刊直接自动来源仍待接入。

## 0.4 再次检索与取舍

2026-11-10 再次检查以下公开一手资料。它们提供产品思路，不构成本项目性能或质量的证明；未复制其他项目代码。并非穷尽整个互联网或照搬所有功能。

| 一手来源 | 值得借鉴 | 本项目本轮落实 |
| --- | --- | --- |
| [Zotero：集合和标签](https://www.zotero.org/support/collections_and_tags) | 按项目与阅读状态组织、过滤条目 | 独立阅读清单与收藏筛选，不写回 Zotero |
| [JabRef 官方仓库](https://github.com/JabRef/jabref) | 阅读管理、组织与导出 | 待读/在读/已读、归档恢复及本机笔记导出 |
| [ZotSeek 官方仓库](https://github.com/introfini/ZotSeek) | 最近检索、混合检索、来源页定位 | 最近 20 次完整检索条件；保留已有 RRF 和页码定位 |
| [Paperless-ngx 使用文档](https://github.com/paperless-ngx/paperless-ngx/blob/dev/docs/usage.md) | 标签、保存视图和持续阅读工作流 | 阅读清单按状态和收藏筛选，保留保存检索 |
| [Paperlib 官方仓库](https://github.com/Future-Scholars/paperlib) | 组织文献和写作时导出的完整工作流 | 把检索、阅读清单、笔记与导出连成一条本地流程 |

Windows 一键升级依据 [GitHub Releases](https://docs.github.com/en/rest/releases/releases)、[发布文件及 digest](https://docs.github.com/en/rest/releases/assets)、[Inno Setup 安装参数](https://jrsoftware.org/ishelp/topic_setupcmdline.htm)和 [pywebview 窗口接口](https://pywebview.flowrl.com/api/)。实现每日检查、版本说明、下载续传、大小/散列核对、退出交接、安装和重新打开原库，不依赖第三方更新服务器。

下一步优先评估相似文献推荐、人工可审查的重复条目提示、多条件主题检索和 Zotero 批注导入。复杂问答、知识图谱、多端同步与自动合并资料需要另行质量和数据保护验证，未列为本版完成项。

## 0.5 多模型 API 与片段阅读

2026-11-10 继续检查公开项目及官方文档。本轮新增或重读下列来源；只借鉴产品设计，没有复制代码，不把项目介绍视为独立效果评测。

| 一手资料 | 借鉴与落实 | 保留的边界 |
| --- | --- | --- |
| [PapersGPT](https://github.com/papersgpt/papersgpt-for-zotero) | 自带 API 密钥、自定义兼容地址、跨文献比较；落实多连接及所选片段比较 | 不自动通读整库、不写回 Zotero；仅可见材料 |
| [Cherry Studio](https://github.com/CherryHQ/cherry-studio)、[连接配置文档](https://cherryai.com/docs/en/mobile/providers-and-models/) | 区分服务商、协议、地址和模型，提供连接测试；落实可编辑预设及多连接 | 未采用其账号登录或密钥迁移机制 |
| [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm)、[兼容服务整合原则](https://github.com/Mintplex-Labs/anything-llm/blob/master/CONTRIBUTING.md) | 用通用协议覆盖同类服务，避免为每个兼容供应商重复开发 | 先保留本机检索及出处，不引入自动代理或多用户部署 |
| [Dify](https://github.com/langgenius/dify) | 将模型接入、检索、生成工作流分开；本项目分别实现连接、预览和按次生成 | 不引入其服务器栈，不复制工作流引擎 |
| [Ollama](https://docs.ollama.com/api/openai-compatibility)、[LM Studio](https://lmstudio.ai/docs/developer/openai-compat) | 本机模型也可接入兼容协议；落实回环地址与可无密钥连接 | 需用户自行启动；其内部转发策略由用户确认 |

按 OpenAI 官方文档优先实现 Responses；保留兼容 Chat 和 Claude Messages。生成答复以普通文字和来源清单展示，用户可以保存为待核对笔记。将费用确认、输出上限、来源变化拒绝、密钥加密和升级保留一并实现，未使用第三方统一代理转发密钥。服务商接入依据、当前兼容范围及未付费联测的说明见 [AI 文档](ai.md)。

后续优先评估人工标注的回答正确性与引用支持评测、适合大库的索引优化和结构化文献比较。自动代理、云端全文索引、自动改写已保存笔记与无审查批量分析本轮未实现。

补充检查了 [PaperQA2](https://github.com/Future-House/paper-qa)、[Zotero Better Notes](https://github.com/windingwind/zotero-better-notes) 和 [Open WebUI 的本机／云端连接文档](https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/)。PaperQA2 将文献检索、片段证据选择和回答分开，并提供可复现实验入口；下一阶段应借鉴其评测思路，用社会学问题检验答案和出处支持，不照搬其科学问答成绩。Better Notes 的笔记关系、批注转笔记和 Markdown 交换值得用于后续阅读积累整合，本版尚未接入其插件 API 或实现双向同步。Open WebUI 区分模型连接及实际推理位置，进一步支持本项目把服务地址与模型 ID 分开、允许多个连接及手动填写模型；没有引入其部署栈、流式聊天或自动模型发现。
