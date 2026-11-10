# Windows 桌面版

面向 Windows 10 / 11 x64；本轮不发布 macOS、Linux、ARM 原生或 32 位安装包。

## 安装

从 [GitHub Releases](https://github.com/Yoesher/SocioLibrary/releases) 下载名称包含 `Windows-x64-Setup.exe` 的安装包。双击后安装到当前用户目录，开始菜单中启动 SocioLibrary。无需安装 Python、Node 或 Docker。

免安装版为 `Windows-x64-Portable.zip`，解压整个目录并运行其中的 `SocioLibrary.exe`，不可只拷贝 exe。免安装指程序无需安装，研究资料仍保存在用户资料目录，不会跟着 U 盘移动。

界面使用 Microsoft Edge WebView2。若机器尚未安装，请从 [微软官方页面](https://developer.microsoft.com/microsoft-edge/webview2/) 安装 Evergreen Runtime；软件不使用旧 IE 渲染器。安装包当前没有代码签名，可能显示来源未知；请核对官方发布来源和 SHA256SUMS，不应关闭系统安全保护。

## 第一次使用

1. 打开 Zotero，在设置 → 高级中允许本机应用通信。
2. 打开“资料与设置”，点击“测试连接”，选择存放 PDF 的 storage 或链接附件文件夹并保存。
3. 点击“同步 Zotero”。任务在后台运行，窗口内显示阶段；可继续全文检索。初次大型索引需要较长时间。
4. 如需要语义检索，下载本地模型，填写试点文件夹名称，再构建索引。语义和混合检索需要模型与完整索引。

## 资料、升级与退出

资料保存在 `%LOCALAPPDATA%/SocioLit`。文献原文件仍由 Zotero 管理。桌面版复用既有 SocioLibrary 资料目录；首次仍需确认 PDF 许可范围。修改文件夹范围后，重新构建语义索引。

覆盖升级只更新程序；卸载不会主动删除文献索引、模型和本地设置。备份前关闭软件和其他 SocioLibrary 写入进程，然后复制整个资料目录。不要同时启动旧版脚本执行导入。

软件关闭时本轮后台工作会中断；已提交的文件和向量保留，下次可以继续同步或构建。模型下载受网络影响；失败后请根据提示重试。下载不会上传文献。

桌面软件启动时按来源检查本月是否已更新；只有软件启动并联网时运行。不是后台常驻服务。已有命令行定时任务仍可继续使用，桌面版不会自动新增系统任务。

## 构建

开发者使用 Windows x64、Python 3.11、Inno Setup 6。先从官方 PyTorch CPU 索引安装 CPU 版 torch，再安装 `.[desktop,semantic,dev]`，执行 `scripts/build-windows.ps1`。二进制只包含程序、依赖、公开配置和许可；不包含真实资料或模型权重。

GitHub 的 Build Windows desktop 工作流构建安装版和免安装版，检查打包后的本地服务、静态资源、PDF DLL 和语义运行组件。完整模型检索效果和不同 Windows 版本仍需用户环境验收，不将冒烟检查当作全部功能评测。
