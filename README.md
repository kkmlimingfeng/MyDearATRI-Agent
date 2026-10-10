# MyDearATRI-Agent 全面改造优化，正在施工ing

一个面向陪伴与学习的大模型 Agent 项目。系统把 Agent 运行时、能力模块和工作流配置分开：日常对话使用当前 Agent 配置，工作流编辑器用于查看和调整底层数据流，也可以在编辑页试运行。

项目目前提供两种显示模式：`normal` 只显示最终回答和错误；`transparent` 显示可验证的模型请求、工具调用、结果和运行轨迹。模型推理文本不作为工具执行依据。

## 当前能力

- 通过 `config/modules.json` 动态创建提示词、LLM、工具、技能、记忆和 Reviewer 模块。
- 通过 `workflows/default_react.json` 配置 CLI 使用的 ReAct runtime 与模块绑定。
- 支持 OpenAI 兼容 API 和本地 GGUF（`llama-cpp-python`）模型。
- 工具调用使用结构化 Tool Call 协议；不支持原生工具调用的模型仍可使用旧式 ReAct 文本解析。
- 工具根据类型注解和文档生成 JSON Schema，并按风险级别要求批准高风险操作。
- 工作流页面从项目目录动态读取图文件和节点目录，可编辑、保存、启动或停止当前 Agent，并试运行和查看 trace。

当前图执行器将支持的数据流适配到 ReAct runtime。节点接口和扩展发现已经具备，但尚不是所有自定义节点都能独立执行；通用任意图执行器仍在后续开发中。

## 项目结构

```text
.
├── agent/                  # Agent runtime、工作流、节点接口和注册表
│   └── nodes/extensions/   # 可动态发现的 Python 节点扩展
├── bus/                    # 模块间事件总线
├── config/
│   ├── modules.json        # 模块实现与初始化配置
│   └── models.json         # CLI/Web 可选择的模型目录
├── docs/                   # 架构说明与扩展约定
├── modules/                # LLM、提示词、工具、技能、记忆等能力实现
├── web/                    # React + Vite 对话页和工作流编辑器
├── workflows/              # CLI v1 与网页 v2 工作流 JSON
├── myagent.py              # 命令行入口
├── web_server.py           # 本地 API 服务
└── requirements.txt        # Python 依赖
```

## 环境搭建

需要 Conda/Miniconda、Python 3.12 和 Node.js。Windows、Linux 和 WSL 均可运行基础功能。

```bash
conda create -n atri python=3.12 -y
conda activate atri
```

CPU 用户直接安装项目依赖：

```bash
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

GPU 用户需按 Python 版本、操作系统和 CUDA 构建选择 `llama-cpp-python` wheel。先安装匹配的 JamePeng CUDA wheel，再安装项目依赖；已安装版本满足 `requirements.txt` 时 pip 会保留该构建。CUDA 12.5 驱动可尝试 CUDA 12.4 构建的 wheel。发布页：[llama-cpp-python Releases](https://github.com/JamePeng/llama-cpp-python/releases)。

Linux/WSL 使用预编译 wheel 的示例：

```bash
python -m pip install ./WHEEL_FILE.whl
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

Windows PowerShell 使用匹配当前 Python 和 CUDA 构建的 wheel：

```powershell
python -m pip install .\path\to\WHEEL_FILE.whl
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

如需从源码编译 CUDA 后端，请先安装匹配的 CUDA Toolkit 和 C++ 构建工具，再设置 `CMAKE_ARGS`。Linux/WSL 示例：

```bash
export CMAKE_ARGS="-DGGML_CUDA=on"
export FORCE_CMAKE=1
python -m pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple "llama-cpp-python>=0.3.16"
```

Windows PowerShell 可在安装前设置：

```powershell
$env:CMAKE_ARGS = "-DGGML_CUDA=on"
$env:FORCE_CMAKE = "1"
python -m pip install --no-cache-dir "llama-cpp-python>=0.3.16"
```

CUDA wheel 和驱动的兼容性取决于具体构建。安装后可检查 Python 后端：

```bash
python -c "import llama_cpp; print(llama_cpp.__version__)"
```

## 配置模型

模型目录在 `config/models.json`。每个条目可以配置 OpenAI 兼容服务的 `base_url`、`model_name`，或本地 GGUF 后端的 `class`、`model_path` 和推理参数。远程模型通常还需要在 `config/.env` 中提供 `OPENAI_API_KEY`；该本地文件已被 Git 忽略，不要提交密钥。

GGUF 示例配置：

```json
{
  "local-qwen": {
    "class": "modules.llm.gguf_llm.GGUFLLM",
    "model_path": "${PROJECT_ROOT}/models/your-model.gguf",
    "n_ctx": 4096,
    "n_gpu_layers": -1
  }
}
```

将模型文件放在 `models/`，网页工作流会自动发现该目录下的 GGUF 文件并加入模型下拉框，权重文件不会提交到仓库。若模型含有单独的多模态投影文件（例如 `mmproj`），网页 GGUF 模型节点可在第二个下拉框选择；纯文本模型留空即可。当前后端需要安装带对应多模态 chat handler 的 `llama-cpp-python` 构建才能使用投影文件。`n_gpu_layers: -1` 表示尽可能将层卸载到 GPU，显存不足时可调低或设为 `0`。

仓库不包含模型权重。Qwen GGUF 可从模型发布页下载，例如 [Qwen3-1.7B Q4_K_M](https://huggingface.co/bartowski/Qwen_Qwen3-1.7B-GGUF)。请确认模型许可、文件名和后端兼容性后再使用。

## 命令行

在项目根目录运行：

```bash
python myagent.py
```

可用参数：

```text
--model KEY             使用 config/models.json 中指定的模型
--select-model          启动时交互选择模型
--list-models           列出模型配置
--mode normal           仅显示最终回答
--mode transparent      显示模型与工具运行轨迹
--workflow PATH         指定 CLI v1 工作流 JSON
--modules-config PATH   指定模块清单 JSON
--trace-jsonl PATH      将运行轨迹追加写入 JSONL
--disable-module ID     禁用模块，可重复使用
--enable-module ID      启用模块，可重复使用
```

其他内置开关可通过 `python myagent.py --help` 查看。CLI 默认加载 `workflows/default_react.json` 和 `config/modules.json`。

## Web 工作区

在两个终端分别启动后端和前端。两者均从项目根目录运行，前端命令进入 `web/`：

```bash
# 终端一：项目根目录，已激活 atri 环境
python web_server.py
```

```bash
# 终端二
cd web
npm install
npm run dev
```

浏览器打开 Vite 输出的地址，通常为 `http://localhost:5173`。前端开发服务器使用 5173，后端 API 默认使用 `127.0.0.1:8765`；模型由后端进程直接加载，不会单独启动模型端口。后端端口可通过 `ATRI_WEB_API_PORT` 设置。

日常对话页使用已启动的 Agent。工作流页可以载入和保存 `workflows/` 中的图工作流、选择模型、启动或停止 Agent，并进行单次试运行。保存工作流会写回项目文件，因此需要对工作区有写权限。

## 工作流与模块扩展

项目中的工作流是 JSON 配置，不是节点实现本身：

- `workflows/default_react.json` 使用 `workflow_version: 1`，供 CLI 选择 runtime 和模块绑定。
- `workflows/atri_companion_graph.json` 使用 `workflow_version: 2`，描述网页编辑器中的节点、端口、连线和布局。

模块是可替换的能力实现，继承 `BaseModule`，并在 `config/modules.json` 声明；新增模块后可在配置中绑定，而不需要把具体模块写进 Agent 主循环。模块构造函数遵循 `(module_id, bus, **kwargs)`，生命周期由 Agent 管理。模块配置中的 `{"$env": "NAME"}` 可读取环境变量，`{"$path": "relative/path"}` 可解析相对项目根目录的路径。

节点描述工作流数据流，继承 `BaseNode`，声明类型化输入/输出，并在 `agent/nodes/extensions/*.py` 中导出 `NODES = [MyNode]`。后端在节点目录请求和节点实例化时扫描扩展；新增或修改后刷新网页即可更新节点面板。接口示例和执行限制见 [节点扩展说明](agent/nodes/extensions/README.md)。

工具添加到 `modules/tools/system_tools/`，使用 `@system_tool` 注册；技能以 `SKILL.md` 放在 `modules/skills/` 下；人格与行为提示词在 `modules/prompt/SystemPrompt/` 中维护。架构和工具调用细节见 [架构说明](docs/architecture.md)。

## 安全与仓库内容

`.env`、`config/.env`、本地 GGUF 权重、前端依赖和构建产物已加入忽略规则。提交前请检查变更列表，避免提交密钥、个人数据或大型模型文件。
