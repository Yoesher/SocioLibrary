# 每月期刊发现与提醒

核验日期：2026-11-06。默认采用本地更新；GitHub Actions 是可选的公共元数据发现渠道。

## 本地更新是主渠道

在本机运行 `python -m sociolit discover --config config.local.toml --output reports`。本地数据目录保留去重记录和来源进度；连续运行可以识别已发现文献，更新已有元数据。长期维护建议在操作系统的任务计划程序中每月执行同一命令，并保持同一配置和数据目录。电脑关机时不会运行，需要启用错过计划后的补跑选项。订阅设置应放在被忽略的本地配置中。

`digest.md` 是当次可读摘要，`records.json` 是公开文献元数据。命令执行后可以在本地界面查看新发现条目；它不会自动代你发送邮件、创建 Issue 或向他人推送消息。来源失败会写入报告并返回失败状态，避免把采集失败误认为“本月无新文献”。

## GitHub Actions 可行性和边界

模板每月 1 日 UTC 02:17（北京时间 10:17）执行。定时工作流只从默认分支运行；高峰期可能延迟或丢弃任务；公开仓库连续 60 天无仓库活动会停用定时任务。因此不能把它视为保证送达、永不停止的定时服务。可以在 Actions 页面手动执行和重新启用；失约月份也可在本地补查。[GitHub 定时事件说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

每次云端运行使用新的临时数据库，默认只输出回看窗口内的元数据，不读取或上传本地 Zotero、全文索引或 PDF。云端报告在单次运行内去重；不同月份回看窗口重叠时可能重复列出同一篇文献。跨月历史去重以本地持久数据库为准。模板没有把数据库当缓存上传，也没有自动提交“状态文件”到公开仓库。

启用步骤：

1. 先按 README 完成本地测试，再自行创建仓库并审核待上传文件。
2. 把允许公开的订阅填入 `config/public-journals.toml`，将对应期刊的 `enabled` 设为 `true`。期刊清单本身可能透露研究兴趣，不想公开的订阅只保存在本地。
3. 如启用 OpenAlex，在仓库 Settings → Secrets and variables → Actions 中设置 `OPENALEX_API_KEY`。可选设置 `CROSSREF_MAILTO`。不要把密钥写进配置或工作流。
4. 设置仓库变量 `ENABLE_JOURNAL_DISCOVERY` 为字符串 `true`。默认未设置时，手动和定时入口都跳过采集。
5. 在 Actions 页面运行一次 **Monthly public journal discovery**，检查摘要、失败提示和附件，再启用自己的通知偏好。

工作流只需要 `contents: read`，不自动创建提交、Issue、PR 或邮件。它使用 GitHub 托管的临时运行环境；只把 `digest.md` 与 `records.json` 两个明确列出的文件作为 artifact 保存 35 天。GitHub 允许设置 artifact 保留期，但不得超过仓库或组织上限。公开仓库中的报告应按公开内容对待。[GitHub artifacts 文档](https://docs.github.com/en/actions/tutorials/store-and-share-data)

## 提醒意味着什么

每次执行在 Actions 页面生成摘要和运行状态，摘要本身不是主动推送。需要 GitHub 通知时，在账号通知设置中启用 Actions 的站内或邮件通知；只开启“失败时通知”不会提醒正常完成的新文献报告。定时任务的通知接收人与最后修改 cron 表达式的用户有关，不能假定所有仓库关注者都会收到每份月报。[Actions 通知设置](https://docs.github.com/en/subscriptions-and-notifications/how-tos/managing-github-actions-notifications)、[定时任务通知对象](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#actor-for-scheduled-workflows)

本项目没有承诺“发现新文献才推送”的云端邮件服务。后续如需此功能，应选择私人通知渠道、持久化去重状态并明确收件人，再单独启用。

## 密钥和公开配置

GitHub Secrets 的日志脱敏并非绝对安全边界，工作流代码仍能读取注入给它的密钥。模板只在发现步骤注入所需密钥，第三方 Action 固定到已核验的提交。不要将本地文件、含认证参数的 RSS 地址、机构 Cookie 或个人全文库用于公共配置。修改工作流和依赖后应重新审查，尤其不能让不可信 PR 代码在带密钥的上下文中执行。[GitHub Secrets 说明](https://docs.github.com/en/actions/concepts/security/secrets)、[GitHub 运行环境安全](https://docs.github.com/en/actions/concepts/security/compromised-runners)
