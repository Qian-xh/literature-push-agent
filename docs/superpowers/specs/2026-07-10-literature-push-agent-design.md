# 科研文献自动推送 Agent 设计规格

## 目标与边界

本项目在 GitHub Actions 上无人值守运行，按北京时间每天 09:00、14:30、19:30 分别执行早间、午后、晚间文献推送。系统从多个开放学术元数据源召回候选文献，按博士研究主题排序，经 OpenAI 完成最终选择与中文结构化总结，生成 HTML 邮件及 RIS、CSV、BibTeX 附件，并通过 Gmail SMTP SSL 发送。

系统只下载元数据源明确标记的合法开放获取 PDF，不绕过付费墙。单个数据源、OpenAI 或单篇 PDF 下载失败不得使整个候选收集或邮件导出流程崩溃；但缺少 Gmail 凭据时，正式发送流程必须清晰失败。

## 总体架构

采用单一 Python 3.12 CLI：`python -m src.main --slot morning|afternoon|evening`。三个时段共享抓取、去重、历史控制、AI 富化、导出和邮件组件，只通过时段策略改变检索时间窗和排序权重。

组件边界如下：

- `config.py`：读取和校验环境变量、研究主题、查询词、超时及附件限制。
- `models.py`：以 dataclass 建模候选文献、富化文献、历史记录和运行结果。
- `fetchers/`：Crossref、OpenAlex、Semantic Scholar 独立实现；统一返回候选文献列表，内部负责 timeout、重试、分页/限量和字段规范化。
- `dedup.py`：优先使用规范化 DOI，缺失 DOI 时使用规范化标题形成稳定唯一键，并合并多来源元数据。
- `ranking.py`：计算主题相关性、新颖性、引用影响、文献类型、历史惩罚和同日时段惩罚；产生供 AI 处理的有限候选集。
- `ai_enrichment.py`：请求 OpenAI 严格 JSON 输出，校验字段与枚举；解析或校验失败自动重试一次，仍失败时由本地规则生成完整结构。
- `exporters.py`：生成 HTML、RIS、UTF-8 BOM CSV、BibTeX，并可下载受大小限制的 OA PDF。
- `mailer.py`：使用 Gmail SMTP SSL 构建并发送多附件邮件。
- `main.py`：仅负责调用组件、运行事务顺序、日志、状态落盘及退出码。

## 数据召回与容错

Crossref 和 OpenAlex 为必接数据源，Semantic Scholar 为无需密钥时可用的增强源。各抓取器使用独立的 `requests.Session`、明确的 connect/read timeout、指数退避重试及状态码重试列表。主流程逐源捕获异常并记录日志，只要至少一个来源返回候选就继续运行；全部来源失败或无候选时返回明确非零退出码。

早间检索先覆盖近 45 天，候选不足时扩展到 90 天。午后和晚间不限年份，通过主题词组合召回。OpenAlex 提供引用数、文献类型和开放获取位置；Crossref 补充 DOI、期刊、作者和日期；Semantic Scholar 补充引用及 influential citation 指标。多源结果在去重阶段合并，非空且信息更丰富的字段优先。

## 排序与每次选择

正常每次选择 3 篇，候选不足时允许 2 篇。`MAX_PAPERS` 默认 5，作为环境可配置的最终硬上限；默认发送数量仍为 3。

- 早间：发布日期得分最高，近 45 天优先，其次为主题相关性；45 天内不足时使用 90 天候选。
- 午后：主题相关性、引用影响和机制关键词权重最高，不限制年份。
- 晚间：综述、方法、模型和潜在重要但较少被推荐的论文加权；对当天午后已推送文献施加强排除，对当日其他时段文献施加强惩罚。

本地排名先选出一个小型候选池交给 OpenAI。OpenAI 必须只从候选池选择，并输出规定字段；系统不接受模型虚构的新 DOI 或标题。

## 历史状态与重复控制

`data/history.json` 包含：

- `ever_recommended`：按唯一键保存首次/最近推荐时间和累计次数，永久保留。
- `deliveries`：保存日期、时段和文献键的细粒度记录，仅保留最近 30 天。

排序前执行规则：任意连续 7 天内同一文献达到 3 次即排除；同日已推送文献默认排除；从未推荐过的文献获得明显加分。只有邮件成功发送后才更新历史，以避免发送失败却记为已送达。状态文件使用临时文件替换方式原子写入；GitHub Actions 随后提交变化。

## OpenAI 输出和本地降级

每篇富化结果包含 `title`、`authors`、`year`、`journal`、`doi`、`url`、`summary_zh`、`why_read`、`dissertation_section`、`priority`、`keywords`、`endnote_group`。章节字段限制为用户指定的四个枚举值，优先级限制为 1–5 整数，关键词为非空中文字符串数组。

AI 返回值经过 JSON 提取、候选身份匹配和字段校验。第一次失败后附带校验错误重试一次；第二次失败则按关键词映射章节，以候选摘要生成简洁中文/可读的降级概述，并由本地相关性分数生成优先级和推荐理由。OpenAI 缺少密钥、额度不足、超时或模型不可用均进入相同降级路径，保证导出与邮件仍可继续。

## 邮件、附件与 OA PDF

邮件主题按时段生成，正文为内联样式 HTML 卡片，每篇论文展示完整规定字段、可点击 DOI/落地页、五星优先级和建议 EndNote 分组。

RIS 包含 TY、TI、AU、PY、JO、DO、UR、AB、KW、N1、ER；N1 汇总论文章节、优先级、EndNote 分组和推荐理由。CSV 使用 UTF-8 BOM，并固定用户要求的列顺序。BibTeX 默认生成并附加。

当 `DOWNLOAD_OA_PDF=true` 时，仅使用 OpenAlex `best_oa_location.pdf_url` 或其他明确 OA URL。下载使用 timeout、重试、内容类型检查和流式大小限制。超过单文件或邮件总附件阈值时不附加 PDF，只在正文保留 OA 链接；单篇下载失败只记录警告。

## GitHub Actions

`.github/workflows/literature.yml` 包含三条 UTC cron（`0 1 * * *`、`30 6 * * *`、`30 11 * * *`）及 `workflow_dispatch` 时段选项。计划任务根据当前 UTC 计划窗口映射时段，手动任务直接使用输入值。

作业设置 `permissions: contents: write` 和合理的 `timeout-minutes`，依次 checkout、setup-python 3.12、安装依赖、运行 pytest、运行 ruff、执行 Agent、始终上传输出和日志 artifact、成功后提交并推送 `data/history.json`。并发组按分支串行，避免三个任务同时修改历史。没有状态变化时提交步骤安全跳过。

Secrets 为 `OPENAI_API_KEY`、`GMAIL_ADDRESS`、`GMAIL_APP_PASSWORD`；Variables 为 `RECIPIENT_EMAIL`、`OPENAI_MODEL`、`MAX_PAPERS`、`DOWNLOAD_OA_PDF`。默认收件人为 `qxh.igsnrr@gmail.com`。

## 测试与验收

单元测试覆盖 DOI/标题去重、多源合并、7 天频率限制、三时段排序差异、RIS 字段、CSV BOM 与字段顺序、BibTeX 转义、AI 校验和降级、历史清理。外部 API、SMTP 和 OpenAI 通过依赖注入或请求 mock 隔离，不在单元测试中访问网络。

验收时运行完整 `pytest`、`ruff check .`、Python 编译检查和 GitHub Actions YAML 解析。提交并推送到 `main` 后，通过 GitHub CLI 手动触发一次 `morning`；若仓库尚未设置 Secrets，预期工作流在凭据预检处给出明确错误，日志和非邮件生成物仍作为 artifact 保留。

## 明确限制

- 学术 API 的召回与引用数依赖第三方覆盖范围和限流策略，不能保证穷尽所有文献。
- GitHub Actions cron 可能延迟数分钟。
- OpenAI 降级模式能维持流程，但中文总结质量低于模型正常可用时。
- Gmail 单封邮件大小受 Gmail 限制，因此 PDF 附件是尽力而为，RIS、CSV、BibTeX 始终优先。
