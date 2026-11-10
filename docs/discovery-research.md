# 期刊发现：接口核实与覆盖边界

## 2026-11-07 本次新增

[《社会学研究》](https://shxyj.ajcass.com/)和[《中国人口科学》](https://zgrkkx.ajcass.com/)官网当期目录已分别接入；本机首轮识别 11 条和 8 条书目信息。只检查当前一期，不提供准确发表日期，也不能回查中间期次或覆盖网络首发；长期未运行可能漏期。只读取公开首页中的标题、作者、年份和文章链接，不抓取摘要或全文。

两站 robots.txt 返回 404；按照 [RFC 9309 第 2.3.1.3 节](https://www.rfc-editor.org/rfc/rfc9309.html#section-2.3.1.3)，不存在的 robots 文件不构成限制，但也不等于内容授权。每次重查，403、网络异常和异常页面均停止；如果将来返回可用策略则遵循策略。对目录外的内容、全文和付费服务不作使用授权推断。

《社会学评论》官网本机 HTTPS 证书验证失败；《中国社会科学》官网本机返回 403。另查到《人口学刊》[维普目录](https://www.cqvip.com/journal/91708X/91708X)和[龙源期刊目录](https://www.qikan.com.cn/magdetails/8D49FDE1-B642-466E-9994-38D1DE32979C/2026/1.html)，可供人工查阅，尚未核实适用于自动采集的授权及可靠更新方式，故不自动抓取。以上三刊仍待接入。

## 此前核验与接入

此前“人口研究未发现 RSS 入口”的记录需要更正：[官方 RSS 页面](https://rkyj.ruc.edu.cn/CN/rss/showRssInfo.do)实际列出多个 feed；但当期目录链接实测返回 HTTP 404，不能当作正常订阅源。

[《人口研究》当期目录](https://rkyj.ruc.edu.cn/CN/1000-6087/current.shtml)与[《社会》当期目录](https://www.society.shu.edu.cn/CN/1004-8804/current.shtml)可直接读取期刊、篇名、作者和期次；两站 [人口研究 robots.txt](https://rkyj.ruc.edu.cn/robots.txt) 与 [社会 robots.txt](https://www.society.shu.edu.cn/robots.txt) 当日均声明允许访问。程序现已分别接入这两个已核验来源，处理公开目录中的题名、作者、刊期及原站链接，不保存摘要、不抓取全文。

接口每次重新核验 robots.txt，限制访问固定官方主机和预定义目录；按“上一期”补查至窗口之前，检查刊期、文章链接及作者，碰到拒绝、页面变化、不完整或页数上限时报告失败并保留旧水位。首次建立基线时会包含窗口之前的最近一期，首批新增数并不等于当月发表数。目录没有覆盖的网络首发文章无法保证发现。系统不绕过登录、反爬、付费或机构访问控制，站点条款或政策变化应重新核查。

此前五刊均未完成来源接入；当前状态以本页顶部和配置为准。以下表格与原始结论保留 2026-11-06 的历史核验口径；当前启用状态以上述更新和配置为准。

后续可核查的候选是中国社会科学院图书馆承建的国家哲学社会科学文献中心：搜索服务可以检索到其[《社会学研究》目录](https://www.ncpssd.org/journal/details?gch=80772X&langType=1&num=2&years=2022)、[《社会学评论》目录](https://ncpssd.org/journal/details?gch=60708X&langType=1)、[《中国人口科学》目录](https://www.ncpssd.org/journal/details.aspx?gch=97725X&langType=1&nav=1)和[《中国社会科学》目录](https://www.ncpssd.org/journal/details.aspx?gch=81908X&langType=1&nav=1)。但本机直接请求目录和 robots.txt 均收到 HTTP 403；搜索服务能看到页面不能证明本地程序获得使用许可，因此未绕过限制，也未启用此源。《人口学刊》的可靠目录编号尚未确认，不能用名称相近的其他期刊替代。

核实日期：2026-11-06。下面区分“接口可以运行”与“指定期刊确有持续数据”。前者不能代替后者。本项目仅收集书目元数据、DOI 和原站链接，不抓取期刊全文，不复制机构访问凭据。

## 接口选择

| 来源 | MVP 实现 | 关键限制 |
| --- | --- | --- |
| Crossref | `/journals/{issn}/works`，索引日期窗口，游标分页 | 只覆盖该注册机构收到且能按 ISSN 查到的元数据；有 DOI 不代表在 Crossref 有记录 |
| OpenAlex | `/works`，`primary_location.source.issn`，发表日期窗口，游标分页 | 跨页使用环境变量中的有效 API key；免费发表日期回查不等于完整变更同步 |
| 官方 RSS/Atom | HTTPS 订阅地址，RSS 2.0、RSS 1.0/RDF、Atom 解析 | 网站列出 RSS 图标不等于 feed 可用；月查可能错过已从短期 feed 移除的文章 |

Crossref 的公开接口无需注册；可通过 `CROSSREF_MAILTO` 提供联系邮箱进入 polite pool。实现按顺序请求，每次至少间隔 0.25 秒，遇到 429 或部分服务端错误最多尝试三次，并尊重 `Retry-After`；超过 60 秒的等待转为可见错误，交给下次运行重试。当前官方文档列出的 public/polite 并发与速率限制不同，实际限额仍以响应头为准。[Crossref 接入说明](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/)

Crossref 官方建议用 `from-index-date` / `until-index-date` 跟踪增量变化。本项目保留闭合时间窗口，每页都携带原始筛选参数，并使用响应中的新游标。达到页数上限、游标重复、响应异常都使该来源“不完整”，上层调度不得推进其成功水位。[增量同步与分页](https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/)、[2026 年游标变化公告](https://community.crossref.org/t/changes-to-cursors-filtering-and-sorting-in-the-rest-api/16246)

OpenAlex 2026-11-03 更新的官方文档允许无密钥的基础查询，但游标翻页超过第一页需要免费且已验证的 API key。支持的 `per_page` 上限为 100。本项目为避免“第一页成功但静默漏页”，启用 OpenAlex 时要求 `OPENALEX_API_KEY`，仅放在 Authorization 请求头，不写入 URL、配置或日志。本项目不会代用户申请账号、发验证邮件或启用付费服务。[身份验证](https://help.openalex.org/api/authentication/)、[分页](https://help.openalex.org/api/paging/)

OpenAlex 的 `from_updated_date`、`from_created_date` 等同步过滤器需要特定付费计划。因此 MVP 使用免费的发表日期窗口回查，并在每次报告中提示：窗口之外的迟收录文章及旧文章修正可能遗漏。需要完整历史更新时，应单独评估付费同步或合法快照，不把免费发表日期检索写成完整同步。[过滤与同步权限](https://help.openalex.org/api/filtering/)

## 用户指定的七本期刊：实测结果

测试口径：Crossref `journals/{ISSN}/works?rows=1&sort=published&order=desc`；OpenAlex `works?filter=primary_location.source.issn:{ISSN}&per_page=1&sort=publication_date:desc`，默认 core 语料。请求只使用公开 ISSN，不含用户文献。中国人口科学、中国社会科学的 Crossref 首次请求超时，随后以 `rows=0` 复查得到 404。下表是当日接口返回，不是对所有商业数据库的覆盖断言。

| 期刊 | ISSN | Crossref journal works | OpenAlex 严格 ISSN 查询 | 当前判断 |
| --- | --- | --- | --- | --- |
| 社会学研究 | 1002-5936 | 404 | 98 条，最近日期 2021-07-06 | 不足以支撑月更；首条结果的落地页为伊朗期刊域名，存在疑似错误归刊 |
| 社会学评论 | 2095-5154 | 404 | 0 条 | 不能据此启动可靠月更 |
| 社会 | 1004-8804 | 404 | 0 条 | 不能据此启动可靠月更 |
| 人口学刊 | 1004-129X | 404 | 805 条，最近日期 2016-01-01 | 以旧记录为主，不能代表当前目录 |
| 人口研究 | 1000-6087 | 404 | 472 条，最近日期 2021-09-29 | 不能代表当前目录 |
| 中国人口科学 | 1000-7881 | 404 | 0 条 | 不能据此启动可靠月更 |
| 中国社会科学 | 1002-4921 | 404 | 0 条 | 中文刊不能替换为同名英文刊的 ISSN |

可复查的官方 API 示例：[Crossref 社会学研究](https://api.crossref.org/journals/1002-5936/works?rows=1)、[OpenAlex 社会学研究](https://api.openalex.org/works?filter=primary_location.source.issn:1002-5936&per_page=1&sort=publication_date:desc)、[OpenAlex 人口学刊](https://api.openalex.org/works?filter=primary_location.source.issn:1004-129X&per_page=1&sort=publication_date:desc)、[OpenAlex 人口研究](https://api.openalex.org/works?filter=primary_location.source.issn:1000-6087&per_page=1&sort=publication_date:desc)。这些地址会随数据更新而变化。

ISSN 核对来源：[社会学研究 2026 年原版刊物目录与版权页（杭州师范大学存档）](https://www.hznu.edu.cn/upload/resources/file/2026/04/13/7929217.pdf)、[社会学评论官方简介](https://src.ruc.edu.cn/CN/column/column1.shtml)、[社会官方英文页面](https://www.society.shu.edu.cn/EN/1004-8804/home.shtml)、[吉林大学人口学刊介绍](https://nasa.jlu.edu.cn/info/1086/2323.htm)、[人口研究官网](https://rkyj.ruc.edu.cn/CN/1000-6087/home.shtml)、[南京大学 CSSCI 中国人口科学记录](https://cssrac.nju.edu.cn/xscb/lyqk/20200524/i83614.html)、[中国社会科学 2025 年原版版权页（杭州师范大学存档）](https://www.hznu.edu.cn/upload/resources/file/2025/03/04/7871729.pdf)。

RSS 额外检查：

- 《社会》[官方 RSS 服务页](https://www.society.shu.edu.cn/CN/rss/showRssInfo.do) 公布的当期目录、最新录用、优先出版三个 feed 实测均返回 HTML 的“HTTP404 无法找到页面”，而不是 XML feed。HTTP 状态可能是 200，因此代码还检查 XML 根节点，不能把 HTML 错误页当成“没有新文章”。
- 《社会学评论》[官方 RSS 服务页](http://src.ruc.edu.cn/CN/rss/showRssInfo.do) 公布的三个 HTTP feed 实测为 502；HTTPS 证书校验失败。本项目不关闭证书验证、不自动降级到 HTTP。
- 《社会学研究》[官方主页](https://shxyj.ajcass.com/) 可读取，未确认可工作的 RSS 链接。
- 《人口学刊》：吉林大学[学术期刊导航](https://www.jlu.edu.cn/info/1123/1973.htm) 指向[社会科学研究院期刊介绍页](https://hssra.jlu.edu.cn/xsqk/rkxk.htm)，该页可读但无 RSS 链接；配置使用此主办单位页面，不猜测独立刊站域名。
- 《人口研究》[当前主页](https://rkyj.ruc.edu.cn/CN/1000-6087/home.shtml) 可读，展示 2026 年第 5 期，页面有 Email Alert，未发现 RSS 入口。
- 《中国人口科学》[刊站首页](https://zgrkkx.ajcass.com/) 直接 HTTPS 请求返回 200 且标题为刊名，未发现 RSS 链接；部分检索抓取入口会返回 403。
- 《中国社会科学》[杂志社中的中文刊页面](https://sscp.cssn.cn/kbw/zgshkx/) 可由网页检索服务读取，直接程序访问返回 403，未确认 RSS 入口。不能为此绕过访问控制。

因此，七本期刊可登记在配置中，但不应把现有元数据 API 或失效 feed 标记为已可靠启用。后续顺序为：确认可用的官方 RSS；若无 RSS，核实官方目录的使用条款并增加单刊适配；或由用户通过 Zotero Connector 合法保存后进入本地增量导入。人工获取和官方目录适配的状态须明确展示。

## 数据质量、增量和提醒

DOI 统一为小写裸 DOI，去除 `doi:` 或 DOI URL 前缀。跨源 DOI 相同的记录合并；没有 DOI 时只在“规范化标题＋年份＋第一作者”一致且无冲突时合并，不进行模糊标题去重。不同 DOI 永不因标题相似而自动合并。不能可靠匹配的记录保留，供后续复核。

本地 `metadata-cache.json` 维护历史去重状态；`digest.md` 提醒新增和更新，`records.json` 保存当次公开元数据报告。写文件使用原子替换，损坏的缓存不会被静默清空。失败来源不隐藏，报告标记不完整；不同来源的成功水位由上层 CLI 分别维护。GitHub Actions 临时运行环境不自动获得本地缓存，因此重叠窗口报告不等于跨月永久去重；本地运行发现时以本地缓存为准。MVP 尚无云端报告自动回传到本机的流程。

正文、摘要、PDF、附件路径、用户笔记均不进入上述公共报告。RSS/XML 禁用外部实体，下载体积有上限，RSS 只允许公开 HTTPS 地址并检查重定向目标。期刊或元数据服务给出的链接只是来源定位；是否允许获取全文，仍由原站授权和用户现有访问权限决定。Crossref 自身也提醒部分摘要可能受版权保护，因此本 MVP 不导出摘要。[Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)

## 已验证测试

离线测试覆盖 DOI 变体、不同 DOI 冲突、无 DOI 歧义、分页日期条件、分页上限、429 与长时间 `Retry-After`、部分来源失败、OpenAlex 请求头密钥和日志清洗、RSS/Atom 日期与链接、恶意 XML 实体、回环重定向、重复运行幂等、DOI 补全和损坏缓存保留。真实接口检查只证明上表所列当日覆盖状况，没有验证所有期刊或全部历史完整性。

## 2026-11-10 三刊复核与 0.3 接入通道

《社会学评论》官网 robots.txt 仍无法通过 TLS 证书校验；《人口学刊》CBPT 客户端页返回 500 JSON；中国社会科学网及 NCPSSD 的 robots.txt 返回 403；知网候选 RSS 返回 404。均未关闭校验、绕过访问限制或自动启用。现增加本机 RSS 配置：核对公开 HTTPS、XML 和频道标题，失败保持原配置；保存后由已有月度更新处理。没有可用来源时仍显示待接入。
