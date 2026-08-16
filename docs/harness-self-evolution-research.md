# Harness 自进化机制调研

## 1. 调研范围

本次直接阅读了本机源码中的以下材料：

- `L:\WORKSPACE\deepseek-harness\docs\architecture.md`
- `L:\WORKSPACE\deepseek-harness\packages\extensions\README.md`
- `L:\WORKSPACE\deepseek-harness\packages\extensions\tool-cordis\README.md`
- `L:\WORKSPACE\deepseek-harness\packages\extensions\cordis-host-runner\README.md`
- `L:\WORKSPACE\deepseek-harness\packages\extensions\cordis-client-runner\README.md`
- `L:\WORKSPACE\deepseek-harness\.agents\notes\implemented\feature\2026-07-08-self-referential-cordis-toolset.md`
- `L:\WORKSPACE\hermes-agent\AGENTS.md`
- `L:\WORKSPACE\hermes-agent\agent\curator.py`
- `L:\WORKSPACE\hermes-agent\agent\curator_backup.py`
- `L:\WORKSPACE\hermes-agent\agent\background_review.py`
- `L:\WORKSPACE\hermes-agent\tools\skill_manager_tool.py`
- `L:\WORKSPACE\hermes-agent\tools\skill_usage.py`
- `L:\WORKSPACE\hermes-agent\hermes_cli\plugins.py`
- `L:\WORKSPACE\hermes-agent\website\docs\user-guide\features\curator.md`
- `L:\WORKSPACE\prime-agent\README.md`
- `L:\WORKSPACE\prime-agent\packages\coding-agent\docs\rlm.md`
- `L:\WORKSPACE\prime-agent\packages\coding-agent\docs\rlm-runtime.md`
- `L:\WORKSPACE\prime-agent\packages\coding-agent\docs\skills.md`
- `L:\WORKSPACE\prime-agent\packages\coding-agent\src\core\refinement\refinement.ts`
- `L:\WORKSPACE\prime-agent\prime-agent-runtime\src\rlm\harness.py`

结论针对当前本地源码快照，不代表未来上游版本永久不变。

## 2. DeepSeek Harness：插件化的运行时自修改

### 2.1 基础结构

DeepSeek Harness 建立在 Cordis 插件、服务和事件模型上。工具、运行器和 UI 扩展都通过普通插件的 `provide`、`inject` 和生命周期挂载，核心没有为动态扩展维护另一套特殊依赖体系。

其自引用工具集当前提供五个主要动作：

- `cordis_inspect`：查看可用 API、服务和事件；
- `cordis_define`：定义动态包并进行语法检查；
- `cordis_run`：启动动态包；
- `cordis_stop`：停止并释放动态包；
- `cordis_undefine`：移除定义。

动态包可包含 host half 与 browser half。Host half 在 `node:vm` 中执行，通过白名单 Context façade 使用 Harness 服务；Browser half 发送到客户端并由 UI 侧批准和运行。插件停止时由 Cordis fiber 统一释放工具、监听器、服务和定时器。

### 2.2 它实现了什么意义上的“进化”

它将控制层的新行为表示为插件/动态包，而不是直接散改主循环：Agent 可先反射当前 API，再生成插件，实时挂载工具、事件处理或 UI 扩展，然后停止并替换。这非常适合：

- 快速验证新的工具组合；
- 运行时诊断与临时修复；
- 用同一插件协议扩展宿主和浏览器；
- 通过生命周期撤销实验。

因此“所有控制层进化转换为插件进化”基本准确，但需要加上两个限定：它首先是运行时实验机制；持久化和生产发布不是自动完成的。

### 2.3 关键边界

- 动态包只保存在进程内存中，不写项目文件或配置，重启后不保留。
- 当前没有自动把成功实验提升为正式插件的流水线。持久化仍需生成普通项目插件，接受版本控制、测试和安装。
- `node:vm` 明确不是安全边界。Context 中暴露的文件、网络、bash 等能力会触达真实运行时，信任级别接近 shell。
- 动态包按 session 管理，但运行于共享进程，副作用可能影响其他 session。
- 源码会留在工具调用历史中，工具 schema 变化也会进入请求日志；这属于可追踪性，不等于耐久发布记录。

所以它适合作为 `self_modifying_bot` 的候选实验层，但不能直接作为面向公众号公网用户的自修改入口。

## 3. Hermes Agent：受治理的技能库演化

### 3.1 插件不是主要自动进化对象

Hermes 同样有成熟插件系统：发现 bundled、`~/.hermes/plugins`、项目 `.hermes/plugins` 和 Python entry point `hermes_agent.plugins`；插件通过 `register(ctx)` 注册工具和生命周期。用户插件可覆盖同名来源，但覆盖内建工具需要显式 opt-in。

不过 Hermes 的自动自改进重点不是自主改写插件或核心，而是 Skills：把成功步骤、纠错、偏好和故障处理沉淀为程序性记忆。前台 Agent 可通过 `skill_manage` 创建、patch、edit 和写支持文件；背景 review 从近期会话中提炼或修补技能。

### 3.2 Background Review 与 Curator

Background Review 是短周期学习环：它在独立 Agent fork 中复盘对话，优先修补已加载的技能、已有 umbrella，或添加 `references/`、`templates/`、`scripts/`；没有合适技能时才创建新的类别级技能。

Curator 是长期维护环：

- 由“间隔已到且用户空闲”触发，不是独立 cron daemon；
- 使用辅助模型和独立 prompt cache，不污染活跃对话；
- 根据 view/use/patch 统计执行 `active → stale → archived`；
- 默认 30 天 stale、90 天 archive，LLM 合并功能默认关闭；
- 永不自动硬删除，只移动到可恢复 archive；
- pinned 技能和被 cron 引用的技能受保护；
- Hub、外部和用户拥有的技能默认不允许后台修改；
- 只有明确的策略来源标记或人工 `adopt` 才把技能交给 Curator 管理。

特别值得采用的是：`created_by` 在实现中被当作“允许自治维护”的策略标记，而不是靠统计猜测作者。Hermes 明确拒绝根据使用/修改次数自动推断所有权。

### 3.3 审批、审计与恢复

`skill_manage` 具有写入审批门，可先暂存待审变更；写入成功后才更新统计和同步。Curator 每次真实变更前可将技能树快照为 tar.gz，保留有限数量；回滚前还会再做一次快照，使回滚本身也可逆。每次运行生成机器可读 `run.json` 和人类可读 `REPORT.md`。

这是一套比“模型可以写文件”更完整的自治治理模型：所有权、可修改范围、空闲调度、辅助模型隔离、成本开关、报告、固定、归档和回滚形成闭环。

### 3.4 关键边界

- Hermes 的自主学习主要改变程序性知识，不是任意改写 Agent 核心。
- 前台用户要求创建的技能属于用户，默认不交给后台 Curator。
- Bundled、Hub、external、pinned 和 protected built-ins 有不同保护规则。
- 技能可以改变未来行为，仍需防范恶意内容和过宽工具权限；来源治理不能替代执行沙箱。

## 4. Prime Agent：Continual Harness 的小步精炼

### 4.1 进化对象

Prime Agent 的 RLM 运行时以持久 IPython 作为模型的程序化工作台。文件、shell、Python Skill 和递归子 Agent 都从这个工作台调用；TypeScript Host 继续掌握会话、Provider、凭据、调度和安全策略。

其自进化核心是 `rlm.harness` 和 `/refine`。Continual Harness 保存四种补充状态：

- `prompt`：对基础系统提示的补充说明；
- `memory`：事实、偏好和任务状态；
- `skill`：已有 Python 调用的可复用描述、引用和参数契约；
- `subagent`：可复用的子 Agent 任务规格。

基础系统 Prompt 保持不可变。进化只对补充状态做小范围 create/update/delete，避免每次学习都重写整个 Agent 身份。

### 4.2 Refine 闭环

显式 `/refine` 或 auto-refine review 会读取当前轨迹、Harness 状态和历史，先生成纯 JSON proposal，再应用修改。计划和应用分离；应用前可重新读取状态并检测并发变化，避免模型规划期间覆盖其他写入。

状态分为 session-local 与 global：局部状态位于 session artifact 的 `harness/harness_state.json`，适合当前任务进度、临时阻塞和协调；全局状态位于 `~/.prime/agent/harness/`，只应用于稳定的跨会话经验、用户偏好、可复用 Skill/Subagent 或明确限定项目的事实。默认优先局部精炼。

每次精炼记录触发条件、证据、修改、预期结果及 before/after snapshot；可按 refinement id 生成逆向 proposal 回滚。Auto-refine 可按轮次间隔或压缩事件触发，先由独立 review 判断 `shouldRefine`，没有证据时允许不修改。

### 4.3 持久执行与能力边界

持久 IPython 的变量、导入、函数和任务句柄可跨工具调用和压缩存活；Daemon、session artifacts、kernel snapshot 和子 Agent registry 支持终端断开后的恢复。Python-backed Skill 是真实可执行包，而 Continual Harness 中的 skill entry 只是对已安装 Python 调用的持久描述，`/refine` 不会代替 Skill 的打包、安装和代码审查。

IPython 使用 worker 的操作系统权限，不是安全沙箱。它增强了工作连续性和组合能力，但不提供权限隔离；不可信代码仍需外部沙箱。

### 4.4 Prime Agent 的特点

Prime Agent 位于 DeepSeek Harness 与 Hermes 之间：

- 比 Hermes 的 Skill Curator 更贴近当前轨迹，可以同时改 prompt、memory、skill description 和 subagent spec；
- 比 DeepSeek 的动态插件更保守，不把 `/refine` 当作任意代码热加载；
- 通过 local/global scope 防止临时经验污染所有会话；
- 通过持久 REPL 和子 Agent 规格，把“如何思考和分工”也纳入演化对象；
- 有细粒度 snapshot 和 refinement rollback，但对候选修改是否真正提升长期指标仍需要外部评测层。

## 5. 对比

| 维度 | DeepSeek Harness | Hermes Agent | Prime Agent |
|---|---|---|---|
| 主要演化单元 | Cordis 动态插件/包 | Skill 程序性记忆 | Prompt、Memory、Skill 描述、Subagent 规格 |
| 典型时机 | 会话内即时定义和运行 | 会话后 review、空闲期 curator | 显式 `/refine`、轮次或压缩后的 auto-refine |
| 能力范围 | 工具、服务、事件、UI，接近控制层 | 流程、知识、偏好和操作经验 | 当前轨迹策略、事实、调用契约和分工方式 |
| 持久性 | 动态包默认仅进程内 | 用户目录中的技能可持久化 | Session-local 与显式 global Harness ledger |
| 隔离 | `node:vm`，非安全边界 | 辅助 Agent/prompt cache 隔离；工具执行仍需策略 | Host/Kernel 分层，但 IPython 不是安全沙箱 |
| 生命周期 | Cordis fiber 可停止和释放 | active/stale/archive、pin/restore | 版本、refinement history、before/after rollback |
| 治理 | 反射、schema 日志、显式运行/停止 | 来源策略、审批、统计、报告、快照回滚 | 最小修改、证据、local/global scope、冲突检查 |
| 正式发布 | 需另行提升为普通插件 | Skill 写入即持久，但受所有权规则约束 | Harness 条目可持久；可执行 Skill 仍需打包审查 |

三者不是替代关系。DeepSeek Harness 擅长结构能力的动态实验，Hermes 擅长行为知识的长期整理与安全维护，Prime Agent 擅长把当前轨迹小步精炼为有作用域、可回滚的补充 Harness 状态，并以持久 REPL 保持复杂工作的连续性。

## 6. 对 self_modifying_bot 的落地建议

采用混合架构：

1. **插件层借鉴 DeepSeek Harness。** Channel、Runtime Adapter、Tool Provider、Policy 扩展和 Eval 都是有清单、有生命周期的插件。临时动态插件只在隔离候选环境运行。
2. **Skill 层借鉴 Hermes。** 记录来源、所有权、使用/查看/修补计数、状态、pin 和引用关系；后台维护只接触明确授权给它的技能。
3. **正式提升由 Bot 自己补齐。** 动态实验通过评测后，生成普通插件包，固定依赖和版本，经过测试、审批、不可变发布和回滚，不能只留在内存。
4. **核心进化不与插件热加载混为一谈。** 核心修改在独立工作树/容器中完成；生产进程只切换已经验证的 release 指针。
5. **权限来自主体与环境，不来自模型。** 微信用户、管理员、后台 curator 和发布器分别使用不同身份与策略；候选环境不注入生产密钥。
6. **保留 Harness 原生性。** Hermes、DeepSeek Harness 和 Prime Agent 以外部进程/公开插件/API 接入，不直接修改其源码。Bot 持有规范会话和工具协议，因此切换 Harness 不会绑定某个实现。
7. **采用 Prime 的局部/全局精炼。** 默认把新经验写入 session-local candidate；只有稳定、重复、通过跨会话评测的条目才能提升为用户、项目或全局范围。
8. **采用 Prime 的计划/应用分离。** Learning Extractor 只生成结构化 proposal，发布器在重新读取当前版本、检查冲突和权限后原子应用。
9. **采用 Prime 的分工演化。** 除记忆和 Skill 外，将经过验证的子 Agent 角色、输入输出契约、模型选择和终止条件保存为可复用 Agent Spec。

第一阶段应优先实现规范 Session Store、Runtime Adapter、Tool Broker 与 `NoExec`/受限本地环境；第二阶段增加 Skill 治理；第三阶段再开放动态插件实验和自动候选发布。这样可以先得到稳定机器人，再逐步扩大自治范围。
