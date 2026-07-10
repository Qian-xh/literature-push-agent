# 科研文献自动推送 Agent

面向博士课题“横断山不同植被带根土复合体对壤中流演化过程的调控机制”的无人值守文献发现、筛选、中文总结与 Gmail 推送系统。项目运行于 GitHub Actions，每天按北京时间推送三次，并为每次邮件生成可导入 EndNote 的 RIS、Excel 友好的 CSV 和 BibTeX 附件。

## 系统功能

- 同时检索 Crossref 和 OpenAlex，并以 Semantic Scholar 作为可降级增强源。
- DOI 优先去重；DOI 缺失时使用规范化标题作为唯一键。
- 早间侧重新文献，午后侧重经典/高被引机制论文，晚间侧重综述、方法和模型论文。
- 使用 OpenAI 严格 JSON 结构化输出完成最终筛选和中文总结；解析失败自动重试一次，再失败使用本地规则降级。
- 长期记录曾推荐文献，执行“连续 7 天最多 3 次”、同日排重和未推荐优先策略。
- 发送清晰的 HTML 邮件，并附带 RIS、UTF-8 BOM CSV、BibTeX。
- 可选下载 OpenAlex/Semantic Scholar 明确标记的开放获取 PDF；不绕过付费墙，单篇失败不影响邮件。
- 每次运行将导出物和日志上传为 GitHub Actions artifact，并在发送成功后自动提交 `data/history.json`。

## 架构

```text
GitHub Actions / 手动触发
        │
        ▼
Crossref + OpenAlex + Semantic Scholar
        │ 独立超时、重试、失败隔离
        ▼
DOI/标题去重 → 时段排名 → 历史频控
        │
        ▼
OpenAI 严格 JSON（失败则本地降级）
        │
        ├─ HTML 邮件
        ├─ RIS / CSV / BibTeX
        └─ 合法 OA PDF（可选、受大小限制）
        │
        ▼
Gmail SMTP SSL → 成功后更新 history.json
```

主要模块：

- `src/fetchers/`：学术元数据源和统一重试会话。
- `src/dedup.py`：DOI/标题身份与多源字段合并。
- `src/ranking.py`：三个时段的确定性初排。
- `src/ai_enrichment.py`：OpenAI 选择、严格校验、一次重试和本地降级。
- `src/exporters.py`：HTML、RIS、CSV、BibTeX、OA PDF。
- `src/mailer.py`：Gmail SMTP SSL 与 MIME 附件。
- `src/history.py`：频率控制、30 天清理和原子状态写入。
- `src/main.py`：CLI 编排和事务顺序。

## 定时规则

| 时段 | 北京时间 | UTC cron | 选择重点 |
|---|---:|---:|---|
| morning | 09:00 | `0 1 * * *` | 近 30–45 天优先，不足时扩展到 90 天 |
| afternoon | 14:30 | `30 6 * * *` | 高相关、经典、高被引、关键机制，不限年份 |
| evening | 19:30 | `30 11 * * *` | 与午后尽量不同的综述、方法、模型及易忽视论文 |

GitHub Actions 的 cron 可能延迟几分钟，这是平台的正常行为。工作流根据触发它的 cron 表达式判断时段，不依赖实际启动分钟数。

## 部署步骤

1. 打开仓库的 **Settings → Secrets and variables → Actions**。
2. 在 **Secrets** 中创建下列三个仓库 Secret：

   | Secret | 是否需要 | 内容 |
   |---|---|---|
   | `OPENAI_API_KEY` | 建议配置 | OpenAI API Key；缺失或额度异常时自动使用本地降级总结 |
   | `GMAIL_ADDRESS` | 必需 | 发件 Gmail 地址 |
   | `GMAIL_APP_PASSWORD` | 必需 | Gmail 16 位应用专用密码，不是登录密码 |

3. 在 **Variables** 中创建或确认：

   | Variable | 推荐值 | 说明 |
   |---|---|---|
   | `RECIPIENT_EMAIL` | `qxh.igsnrr@gmail.com` | 收件地址；未设置时也使用此默认值 |
   | `OPENAI_MODEL` | `gpt-4.1-mini` | 支持结构化输出的低成本模型 |
   | `MAX_PAPERS` | `5` | 安全硬上限；正常每次仍发送 3 篇，候选不足时发送 2 篇 |
   | `DOWNLOAD_OA_PDF` | `false` | 设为 `true` 才尝试附加合法 OA PDF |

4. 打开 **Settings → Actions → General → Workflow permissions**。推荐选择 **Read and write permissions**。工作流本身已声明 `permissions: contents: write`，组织策略仍可能覆盖它。
5. 打开 **Actions → Literature Push Agent → Run workflow**，选择 `morning` 做首次手动测试。

### Gmail 应用专用密码

1. 为 Google 账号启用两步验证。
2. 在 Google 账号安全设置中搜索“应用专用密码（App passwords）”。
3. 创建一个用于 GitHub Actions 的密码。
4. 将生成的 16 位密码保存为 `GMAIL_APP_PASSWORD`。复制时可以带空格，程序会移除空格；不要保存普通 Gmail 登录密码。

如果账号由单位 Google Workspace 管理且看不到应用专用密码，需要管理员允许该功能，或改用允许 SMTP 应用密码的独立 Gmail 账号。

### OpenAI API Key

在 OpenAI API 平台创建 API Key，并保存为 `OPENAI_API_KEY`。Key 仅通过 GitHub Secret 注入，不会写入仓库、日志或附件。`OPENAI_MODEL` 默认使用 `gpt-4.1-mini`；如账号不可用该模型，可将 Variable 改为账号支持且具备结构化输出能力的模型。

## 手动运行

GitHub 网页：

1. 进入 **Actions**。
2. 选择 **Literature Push Agent**。
3. 点击 **Run workflow**。
4. 选择 `morning`、`afternoon` 或 `evening`。

GitHub CLI：

```bash
gh workflow run literature.yml --ref main -f slot=morning
gh run list --workflow literature.yml --limit 1
```

本地运行（PowerShell）：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:OPENAI_API_KEY = "sk-..."
$env:GMAIL_ADDRESS = "your-address@gmail.com"
$env:GMAIL_APP_PASSWORD = "your-app-password"
$env:RECIPIENT_EMAIL = "qxh.igsnrr@gmail.com"
python -m src.main --slot morning
```

正式运行会发送邮件。未配置 Gmail Secrets 时，系统仍会先生成可诊断的导出物和 `output/agent.log`，随后以清晰的缺失凭据错误退出，不会写入“已发送”历史。

## 本地测试与静态检查

需要 Python 3.12：

```bash
python -m pip install -r requirements.txt
python -m pytest -v
python -m ruff check .
python -m compileall -q src tests
```

测试通过假的 HTTP/OpenAI/SMTP 对象执行，不会访问学术 API、消耗 OpenAI 配额或发送邮件。

## 邮件与附件

每篇邮件正文包括题名、作者/年份、期刊、DOI、链接、中文概述、推荐理由、对应论文章节、五星优先级、中文关键词和 EndNote 分组。

RIS 包含 `TY`、`TI`、`AU`、`PY`、`JO`、`DO`、`UR`、`AB`、`KW`、`N1`、`ER`。`N1` 写入论文章节、优先级、EndNote 分组及推荐理由。CSV 使用 UTF-8 BOM，Windows Excel 可直接识别中文。

当 `DOWNLOAD_OA_PDF=true` 时，程序只使用元数据源明确给出的 OA PDF URL，并检查 HTTP 内容类型、PDF 文件签名、单文件上限和邮件总附件上限。过大或失败的 PDF 不附加，但正文保留可用链接。

## 重复控制和状态

- 唯一键优先使用规范化 DOI；无 DOI 时使用规范化标题。
- 同一文献在任意连续 7 天最多推送 3 次。
- 同日已经推送的文献不再进入其他时段。
- 未推荐文献获得排序加分，重复文献受到惩罚。
- `deliveries` 仅保留最近 30 天，`ever_recommended` 长期保留。
- 只有 Gmail 成功发送后才更新 `data/history.json`。

## 常见错误排查

### Gmail SMTP 认证失败

- 确认使用应用专用密码，不是 Gmail 登录密码。
- 确认 Google 账号已启用两步验证。
- 删除 Secret 中多余换行；普通空格会由程序自动去除。
- 检查 `GMAIL_ADDRESS` 是否就是创建该应用密码的账号。
- Workspace 账号若禁用应用密码，请联系管理员或更换发件账号。

典型日志包含 `SMTPAuthenticationError`、`Username and Password not accepted`。修改 Secret 后重新手动触发，无需提交代码。

### GitHub Actions 无写权限

若发送成功但 `data/history.json` 推送失败并出现 HTTP 403：

1. 检查 **Settings → Actions → General → Workflow permissions**。
2. 允许 **Read and write permissions**。
3. 检查组织级策略是否禁止 `GITHUB_TOKEN` 写入。
4. 确认默认分支保护没有禁止 GitHub Actions bot 直接推送；必要时为该工作流配置允许规则。

### OpenAI 配额、余额或模型错误

日志会记录一次失败、自动重试一次，然后使用本地规则生成完整字段并继续发送。检查 API 账户余额、项目预算、Key 所属项目和 `OPENAI_MODEL`。本地降级摘要用于保障流程连续性，质量低于模型正常运行时，应以原文为准。

### Crossref/OpenAlex 限流

所有请求均设置 connect/read timeout，并对 429、500、502、503、504 使用指数退避重试。单源失败时其他来源继续工作。若持续限流：

- 等待后手动重试；
- 避免连续多次手动触发；
- 确保 `GMAIL_ADDRESS` 已配置，使 Crossref/OpenAlex 请求带有礼貌池联系信息；
- 查看 `output/agent.log` 判断是某一来源失败还是全部来源无结果。

### 没有收到邮件

- 查看 Actions 运行结论和 `output/agent.log` artifact。
- 检查收件箱垃圾邮件、分类和 Gmail 发件箱。
- 确认 `RECIPIENT_EMAIL` 拼写正确。
- 若日志显示“少于 2 篇合格论文”，说明去重/7 天频控后不足，系统按要求不会发送单篇邮件。

## 已知限制

- 第三方学术 API 的覆盖范围、引用数和文献类型并不完全一致，系统无法保证穷尽所有相关论文。
- GitHub Actions 定时任务可能延迟数分钟。
- Semantic Scholar 公共 API 可能限流；它是增强源，Crossref 与 OpenAlex 仍会继续。
- OpenAI 本地降级摘要依据题名和公开元数据生成，不能替代阅读全文。
- Gmail 对单封邮件附件大小有平台限制；RIS/CSV/BibTeX 优先，PDF 为尽力附加。
- 系统只自动下载明确合法的开放获取 PDF，不尝试规避登录、订阅或付费墙。
