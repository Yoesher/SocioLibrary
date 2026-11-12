<p align="center"><strong>简体中文</strong> · <a href="README.en.md">English</a></p>

<p align="center"><img src="docs/assets/sociolibrary-cover.svg" alt="SocioLibrary" width="1280"></p>

<p align="center"><strong>把文献连成研究。</strong><br>本地优先的文献工作台，将 Zotero、检索、阅读与研究图谱放在一起。</p>

<p align="center"><a href="https://github.com/Yoesher/SocioLibrary/releases/latest"><strong>下载软件</strong></a> · <a href="docs/windows.md">开始使用</a> · <a href="docs/README.md">使用文档</a> · <a href="https://github.com/Yoesher/SocioLibrary/issues">反馈问题</a></p>

## 下载

**当前版本 0.12.3** · Windows 10 / 11 x64 · macOS 15+ 预览版

| 你的电脑 | 软件包 | 使用方式 |
| --- | --- | --- |
| **Windows · 推荐** | [**下载安装版**](https://github.com/Yoesher/SocioLibrary/releases/download/v0.12.3/SocioLibrary-0.12.3-Windows-x64-Setup.exe) | 安装后使用；支持软件内升级 |
| Windows · 免安装 | [下载完整 ZIP](https://github.com/Yoesher/SocioLibrary/releases/download/v0.12.3/SocioLibrary-0.12.3-Windows-x64-Portable.zip) | 完整解压后运行，保留全部程序文件 |
| Mac · Apple 芯片 | [下载 arm64 ZIP](https://github.com/Yoesher/SocioLibrary/releases/download/v0.12.3/SocioLibrary-0.12.3-macOS-arm64.zip) | 退出旧版后替换应用 |
| Mac · Intel 芯片 | [下载 x86_64 ZIP](https://github.com/Yoesher/SocioLibrary/releases/download/v0.12.3/SocioLibrary-0.12.3-macOS-x86_64.zip) | 退出旧版后替换应用 |

已有 Windows 版本可进入 **软件更新 → 检查更新**，也可退出后运行安装包覆盖升级。原文库、模型、笔记和设置继续沿用，升级前会建立本机快照。校验值见[发行说明](https://github.com/Yoesher/SocioLibrary/releases/latest)。

<details>
<summary>Mac 预览版与安装范围</summary>

Mac 包面向 macOS 15+，尚未 Apple Developer ID 签名或公证；Intel 版暂不附带本地语义运行环境。Mac 暂不提供扫描页 OCR 和自动替换应用。Windows 包尚未代码签名，部分电脑需要安装微软 WebView2 Runtime。请从本仓库下载并保留系统安全保护。[Windows 安装](docs/windows.md) · [Mac 安装](docs/macos.md)

</details>

## 从收藏到研究

| 接入与查找 | 阅读与比较 | 关联与积累 |
| --- | --- | --- |
| 只读导入 Zotero 书目、PDF、笔记与批注；按变化增量同步 | 每篇展示来源摘要、查询关联和正文命中页 | 从一篇文献展开动态网络，核对每条关系的依据 |
| 中文检索英文资料；字词、语义与混合检索 | 在 Zotero 打开对应附件页，保存带出处的阅读笔记 | 保存研究图谱，导出 Obsidian 画布与文献笔记 |
| 按作者、年份筛选；保存和重用检索条件 | 相似推荐、阅读清单和结构化文献对照 | 自选期刊来源，按月发现新文献与书目更正 |

图谱单视图最多 80 篇，支持原位展开、拖动固定、暂停动态和探索返回。自动连线用于发现阅读线索；摘要、页码与关系解释均需结合原文核对。[图谱与研究包](docs/v0.12-research-workspace.md) · [推荐、批注与比较](docs/reading-tools.md)

## 三步开始

1. **连接 Zotero。** 保持 Zotero 运行，在其“设置 → 高级”中允许本机应用通信。
2. **选择资料范围。** 在 SocioLibrary 的“资料与设置”选择允许读取的 PDF 文件夹，测试连接后同步。
3. **从一个问题开始。** 检索、查看命中页，再进入笔记、比较或图谱。需要语义检索时另行下载本地模型并建立索引；大库可先选核心文件夹。

全文检索可独立运行；语义模型在本机计算。AI 是可选连接，使用你自己的 API，发送前逐次预览并确认材料。[Zotero 接入](docs/zotero-research.md) · [AI 配置与发送预览](docs/ai.md)

## 文献留在本机

- 通过 Zotero 本机接口读取，**不读取或上传 Zotero 数据库**。原 PDF 保留在原位置。
- 文库、笔记、索引与密钥保存在本机；同步整理只维护派生索引，不自动删除论文或合并 Zotero 条目。
- 本地检索和阅读可离线使用。期刊发现、模型下载、软件更新及你选择的 AI 服务需要联网；研究材料按次确认后才发送到所配置的 AI 接口。

<details>
<summary>期刊更新如何接入？</summary>

在“期刊动态”添加官网 RSS / Atom，或通过 Crossref 的 ISSN 接入；OpenAlex 需先在本机配置密钥。来源可以验证、修改、暂停及恢复，发现的书目进入软件内收件箱。

内置来源中，《社会》《人口研究》的当期与过刊目录，以及《社会学研究》《中国人口科学》的当期目录已接入；《社会学评论》《人口学刊》《中国社会科学》仍为待接入。当前目录来源可能漏掉长期未运行期间的期次。只发现元数据与来源链接，全文遵从版权与机构访问限制。[接入步骤](docs/v0.11-graph-and-journals.md) · [逐刊状态](docs/discovery-research.md)

</details>

<details>
<summary>界面与维护</summary>

Apple、Windows、Material 三套界面风格可在“资料与设置”中预览、保存和切换；布局、控件、字体层级与动效一同变化，配色另行选择。

0.12.3 集中优化启动、空闲资源占用、配置保存与 Windows 安装文件体积。数据更新会使展示统计缓存失效；任务和升级判断保持实时。精简与升级清理仅针对经校验的程序文件，保留研究资料和已修改文件。[版本记录](CHANGELOG.md) · [升级与恢复](docs/windows.md#资料升级与退出)

</details>

## 文档与参与

[使用指南](docs/README.md) · [开发与命令](docs/development.md) · [项目架构](docs/architecture.md) · [验证记录](docs/validation.md) · [维护与发布](docs/releasing.md)

[贡献指南](CONTRIBUTING.md) · [安全与隐私](SECURITY.md) · [第三方依赖](THIRD_PARTY_NOTICES.md) · [MIT 许可](LICENSE)

欢迎提交可复现的问题。分享日志或示例前，请去除私人文献、API 密钥和个人路径。
