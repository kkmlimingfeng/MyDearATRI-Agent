# MyDearATRI-Agent

2026年6月26日 亚托莉Agent开发启动

一个基于模块化总线架构的个人AI助理/陪伴系统，支持 ReAct 推理循环、工具调用、技能编排、长期记忆和事后审查。

---

## 项目结构

```text
MyDearATRI-Agent/
├── myagent.py              # 项目启动入口，负责模块初始化、注册、命令行交互
├── README.md               # 项目说明文档
├── config/
│   └── .env                # 环境变量配置（API Key、沙箱路径等）
├── bus/
│   ├── base.py             # 总线消息类型与消息结构定义
│   ├── event_bus.py        # 事件总线实现，模块间通过 request/response 通信
│   └── __init__.py
├── agent/
│   ├── base_agent.py       # Agent 基类：模块注册、生命周期管理、颜色输出
│   ├── react_agent.py      # ReAct Agent：Thought-Action-Observation 循环实现
│   └── __init__.py
├── modules/
│   ├── base.py             # 模块基类
│   ├── llm/
│   │   ├── base_llm.py     # LLM 模块基类
│   │   ├── modelscope_llm.py   # 本地模型加载（ModelScope / Transformers）
│   │   ├── openai_llm.py   # OpenAI 兼容接口调用
│   │   └── __init__.py
│   ├── prompt/
│   │   ├── prompt_manager.py   # 系统提示词管理器
│   │   └── SystemPrompt/   # 系统提示词文件目录
│   │       ├── AGENT.md    # Agent 运行规则、输出格式、工具/技能占位符
│   │       ├── SOUL.md     # 角色人格、语气、价值观（待填写）
│   │       ├── USER.md     # 用户画像（待填写）
│   │       ├── HEARTBEAT.md# 定时任务相关（预留）
│   │       └── reviewer.md # Reviewer 模块的后台审查提示词
│   ├── tools/
│   │   ├── base_tool.py    # 工具基类，提供 @system_tool 装饰器、自动扫描、工具配置
│   │   ├── tool_module.py  # 工具模块，通过总线接收调用请求
│   │   └── system_tools/   # 具体工具实现目录
│   │       ├── weather.py      # 查询天气
│   │       ├── get_attraction.py   # 根据天气推荐景点
│   │       └── exec_sandbox_cmd.py # 沙箱命令执行
│   ├── skills/
│   │   ├── base_skill.py   # 技能基类，自动扫描 SKILL.md、技能开关
│   │   ├── skill_module.py # 技能模块，通过总线提供技能目录和详情
│   │   ├── recommend_travel/   # 旅游推荐技能
│   │   │   └── SKILL.md
│   │   └── file_operations/    # 文件操作技能
│   │       └── SKILL.md
│   ├── mem/
│   │   ├── base_mem.py     # 记忆模块基类（预留）
│   │   ├── memory_module.py# 长期记忆模块，读取 memory.md
│   │   └── memory.md       # 长期记忆存储文件
│   ├── reviewer/
│   │   ├── reviewer_module.py  # Reviewer 模块，后台总结并维护记忆/画像
│   │   └── __init__.py
│   ├── mcp/                # MCP 模块预留目录
│   └── rag/                # RAG 模块预留目录
├── Qwen/                   # 本地模型目录（Qwen3-0.6B）
├── 开发日志/
│   ├── 20260626.md         # 项目启动日志
│   ├── 20260629.md         # 模块化、ReAct、Reviewer 流程记录
│   └── 近期计划.md         # 后续开发计划
└── 8_Agent.ipynb           # 参考学习笔记
```

## 核心模块职责

| 模块 | 职责 |
|---|---|
| `bus` | 模块间通信总线，支持同步 request/response |
| `agent` | 负责 ReAct 循环、调用各模块、维护对话历史 |
| `llm` | 加载并调用大语言模型 |
| `prompt` | 管理系统提示词，支持 AGENT/SOUL/USER 自动拼接 |
| `tools` | 注册、管理、执行工具函数，支持细粒度开关 |
| `skills` | 管理 SKILL.md 技能目录，提供技能简介和详情 |
| `mem` | 长期记忆读取与注入 |
| `reviewer` | 后台审查对话，自动更新 memory.md 和 USER.md |

## 快速启动

```bash
python myagent.py
```

常用参数：

```bash
python myagent.py --disable-tools      # 禁用工具模块
python myagent.py --disable-skills     # 禁用技能模块
python myagent.py --disable-memory     # 禁用记忆模块
python myagent.py --disable-reviewer   # 禁用 Reviewer 模块
```

## 扩展方式

- **添加新工具**：在 `modules/tools/system_tools/` 下新建 `.py` 文件，使用 `@system_tool` 装饰器。
- **添加新技能**：在 `modules/skills/` 下新建文件夹，放入 `SKILL.md`（支持 YAML frontmatter）。
- **编辑人格/用户画像**：修改 `modules/prompt/SystemPrompt/SOUL.md` 和 `USER.md`。