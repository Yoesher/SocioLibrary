# 社会科学研究工作台

SocioLibrary 面向不同社会科学研究传统，连接本地文献、研究问题和可回查的证据。产品名称保持 **SocioLibrary**。

## 从研究领域出发

检索页提供社会科学通用、教育研究、经济与劳动、政治与公共管理、心理与行为、社会学与人口、新闻与传播、人文地理与区域、历史与历史社会科学、人类学与文化、法学与社会法共 11 个视角。

选择视角后，本机保存相应的研究示例和阅读提示。视角不会过滤其他学科的文献，不改变附件许可、全文语义试点、模型、AI 密钥或期刊订阅。跨学科问题可使用“社会科学通用”；也可以在任何视角下检索全部已导入文献。

离线中英术语扩展覆盖这些方向的常用概念和方法，例如教育公平、政策执行、自我效能、媒介素养、空间正义、档案研究、参与观察、法律意识，以及双重差分、过程追踪、混合方法等。它是有限词表，不是任意句子的翻译。已经建立的多语言语义索引继续沿用，无需为切换视角重建。

## 围绕证据开展研究

检索页的“从问题到证据：研究路线”把材料筛选、片段阅读、比较与积累连接起来。按钮只准备任务和问题，不自动调用 AI。

| 任务 | 处理方式 |
| --- | --- |
| 方法与论证审读 | 识别研究类型，梳理材料、概念或测量、设计、论证和结论之间的关系，指出尚待补读之处 |
| 梳理证据与分歧 | 按概念或命题组织所选材料的证据、主张、分歧和适用范围，标注来源 |
| 文献综述提纲 | 按问题与分歧组织提纲，每节列出已选依据和待补读材料 |

仍需先在检索结果中选择 1–8 个片段，再核对完整提示、接收地址、模型和发送范围，确认后发送。切换研究视角会使旧预览失效；服务端也会在发送前再次检查。答复是待核对草稿，不能把选中的少数片段当作领域全貌。

阅读与六维比较兼容定量、质性、混合、历史、规范和理论研究。比较表保留原有六个内部字段及既有内容，界面将其表述为“问题与命题、概念与理论、材料与对象、方法与论证、发现与主张、局限与适用范围”。没有提供样本或统计结果时，不强行填入；历史材料需区分事件时间、材料形成时间和作者解释；相关关系不能直接改写成因果关系。

## 添加自己学科的期刊

每个专门视角提供一本期刊作为配置起点，不代表选刊排名，也不会自动订阅。点击“准备订阅”只预填刊名、Crossref 接入方式和 ISSN；核对后由使用者点击“验证并保存”，再检查更新。

下列 ISSN 于 2026-11-13 用 Crossref 期刊接口核对，接口均返回对应刊名。这只验证期刊身份，不代表完整过刊、每月收录及时性或全文可用性。

| 研究方向 | 期刊与 Crossref 身份记录 | ISSN |
| --- | --- | --- |
| 教育 | [Review of Educational Research](https://api.crossref.org/journals/0034-6543) | 0034-6543 |
| 经济与劳动 | [American Economic Review](https://api.crossref.org/journals/0002-8282) | 0002-8282 |
| 政治与公共管理 | [Journal of Public Administration Research and Theory](https://api.crossref.org/journals/1053-1858) | 1053-1858 |
| 心理与行为 | [Psychological Science](https://api.crossref.org/journals/0956-7976) | 0956-7976 |
| 社会学与人口 | [American Sociological Review](https://api.crossref.org/journals/0003-1224) | 0003-1224 |
| 新闻与传播 | [Journal of Communication](https://api.crossref.org/journals/0021-9916) | 0021-9916 |
| 人文地理 | [Progress in Human Geography](https://api.crossref.org/journals/0309-1325) | 0309-1325 |
| 历史 | [History and Theory](https://api.crossref.org/journals/0018-2656) | 0018-2656 |
| 人类学 | [American Anthropologist](https://api.crossref.org/journals/0002-7294) | 0002-7294 |
| 社会法 | [Law & Society Review](https://api.crossref.org/journals/0023-9216) | 0023-9216 |

也可以自行添加任何其他有可靠来源的期刊。已有中文试点与待接入来源保持原状。详见[期刊配置](v0.11-graph-and-journals.md)。

## 可公开展示的演示资料

开发者可运行下面的命令，在**新的空目录**生成十份原创合成文档、二十页 PDF 与相应索引。程序拒绝覆盖非空目录。这些材料全部标明“演示、非真实论文”，没有实证研究结果，不包含私人文献或 API 密钥。

```powershell
python scripts/create_social_science_demo.py --directory ./demo-social-science
python -m sociolit.desktop --data-dir ./demo-social-science
```

正式研究请使用有权读取和处理的材料。演示库只是功能检查夹具，不能用于证明真实科研效果。
