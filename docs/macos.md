# macOS 预览版

首版提供 Apple 芯片 arm64 与 Intel x86_64 的独立包，面向 macOS 15 或更新版本。构建和启动验证在对应架构的 macOS 15 环境进行；不能据此保证所有旧系统或所有用户机器兼容。

## 安装与升级

从本项目 Releases 下载对应芯片的 ZIP，完整解压后将 SocioLibrary.app 移动到 Applications。先退出旧版，再替换应用。请保留原资料目录，不需要重新导入旧库。

研究资料默认位于 `~/Library/Application Support/SocioLit`；记忆目录指针在 `~/Library/Application Support/SocioLibrary`。程序替换与资料目录分离；首次打开新版本先建立本机升级快照。卸载应用不会自动删除研究目录。请另行备份原 PDF 和完整资料。

本构建只有临时本机签名，没有 Apple Developer ID 签名及 Apple 公证。GitHub 构建环境中可以启动，不代表下载后能通过每台 Mac 的 Gatekeeper 分发检查。不要关闭系统安全设置；遇到系统阻止时请参考 [Apple 官方说明](https://support.apple.com/en-us/102445)，或等待开发者签名和公证版本。

## 功能范围

| 能力 | Apple 芯片 | Intel 预览版 |
| --- | --- | --- |
| Zotero 个人库只读导入、已有文字层 PDF 检索 | 支持 | 支持 |
| 中英词语扩展检索、摘要与页码位置 | 支持 | 支持 |
| 本地多语言语义检索 | 包含运行环境，模型另行下载 | 暂未附带运行环境 |
| 图谱、保存视图、批注、比较、期刊收件箱 | 支持 | 支持 |
| 自选云端/本机 AI 接口 | 支持 | 支持 |
| 密钥存储 | macOS 系统钥匙串 | macOS 系统钥匙串 |
| Windows 系统扫描页 OCR | 不提供 | 不提供 |
| 软件内检查更新 | 支持 | 支持 |
| 自动覆盖安装 | 首版手动替换应用 | 首版手动替换应用 |

Intel Mac 不使用已停止维护的旧版 PyTorch 运行环境来凑齐语义功能；后续另评估 ONNX 等方案。缺少本地语义环境时，仍可使用全文检索和中英词语扩展，但这不等于语义检索。

打开 Zotero，在设置中允许本机应用通信；在本软件选择允许读取的 storage/链接附件文件夹，再同步。Zotero 页跳转使用官方应用协议，不读 Zotero 数据库。

AI 密钥使用固定的 macOS Keychain 后端，没有明文回退。系统可能要求你自行确认钥匙串访问；拒绝或不可用时会报错，不会把密钥写进配置。Windows 的加密密钥不能直接复制到 Mac 使用，需要重新配置。研究包导出到你选择的本机位置，若要分享请自行检查其中的摘要和批注。

## 构建

在 macOS 安装项目的 desktop/dev 依赖，Apple 芯片额外安装 semantic 依赖，运行 `python scripts/build_macos.py`。GitHub Actions 使用 `macos-15`（arm64）和 `macos-15-intel`，检查源码、包签名完整性、冻结程序独立启动和实际 Cocoa 窗口加载。CI 使用合成资料，不包含个人文献或密钥。

参考：[GitHub runner 架构](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)、[pywebview 安装](https://pywebview.flowrl.com/guide/installation)、[PyTorch Intel Mac 构建停止维护公告](https://dev-discuss.pytorch.org/t/pytorch-macos-x86-builds-deprecation-starting-january-2024/1690)、[Keyring 文档](https://keyring.readthedocs.io/en/latest/)。
