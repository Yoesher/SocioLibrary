# 同类项目调研与优化取舍

核查日期：2026-11-11。按本地文献管理、Zotero 插件、文献图谱、个人知识库、期刊订阅五条线，检索 GitHub 仓库及官方产品文档。下表是本轮重点对照的项目，不代表穷尽所有网站或对上游软件完成实机评测。功能描述来自上游文档，采纳方式是本项目的实现判断。

| 项目 / 官方来源 | 值得借鉴的能力 | SocioLibrary 的处理 |
| --- | --- | --- |
| [Paperlib](https://github.com/Future-Scholars/paperlib) | RSS、智能筛选、标签与笔记、桌面文献工作流 | 本轮加入可筛读的期刊收件箱，接到文献详情与图谱 |
| [Better Notes](https://github.com/windingwind/zotero-better-notes) | 笔记链接、模板、多种导出及 Markdown 互通 | 本轮增加文献笔记研究包，保留摘要来源、可选批注与 Zotero 链接；不宣称双向同步 |
| [ZotSeek](https://github.com/introfini/ZotSeek) | 本机语义检索、相似研究、可选只读 MCP | 继续坚持本机索引与明确授权；MCP 另作后续方向，尚未接入 |
| [Better BibTeX](https://retorque.re/zotero-better-bibtex/) | 文本写作工具链与引用标识 | 研究包采用稳定散列文件名、DOI 与 Zotero 条目标识；不生成未经核对的引用键 |
| [Obsidian Reference Map](https://github.com/anoopkcn/obsidian-reference-map) | 文献发现中的引用与关系浏览 | 区分自动线索、人工确认关系、保存时快照；不将词语相近伪装成真实引文 |
| [ResearchRabbit](https://www.researchrabbit.ai/) | 从种子文献逐步探索研究联系 | 沿用原位展开，本轮使研究图谱能够持久保存和恢复 |
| [Litmaps Monitor](https://docs.litmaps.com/en/articles/9126249-monitor-get-alerts-for-important-research) | 关注研究后的持续更新 | 本轮补齐未读、收藏和发表/发现日期；邮件提醒尚未实现 |
| [Obsidian / JSON Canvas](https://jsoncanvas.org/spec/1.0/) | 开放的节点、文件与边格式 | 本轮导出标准 .canvas 与 Markdown 笔记 ZIP，可在 Obsidian 继续整理 |
| [JabRef](https://github.com/JabRef/jabref) | 桌面书目与 BibTeX/BibLaTeX 管理 | 保持本地资料的独立性；更完整的引用格式互通列入后续计划 |
| [Karakeep](https://github.com/karakeep-app/karakeep) | 自托管收藏、全文检索、可选 AI 标签 | 借鉴显式整理与筛选，保留 AI 按次确认，不自动发送全部文献 |
| [Khoj 搜索文档](https://github.com/khoj-ai/khoj/blob/master/documentation/docs/features/search.md) | 检索与重排分层 | 重排需要先做中文社会学语料的相关性与 CPU 成本评测，本轮未自动下载新重排模型 |
| [Paperless-ngx](https://github.com/paperless-ngx/paperless-ngx) | 扫描、索引与归档流程 | 保留派生索引与原始 PDF 分离、明确任务状态；扫描阅读顺序评测继续推进 |

## 本轮落实

1. 保存命名研究图谱：文献集合、位置、固定节点、视角与筛选可重开恢复。关系由服务器按书目重新核验后保存，恢复时明确为历史快照；不接受浏览器任意传入的引文关系。保存时的关系可能与原探索过程中的候选边略有不同。
2. 期刊收件箱：分页、期刊与关键词筛选、未读和收藏；书目更正重新提示未读，收藏保留；普通重复检查不重置阅读状态。首次发现时间不当作发表时间。
3. 开放研究包：标准 JSON Canvas + Markdown 来源摘要与关系链接，批注需主动勾选；不附带 PDF、密钥或绝对路径。每篇最多20条批注，摘录/评论各4000字、摘要6000字，总文本20MB以内。
4. Mac 原生发布链路：Apple 芯片与 Intel 分别构建，Cocoa 窗口、独立资料目录、系统钥匙串、Zotero 页链接、原生保存窗口。

## 暂未纳入

- 自动推断真实引用关系、自动给研究结论背书：需要可靠引用数据或人工核验。
- 全库自动云端 AI 整理与无感上传：继续按次选择和确认材料。
- 重型模型或图数据库强制常驻：先评测必要性、CPU 与磁盘成本。
- 笔记双向同步、邮件/微信提醒、共同编辑、远程 MCP：尚未实现，避免混入现有稳定工作流。

## 实现与许可

本轮参考交互、工作流和公开数据格式，代码独立编写，没有复制上述仓库源码或打包其图片。上游许可各不相同，后续如引入代码或依赖，需要逐项核对许可并补齐第三方声明。官方 JSON Canvas 规范用于互通格式。
