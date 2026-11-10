# Zotero 接入核实与实现边界

核实日期：2026-11-06；分页和可续传改进于 2026-11-07。下列接口结论来自 Zotero 官方文档；自动化测试使用合成响应。

## 接入结论

| 事实 | 对本项目的影响 |
| --- | --- |
| 本地 API 位于 `http://localhost:23119/api/`，须在高级设置开启；读请求无需密钥。 | 默认使用数值回环地址，只发送 GET，关闭环境代理和重定向。 |
| `/users/0/items` 返回本机当前用户的非回收站条目，支持指定分页；`/items/{key}/file/view/url` 返回本地文件 URL。 | Zotero 10 分页获取完整元数据并核对版本，然后逐个解析 PDF 路径；不读取 `zotero.sqlite`。 |
| Zotero 10 引入实例标识及本地版本；此前版本号可能不会随本地修改变化。 | 按实例隔离来源，每次扫描元数据，由应用按内容变化增量建索引，避免仅依赖 `since=`。 |

来源：[Zotero Local API 官方说明](https://www.zotero.org/support/dev/web_api/v3/local_api)、[API 条目端点](https://www.zotero.org/support/dev/web_api/v3/basics)。

存储附件通常位于数据目录的 `storage` 子目录；链接附件可能在别处。请从 Zotero 的“显示数据目录”或附件的“显示文件”找到实际目录，再加入项目的本地许可目录。按需下载的附件可能尚不存在于本机；项目记录提示并保留元数据，不绕过下载或机构访问要求。[数据目录说明](https://www.zotero.org/support/zotero_data)、[存储与链接附件说明](https://www.zotero.org/support/attaching_files)

## 已实现的接口

```python
from sociolit.zotero import ZoteroClient, load_export

with ZoteroClient(allowed_roots=["C:/Users/YOUR_NAME/Zotero/storage"]) as client:
    snapshot = client.snapshot()

# 无本地 API 时，可手动选择 JSON 导出文件。
snapshot = load_export("library.json", allowed_roots=["C:/selected-export-folder"])
```

`Snapshot` 包含稳定来源标识、规范化条目、附件路径、完整性标志和提示。适配器只读取路径，索引和重复判断由本地应用负责。未配置 PDF 目录时可导入元数据，附件显示未授权提示。网络共享、外部 URL、目录穿越和解析后越出许可目录的符号链接均拒绝。元数据格式异常、条目重复、响应数量不符、库版本变化或不安全分页时，整个快照失败，避免将残缺结果误当成删除依据。

JSON 备用入口支持 CSL JSON（仅元数据）和包含 `items`、Zotero 字段及嵌套附件 `path`/`localPath` 的 JSON（包括相应 Better BibTeX JSON 导出）。它不安装插件，也不假定 CSL JSON 自带 PDF。导出相对路径以 JSON 所在目录为基准，再进行同样的许可目录检查。导出只能作为阅读索引的输入，不是 Zotero 备份。[官方导出说明](https://www.zotero.org/support/kb/exporting)

## MVP 范围与待验证事项

- 当前接入个人库 `users/0`，暂未提供群组库、集合筛选、Zotero 写回、自动 OCR 或浏览器插件。
- 若旧版 Zotero 不返回实例标识，来源由回环地址与 `legacy_namespace` 标识；切换旧版数据库时须更换 namespace，以免混合不同库。
- 本机 PDF 缺失或越出许可目录会报告提示，不会改动 Zotero，也不会主动去网络寻找全文。
- 元数据导入与 PDF 路径解析已有离线测试；不同 Zotero 版本、用户实际目录及超大库仍需首次本机接入验收。未宣称已完成真实库兼容性测试。
- Zotero 10 按页读取完整元数据并检验库版本，旧版回退单次快照；尚未使用 Zotero 10 的 `since=` 优化请求量。PDF 内容未变时复用索引，已完成的文件可在中断后复用。
