# MyDearATRI-Agent 全面改造优化，正在施工ing

2026年6月26日 亚托莉Agent开发启动

一个基于模块化总线架构的个人AI助理/陪伴系统，支持 ReAct 推理循环、工具调用、技能编排、长期记忆和事后审查。

---

## 项目结构

```text
MyDearATRI-Agent/
├── myagent.py              # 项目启动入口，负责模块初始化、注册、命令行交互
├── README.md               # 项目说明文档
├── config/
│   ├── modules.json        # 可插拔模块清单
│   └── .env                # 环境变量配置（API Key、沙箱路径等）
├── workflows/
│   ├── default_react.json  # CLI Runtime 与模块绑定
│   └── atri_companion_graph.json  # 网页默认图工作流
├── bus/
│   ├── base.py             # 总线消息类型与消息结构定义
│   ├── event_bus.py        # 事件总线实现，模块间通过 request/response 通信
│   └── __init__.py
├── agent/
│   ├── base_agent.py       # Agent 基类：模块注册、生命周期管理、颜色输出
│   ├── react_agent.py      # ReAct Agent：Thought-Action-Observation 循环实现
│   └── __init__.py
├── modules/
│   ├── module_loader.py    # 根据配置动态加载模块
│   ├── base.py             # 模块基类
│   ├── llm/
│   │   ├── base_llm.py     # LLM 模块基类
│   │   ├── modelscope_llm.py   # 本地模型加载（ModelScope / Transformers）
│   │   ├── openai_llm.py   # OpenAI 兼容接口调用
│   │   ├── gguf_llm.py     # GGUF 本地模型（llama.cpp，可选依赖）
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
python myagent.py --enable-reviewer    # 启用 Reviewer 模块
python myagent.py --disable-module xxx # 按 ID 禁用任意模块
python myagent.py --mode transparent   # 展示模型调用、工具参数、结果和运行轨迹
```

默认 `normal` 模式隐藏对话中间过程，只显示最终回答和错误；`transparent` 模式逐步显示 LLM 输入输出、工具调用参数和结果。两种模式共用同一运行流程。

## 可插拔模块

`config/modules.json` 声明可用模块实现；`workflows/*.json` 保存 CLI Runtime 配置和网页 workflow v2 图文件。网页启动或刷新时会从该目录动态读取图工作流，保存按钮也会直接写回目录。节点面板从后端 `/api/nodes` registry 动态加载；`agent/nodes/extensions/*.py` 中的节点扩展在 API 请求和工作流运行时扫描，新增或修改扩展后刷新网页即可更新节点目录，不需要重启后端。扩展节点实现 `BaseNode` 并导出 `NODES = [MyNode]`，示例见 `agent/nodes/extensions/README.md`。插件类继承 `BaseModule`，构造函数遵循 `(module_id, bus, **kwargs)`；模块生命周期和总线注册由 Agent 自动处理。工具、技能等目录扫描通过 `setup` 配置完成。

添加模块时，在 `modules/` 新增实现并在 `config/modules.json` 添加一项；组合新 Agent 时复制并编辑 workflow JSON 即可，不需要修改 CLI 主循环。模块参数支持从环境变量读取（`{"$env": "NAME"}`）和相对项目根目录的路径（`{"$path": "relative/path"}`）。通过 `--modules-config` 和 `--workflow` 可以指定其他清单与工作流。工作流版本 1 将 ReAct 循环作为 Runtime，JSON 负责选择运行时和模块绑定；网页编辑器可以复用相同格式。

当前 LLM 和工具之间使用统一结构化协议：工具函数的类型注解和 docstring 会生成 JSON Schema，支持工具调用的后端返回原生 Tool Call，运行时执行后按 `role=tool` 消息返回结果；不支持原生调用的模型仍兼容原有 ReAct 文本格式。设计约定和后续路线见 [docs/architecture.md](docs/architecture.md)。

工具调用由独立的 `ToolExecutor` 处理，工具函数可使用 `@system_tool(risk="network", timeout=20, retries=1)` 声明执行元数据。参数会在调用前按函数签名校验。`read/network` 工具直接执行，`write/execute` 工具需要用户批准；超时会停止等待并报告错误，但 Python 无法安全终止已运行的函数，因此超时后不会自动重试。运行轨迹在普通模式也会保存在内存中；可用 `--trace-jsonl runs/trace.jsonl` 追加写入 JSONL，透明模式会在终端显示轨迹。

## Web 工作区

Web 工作区分为日常对话页和工作流编辑页。对话页使用当前启动的工作流；编辑页可以配置模块连接、保存/导出 workflow v2 JSON、启动或停止 Agent，并通过当前 ReAct runtime 试运行和查看 trace。节点接口已准备好，但通用任意图执行器仍在后续路线中。

分别打开两个终端并激活 `atri` 环境。第一个终端启动 API：

```bash
python web_server.py
```

第二个终端启动前端：

```bash
cd web
npm install
npm run dev
```

打开 Vite 显示的本地地址，通常为 `http://localhost:5173`。本地 API 默认监听 `127.0.0.1:8765`，这两个端口分别用于网页和本地 API，不是模型服务端口。GGUF 模型由 API 进程直接在本机加载，不会额外监听模型端口。工作流页的“启动”会初始化当前选择的模型，“停止”会关闭 Agent 并释放模型；“试运行”可单独执行一次工作流。

## GGUF 模型

GGUF 后端通过 `llama-cpp-python` 加载本地模型。项目内置 `qwen3-1.7b-q4km` 配置，模型文件放在 `models/Qwen3-1.7B-Q4_K_M.gguf`，约 1.2 GB。模型下载地址：

`https://huggingface.co/bartowski/Qwen_Qwen3-1.7B-GGUF/resolve/main/Qwen_Qwen3-1.7B-Q4_K_M.gguf?download=true`

下载完成后运行 `python myagent.py --model qwen3-1.7b-q4km`。当前配置使用 `n_gpu_layers: -1` 将模型层全部 offload 到 GPU；显存不足时可在 `config/models.json` 调小该值，设为 `0` 则使用 CPU。

当前验证文件大小为 `1,282,439,584` bytes，SHA-256 为 `72c5c3cb38fa32d5256e2fe30d03e7a64c6c79e668ad84057e3bd66e250b24fb`。模型文件被 `.gitignore` 忽略，不会提交到仓库。

Linux/WSL 可续传下载：

```bash
mkdir -p models
curl -L --retry 5 -C - "https://hf-mirror.com/bartowski/Qwen_Qwen3-1.7B-GGUF/resolve/main/Qwen_Qwen3-1.7B-Q4_K_M.gguf" -o models/Qwen3-1.7B-Q4_K_M.gguf
```

Windows PowerShell 使用 `curl.exe` 执行相同下载命令；如果镜像不可用，将域名替换为 `huggingface.co` 并添加 `?download=true`。下载中断后重复执行即可续传。

## 环境搭建

需要 Conda/Miniconda 和 Python 3.12。Windows PowerShell 与 Linux/WSL 都先创建并进入环境：

```bash
conda create -n atri python=3.12 -y
conda activate atri
```

### Linux / WSL

GPU 用户先从 [JamePeng llama-cpp-python Releases](https://github.com/JamePeng/llama-cpp-python/releases) 下载匹配 Python 和平台的 CUDA wheel。CUDA 12.5 驱动可使用 `cu124` wheel；本项目的 `requirements.txt` 会安装该 wheel 需要的 CUDA 12.4 用户态运行库：

```bash
python -m pip install ./llama_cpp_python-0.4.2+cu124-cp312-cp312-linux_x86_64.whl
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

CPU 用户可以直接安装 `requirements.txt`，`llama-cpp-python` 会从源码编译。若要使用系统 CUDA 12.5 Toolkit 本机构建 GPU 后端：

```bash
export CMAKE_ARGS="-DGGML_CUDA=on"
export FORCE_CMAKE=1
python -m pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple "llama-cpp-python>=0.3.16"
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

如果使用 JamePeng 的 Linux `cu124` wheel，还需要 CUDA 12.4 用户态运行库；`requirements.txt` 已按 Linux 平台声明，会安装 `cudart`、`cublas` 和 `nccl` 运行库。GGUF 模块启动时会在导入 llama.cpp 后端前加载这些运行库。

若 WSL 中代理监听在 Windows 主机而不是 WSL 自身的 `127.0.0.1`，将代理地址改为 WSL 可访问的 Windows 主机地址并带端口 `7897`，再执行 pip 下载。

### Windows

先从 [JamePeng llama-cpp-python Releases](https://github.com/JamePeng/llama-cpp-python/releases) 下载匹配当前 Python 版本和平台的 wheel。发布页目前提供 CUDA 12.4、12.6、12.8、13.0 和 13.1 构建，没有 CUDA 12.5 专用 wheel；CUDA 12.5 用户应选择与驱动兼容的 12.4 wheel，或按上面的 CMake 方法本机构建。文件名需匹配 `cp312`、`win_amd64` 及 CUDA 标记。安装 wheel 后再安装项目依赖：

```powershell
$wheel = Get-ChildItem .\path\to\llama_cpp_python-*.whl | Select-Object -First 1
python -m pip install $wheel.FullName
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

如清华镜像没有相应版本，可以在 pip 命令加 `--extra-index-url https://pypi.org/simple`，并确保 `HTTPS_PROXY` 指向可用代理。安装后可用 `python -c "import llama_cpp; print(llama_cpp.__version__)"` 检查，再按上面的命令启动 CLI。

本项目已在 Linux/WSL、Python 3.12、RTX 3060、CUDA 驱动 12.5 环境用 `llama-cpp-python 0.4.2+cu124` 完成 GPU 推理验证；CUDA 12.4 wheel 可由 CUDA 12.5 驱动向后兼容运行。

## 扩展方式

- **添加新工具**：在 `modules/tools/system_tools/` 下新建 `.py` 文件，使用 `@system_tool` 装饰器。
- **添加新技能**：在 `modules/skills/` 下新建文件夹，放入 `SKILL.md`（支持 YAML frontmatter）。
- **编辑人格/用户画像**：修改 `modules/prompt/SystemPrompt/SOUL.md` 和 `USER.md`。
