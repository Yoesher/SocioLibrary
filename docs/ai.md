# AI 文献阅读与 API 配置（Windows 0.5）

AI 是可选功能。未配置或未点击发送时，文献检索、Zotero、OCR、笔记及期刊发现继续使用，不调用生成式 AI。原有模型下载和期刊联网仍按原功能执行。

## 配置自己的连接

在“AI 文献阅读”新增连接，选择服务示例，填写 API 基础地址、自己账号可用的模型 ID 和密钥，保存。最多保留 20 个连接。软件不包含赠送额度，不把某个模型名写成永久默认。

| 服务 | 协议 | 基础地址 |
| --- | --- | --- |
| OpenAI / ChatGPT API | Responses，优先使用 | `https://api.openai.com/v1` |
| 自定义兼容服务 | Chat 或 Responses，按其文档选择 | 服务商控制台提供的 HTTPS 基础地址 |
| Anthropic / Claude | Messages | `https://api.anthropic.com/v1` |
| Google Gemini | OpenAI 兼容 Chat | 预设 `https://generativelanguage.googleapis.com/v1beta/openai`，以当前控制台为准 |
| DeepSeek | OpenAI 兼容 Chat | `https://api.deepseek.com` |
| 通义千问 / 百炼 | OpenAI 兼容 Chat | 从所在地域、业务空间控制台复制，密钥与地址需匹配 |
| Ollama | OpenAI 兼容 Chat | 本机默认 `http://127.0.0.1:11434/v1` |
| LM Studio | OpenAI 兼容 Chat | 本机默认 `http://127.0.0.1:1234/v1` |

这些是配置模板。三种协议已用合成响应验证，不表示每个厂商、模型及个人账号均已付费联测。Gemini 官方页面本轮抓取返回不支持的 Markdown 或访问失败，预设依据官方搜索索引提供的兼容地址，仍需个人账号核验。依赖 OAuth、AWS 签名、额外专有参数或强制流式思考的服务，不属于通用兼容范围。本版仅文本单轮请求，无文件上传、视觉、语音、工具调用、云端嵌入或自动代理。

基础地址后自动追加 `/responses`、`/chat/completions` 或 `/messages`，不要重复填写。不得携带账号、密钥或查询参数。云端使用 HTTPS，本机回环可用 HTTP；不跟随重定向、不关闭证书校验、不读取环境代理设置。本机服务是否转发云端取决于其自身配置，不保证它一定离线。

兼容 Chat 默认使用 `max_tokens`，OpenAI 官方主机自动使用 `max_completion_tokens`；可在兼容选项明确选择。通义示例默认勾选 `enable_thinking=false`，仅适用于支持该扩展的模型，其他模型按服务商文档取消。两项兼容选项不影响 Responses 或 Claude。Claude 使用 `anthropic-version: 2023-06-01` 与 `x-api-key`；请使用适用此协议的密钥和模型。

“测试当前连接”发送固定短提示，最多输出 64 tokens，不发送文献。测试可能计费，需先确认。若推理用完测试额度还未生成文字，会显示“请求已获接受，完整生成尚未验证”。失败或超时不自动重试，服务商仍可能已计费。

OpenAI 使用 API 平台密钥及该账号可用额度，不使用 ChatGPT 网页登录 Cookie、订阅会话或 Codex 凭据。不要自行把 ChatGPT 内额度视作本软件可用 API 余额，以平台实际授权和计费为准。请只在本机密钥框填写，不在聊天、GitHub 或截图中发送密钥。

## 从原文片段开始

1. 在全文、语义或混合检索结果勾选“用于 AI 阅读”，每次 1–8 个片段。
2. 选择连接、归纳／比较／翻译／提问任务，填写问题，点击预览。本机核验片段没有因同步变化；每段最多 1800 字符，正文总计最多 12000 字符，截短会标明。
3. 核对接收地址、模型、实际材料和完整系统提示，再确认发送。只发送预览中的问题、系统提示、所选文字和题名、作者、年份、类型及已知页码；不发送 PDF 文件、路径或未选内容。预览有效十分钟，单次使用；连接或材料变化需重新预览。
4. 答复用普通文字显示，列出 `[S1]` 等对应片段和原文页链接。不存在的编号或缺少编号会警示。编号校验不代表论断获证，仍须核对原文；软件不会把片段阅读称为通读全文。
5. 可复制，或在生成后十分钟内保存成标明“AI 生成草稿，未经人工核对”的本地阅读笔记，附本次来源快照；按原流程编辑、归档和导出。未保存的预览及答复仅在内存中，退出不恢复。

云端内容处理依接收服务商政策。OpenAI Responses 及其官方 Chat 请求设置 `store=false`；此选项不是“云端完全不留存”的承诺，也不强加给所有兼容服务。

## 密钥、费用与升级

密钥由 Windows DPAPI 按当前账号加密，保存在资料目录的 `ai-profiles.json`，不回传页面、不放入浏览器本地存储或文献数据库、不加入公共仓库或发布包。密钥绑定连接 ID、地址与协议；修改地址或协议不沿用旧密钥，换模型可沿用。页面只显示是否已保存；错误响应不回显密钥或服务商原始错误正文。

DPAPI 不能防止同一 Windows 账号下的恶意进程读取已解密内容。迁移到其他电脑或账号通常需重新填写。移除连接删除当前配置的密钥记录，旧升级备份可能仍含加密副本；如需撤销访问，应在服务商控制台撤销密钥。

Mac 预览版使用固定的系统钥匙串后端，`ai-profiles.json` 只保存不透明引用，没有明文回退；密钥仍绑定连接及目标。系统可能弹出访问授权窗口，拒绝或钥匙串不可用时会提示失败。Windows 加密内容不能直接迁移到 Mac，需要重新配置。旧钥匙串条目可能仍被备份引用，移除当前连接不等于在服务商处撤销密钥。[Mac 安装与范围](macos.md)

升级沿用原目录，快照包含加密 AI 配置。不自动批量读库或重试付费请求。单次输出上限 256–8192 tokens，可见服务商报告的输入／输出用量；输入、缓存、推理等可能另行计费，费用和账户限额以服务商为准。字符数不等于 token 数，本版没有跨服务商月度预算保证。

## 一手依据

- [OpenAI Responses 与保存选项](https://developers.openai.com/api/docs/guides/migrate-to-responses)、[数据控制](https://developers.openai.com/api/docs/guides/your-data)。
- [Claude Messages](https://platform.claude.com/docs/en/api/messages/create)、[API 版本](https://platform.claude.com/docs/en/api/versioning)。
- [Gemini 兼容文档](https://ai.google.dev/gemini-api/docs/openai)、[DeepSeek](https://api-docs.deepseek.com/)、[百炼兼容 Chat](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)。
- [Ollama](https://docs.ollama.com/api/openai-compatibility)、[LM Studio](https://lmstudio.ai/docs/developer/openai-compat)。
- [Microsoft CryptProtectData](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)。
