# MyDearATRI-Agent

一个用于日常对话和学习 Agent 工作原理的模块化项目。对话页负责使用当前 Agent；工作流页用于编辑它的数据流，也可以直接试运行工作流。两种页面共用同一套工作流配置。

项目仍在开发中。当前的可视化执行器支持内置的 ReAct 工作流和部分简单数据流；自定义节点可以被发现并显示在编辑器中，但并非都能直接参与执行。

## 功能

- 普通模式显示回答，透明模式展示可观察的执行步骤、模型交互和工具结果。
- 在工作流页面编辑、保存和同时打开多个 JSON 工作流；同一时间只运行其中一个。
- 支持 OpenAI 兼容 API 模型，以及通过 `llama-cpp-python` 加载本地 GGUF 模型。
- 提示词、记忆、技能、工具和模型按模块组织，可通过配置更换实现。
- 可从扩展目录发现新节点；界面支持主题配色和自定义背景。

透明模式展示的是系统实际取得的输入、输出和运行事件，不代表能读取模型内部未输出的推理过程。

## 安装

需要 Python 3.12、Node.js 18+ 和 npm。推荐使用 Conda 创建独立环境：

```bash
conda create -n atri python=3.12 -y
conda activate atri
python -m pip install -r requirements.txt
cd web
npm install
cd ..
```

在国内安装 Python 依赖时，可以给 `pip install` 加上 `-i https://pypi.tuna.tsinghua.edu.cn/simple`。

`requirements.txt` 包含 `llama-cpp-python`。如需 GPU 加速，请先根据系统、Python 版本和 CUDA 环境安装匹配的预编译 wheel，再安装其余依赖。可参考 [llama-cpp-python CUDA 构建发布页](https://github.com/JamePeng/llama-cpp-python/releases)。CPU 或 API 模型不需要 CUDA 构建。

## 启动 Web 界面

Linux/WSL 可在项目根目录运行：

```bash
./start.sh
```

脚本会启动前后端，并在退出时一起停止。它会尝试结束占用 `8765` 和 `5173` 端口的进程；如果这些端口用于其他服务，请改用下面的手动启动方式。

Windows PowerShell、Linux 和 WSL 也可以在两个终端分别运行：

```bash
python web_server.py
```

```bash
cd web
npm run dev
```

打开 `http://localhost:5173`。后端 API 默认监听 `127.0.0.1:8765`；本地模型由后端进程加载，无需单独启动模型服务。

## 接入模型

**本地 GGUF：**将模型文件放入项目根目录的 `models/`。刷新工作流页面后，在 GGUF 模型节点的下拉框中选择文件。多模态模型如果需要单独的 `mmproj`，可在第二个下拉框选择；纯文本模型留空。`models/` 下的 GGUF 文件已被 Git 忽略。

**OpenAI 兼容 API：**在 API 模型节点选择模型，并填写服务端点和 API Key。如果模型不在下拉框，先在 `config/models.json` 增加包含 `base_url` 和 `model_name` 的条目，再刷新页面。密钥保存在本机后端，不写入工作流 JSON；请勿把密钥提交到仓库。

命令行使用的模型可以在 `config/models.json` 中配置。例如：

```json
{
  "local-model": {
    "class": "modules.llm.gguf_llm.GGUFLLM",
    "model_path": "${PROJECT_ROOT}/models/model.gguf",
    "n_ctx": 4096,
    "n_gpu_layers": 0
  }
}
```

使用 GPU 构建时，可将 `n_gpu_layers` 调高；`-1` 表示尽可能将模型层卸载到 GPU。API 模型所需的 `OPENAI_API_KEY` 也可以写入本地的 `config/.env`。该文件已被 Git 忽略。

## 命令行

在项目根目录运行：

```bash
python myagent.py --list-models
python myagent.py --select-model --mode transparent
```

不指定工作流时，CLI 使用 `workflows/default_react.json`。通过 `--workflow PATH`、`--model KEY` 和 `--modules-config PATH` 可更换工作流、模型与模块配置。完整参数见 `python myagent.py --help`。

## 工作流与扩展

网页工作流保存在 `workflows/`，刷新页面会重新读取目录中的文件。工作流 JSON 描述节点、连线和配置；节点实现与模块实现分别放在 `agent/nodes/` 和 `modules/`。工作流页面可以打开多个编辑标签，但同一时间只能启动一个工作流。

新增 Python 节点的接口与示例见 [节点扩展说明](agent/nodes/extensions/README.md)，运行时、模块和工具调用的设计见 [架构说明](docs/architecture.md)。目前编辑器能动态发现扩展节点，通用的任意图执行仍未完成；编写扩展时应先确认目标工作流是否受当前执行器支持。
