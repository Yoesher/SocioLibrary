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

向量数据库和重排器的速度评测、笔记组织、结构化论文比较、代码签名和自动升级。新增来源仍须逐刊核实权限和完整性。

0.3 已增加 Windows 离线 OCR、保存检索、基础阅读笔记和可验证的公开 RSS 设置。OCR 阅读顺序、识别质量及检索相关性仍需独立评估；三刊直接自动来源仍待接入。
