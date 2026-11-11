# 第三方依赖与内容

项目自身代码采用 MIT 许可。安装时获取的第三方库仍受各自许可约束；项目不重新授予第三方代码、期刊文章或模型的权利。

| 组件 | 用途 | 官方信息 |
| --- | --- | --- |
| Zotero | 用户自行安装的参考文献管理器；本地 API 集成 | https://www.zotero.org/ |
| pypdf / pypdfium2 | 提取用户本地 PDF 文字与页信息 | https://pypi.org/project/pypdf/ / https://pypi.org/project/pypdfium2/ |
| Sentence Transformers | 可选的本地向量编码 | https://www.sbert.net/ |
| multilingual-e5-small | 可选模型，独立下载，不随源码分发 | https://huggingface.co/intfloat/multilingual-e5-small |
| Cytoscape.js 3.35.0 | 随应用分发的离线图谱引擎；MIT | https://github.com/cytoscape/cytoscape.js/tree/v3.35.0 |

其他运行依赖见 `pyproject.toml`；使用者应以安装版本的分发包、许可和模型卡为准。Zotero 和 PDF 不随本项目分发。期刊目录只用于来源发现；可阅读、可下载和可再次公开分发是不同权限。

Cytoscape.js 的版权与完整 MIT 许可保存在 `src/sociolit/static/cytoscape-LICENSE.txt`，随源码及 Windows 应用内的静态资源分发。固定版本、来源和文件摘要见 [0.8 设计记录](docs/v0.8-search-and-design.md)。Apple 官方指南只用于界面设计参考；未分发 Apple 字体、图标或图片。
