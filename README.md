# MyDearATRI-Agent

一个用于日常对话和学习 Agent 工作原理的模块化项目。对话页负责使用当前 Agent；工作流页用于编辑它的数据流，也可以直接试运行工作流。两种页面共用同一套工作流配置。

项目仍在开发中。工作流由通用节点及其连线决定执行顺序，默认陪伴工作流用一个模型节点、响应解析、能力分发和反馈边组成 ReAct 循环。

---

![](docs/chat1.png)

---

![](docs/workflow1.png)

---

## 功能

- 普通模式显示回答，透明模式展示可观察的执行步骤、模型交互和工具结果。
- 对话输入区显示最近一次模型请求的输入 token 用量和上下文上限；支持的模型可切换思考档位，不支持时会明确显示。
- 工作流接入 Qwen3-TTS 后可随回复流式播放语音；新语音开始时会打断正在播放的音频，回复下方的喇叭按钮可重新播放。
- 对话支持图片、视频抽帧和常见文档附件；图片与视频理解需要工作流连接支持视觉输入的模型。
- 普通对话自动保存为逐条记录，默认每 8 轮更新一次会话摘要；间隔可在记忆设置中调整，也可手动更新。试运行内容不保存。
- 工作流节点可单独切换跳过状态；跳过的节点不会执行，主流程的输入、模型对话和回复节点不能跳过。
- 沙箱支持选择工作空间、预设或自定义文件权限，并可单独控制是否允许命令及 MCP 工具执行。
- 在工作流页面编辑、保存和同时打开多个 JSON 工作流；同一时间只运行其中一个。
- 支持 OpenAI 兼容 API 模型，以及通过 `llama-cpp-python` 加载本地 GGUF 模型。
- 提示词、记忆、技能、工具和模型按模块组织，可通过配置更换实现。
- 支持导入标准 Agent Skills ZIP，以及 Claude JSON / Codex TOML 格式的 MCP 服务配置。
- 可从扩展目录发现新节点；界面支持主题配色和自定义背景。
- 试运行时显示实际执行的节点、输出预览与完成耗时；循环节点可以多次执行同一个模型节点。
- 工作流画布支持双击添加节点、调整节点尺寸、切换连线样式，以及按内容自适应节点大小。
- 首次进入和刷新页面时显示 ATRI 粒子动画；对话页与工作流页之间也有过渡动画。

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

本地 stdio MCP 服务和 `exec_sandbox_cmd` 使用项目代码沙箱。模型调用命令或 MCP 工具默认关闭；需要时在输入框的沙箱设置或工具配置页显式开启。开启后仍受选定的文件权限限制。在 Linux/WSL 中安装 Firejail，并在工具配置页检查 Landlock 支持：

```bash
sudo apt install firejail -y
```

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

首次使用网页内的 Live2D 形象时，在 `web/` 目录运行 `npm run download:cubism-core` 获取 Live2D Cubism Core Web 运行库。运行库保存在 Git 忽略的 `web/public/vendor/`。桌宠素材按人物放在 `data/pets/<人物名>/`：Live2D 模型放在 `live2d/` 子目录，静态图片放在人物目录根部，支持 PNG、JPG、JPEG、GIF 和 WebP；点击音效放在人物目录下的 `click/`。TTS 参考音频单独放在 `data/voice/<音色名>/`。启动后会自动读取可用的 Live2D 模型和根目录图片。静态图片保留文件原有透明度或背景，也能拖动、弹跳、播放点击音效并显示语音气泡。人物设置菜单可切换桌宠；对话页和工作流页分别记住位置。点击音效和 TTS 参考音频都会动态读取。

### 导入 Live2D 桌宠

可以从 [Eikanya/Live2d-model](https://github.com/Eikanya/Live2d-model/) 下载单个模型目录，并在“桌宠设置”中直接选择或拖入该目录；不需要手动改名为 `live2d`。目录根部需包含 `.model3.json`，或包含一层 `live2d/` 子目录并在其中放置 `.model3.json`；同时保留配置引用的 `.moc3`、贴图及其他资源。应用会将模型文件放入 `data/pets/<人物名>/live2d/`。不要把整个模型仓库作为一个桌宠导入，应下载并导入其中的单个模型目录。

本项目通过 Cubism 4 Web Core 加载 Cubism 3/4 的 `.model3.json` 模型。上游仓库是模型收集项目，其说明不保证每个模型的配置都正确；旧版 Cubism 2 `.model.json` 模型，以及配置损坏或缺少依赖资源的模型，不能保证直接加载。导入后可在桌宠设置右侧预览中确认模型是否正常显示。

## 接入模型

**本地 GGUF：** 将模型文件放入项目根目录的 `models/`。刷新工作流页面后，在 GGUF 模型节点的下拉框中选择文件。多模态模型如果需要单独的 `mmproj`，可在第二个下拉框选择；纯文本模型留空。`models/` 下的 GGUF 文件已被 Git 忽略。

**OpenAI 兼容 API：** 在 API 模型节点点击“配置模型”，从左侧选择已有配置，或添加自定义模型。填写提供商模型 ID、API 根地址（例如 `https://api.openai.com/v1`）、API Key，并选择 Chat Completions 或 Responses 格式。保存后即可在节点下拉框选择模型。自定义配置保存在本机的 `config/api_models.json`，密钥单独保存在 `config/model_credentials.json`；两者均被 Git 忽略。已有 `config/models.json` 条目仍可作为内置预设。

模型配置分别记录最大输入 token（模型能力参考）和最大输出 token（可选的生成上限）。输出上限默认留空，API 请求不指定上限，由提供商和模型决定；手动填写后才发送限制。已有配置中的数值会继续生效，需要自动模式时可清空后保存。实际送入模型的历史消息仍由工作流的上下文策略决定，输入上限不会自动截断历史。密钥可在配置页单独清除；若设置了 `OPENAI_API_KEY`，清除本机保存的密钥后仍会使用该环境变量。图片输入标记用于记录模型能力，当前对话输入仍为文本。

API 模型的思考强度可在“模型对话”节点属性中设置工作流默认值，也可在对话输入区临时选择。选择“跟随工作流”使用节点默认值。ModelScope Qwen 只在手动设置最大输出 token 时按所选强度分配思考预算；输出上限为自动时使用提供商默认预算。其他提供商的“自动”不会发送思考强度参数，手动选择的档位取决于提供商和模型支持情况。GGUF 模型不提供此设置。

对话输入区的上下文读数显示最近一次模型请求的输入 token 用量和当前模型配置的上下文上限；具体用量取决于模型返回的统计信息。思考档位只在当前模型支持时启用。

**本地语音输出：** 在工作流中将“Qwen3-TTS 音频模型”节点接到“回复输出”的语音输入，即可在回复生成期间合成并播放语音；完整音频保留在浏览器中供重新播放。模型文件、服务配置和 HTTP API 见 [Qwen3-TTS 说明](docs/tts.md)。

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

不指定工作流时，CLI 使用 `workflows/atri_companion_graph.json`。通过 `--workflow PATH`、`--model KEY` 可更换工作流和模型。CLI 与网页共用 workflow v2 图执行器。完整参数见 `python myagent.py --help`。

## 工作流与扩展

网页工作流保存在 `workflows/`，刷新页面会重新读取目录中的文件。工作流 JSON 描述节点、连线和配置；节点实现与模块实现分别放在 `agent/nodes/` 和 `modules/`。工作流页面可以打开多个编辑标签，但同一时间只能启动一个工作流。

在画布空白处双击可搜索并添加节点。编辑后点击顶部的“保存”将 JSON 写入 `workflows/`；“试运行”用于检查数据在节点间的传递，确认后可点击“启动”让对话页使用当前工作流。节点的输出预览和透明模式的执行轨迹可帮助查看每一步的结果。

新增 Python 节点的接口与示例见 [节点扩展说明](agent/nodes/extensions/README.md)，运行时、模块和工具调用的设计见 [架构说明](docs/architecture.md)。节点返回的输出端口决定数据走向；分支可以只输出一侧，带反馈标记的连线会在下一轮送回数据。

### Skills 与 MCP

在工作流的“技能目录”节点中打开详细配置，可以导入包含 `SKILL.md` 的 ZIP 包。技能安装到 `modules/skills/<技能名>/`，包内 `references/` 等文本资源可由模型按需读取。导入器会拒绝路径穿越、符号链接和超限压缩包。

在“MCP 服务”节点的详细配置中，可粘贴或选择 Claude `mcpServers` JSON、Codex `mcp_servers` TOML，也可手动添加本地 stdio 或远程 Streamable HTTP 服务。默认工作流已接入 MCP 节点；添加或修改服务后会重载 MCP 进程。stdio 命令按工具页配置的沙箱工作空间和权限启动，npm、uv、pip 缓存默认写入工作空间；MCP 配置保存在被 Git 忽略的 `config/mcp_servers.json`，环境变量和请求头密钥不会通过管理 API 返回。

安装第三方能力时，将 Skill 包原样放入 `modules/skills/<技能名>/`；项目会保留 Skill 的 `allowed-tools` 声明，并兼容标准 `Bash(command)` 调用，将一般命令映射到 `exec_sandbox_cmd`，`bb-browser` 命令则转发到专用的 `bb_browser` 工具。命令和 MCP 调用默认拒绝，显式开启后由工作空间及文件权限约束。CLI 依赖使用固定版本安装到工作空间缓存，例如 npm 包可运行 `npm install --global --prefix .cache/tools <包>@<版本>`；沙箱会把 `.cache/tools/bin` 加入 PATH。npm、uv、pip 缓存放在工作空间的 `.cache/`，不会加入 Git。Skill 是模型使用工具的说明，不会自行创建可调用工具。真正实现 MCP 协议的服务，则通过“MCP 服务”节点导入配置并启用，stdio 进程遵守项目沙箱权限。

#### 网页联网与浏览器操作（bb-browser）

项目保留 [bb-browser](https://github.com/epiral/bb-browser) 的 Skill 说明，并实现了项目内的 `bb_browser(command, timeout)` 工具适配层。它在沙箱中调用固定版本的 CLI，支持 `site`、`fetch`、标签页、页面交互、网络调试和 trace 等命令；命令以参数数组执行，不经过 shell。`Bash(bb-browser:*)` 会自动路由到该工具。

首次使用时，在项目根目录安装 CLI：

```bash
node --version  # 需要 Node.js 18 或更高版本
npm install --global --prefix .cache/tools bb-browser@0.14.2
```

Linux/WSL 中还需要按上文安装 Firejail。浏览器工具不会安装或启动 Chrome；需要先启动一个从项目运行环境可访问、启用了远程调试的 Chrome/Chromium 浏览器。默认连接 `http://127.0.0.1:9222`；使用其他地址时，可在环境变量或被 Git 忽略的 `config/.env` 中设置 `BB_BROWSER_CDP_URL`。工具会复用健康的 bb-browser daemon，否则在沙箱内启动 daemon 并连接该 CDP 地址。

`site <名称>` 依赖站点适配器。运行 `bb-browser site list` 查看已安装项，运行 `bb-browser site search <关键词>` 搜索适配器；缺少适配器时可运行 `bb-browser site update` 更新社区适配器，或使用 `bb-browser open <网址>` 和 `snap` 直接浏览网页。工具调用还需要在输入框的沙箱设置中开启“允许命令和 MCP 工具执行”，文件操作仍受工作空间权限约束。

项目没有额外安装 BeautifulSoup 等 HTML 解析依赖。`requests` 和 `tavily-python` 已列在 `requirements.txt`；旧的 `get_attraction` 工具使用 Tavily 搜索景点，需在 `config/.env` 设置 `TAVILY_API_KEY` 才能调用。Tavily 是可选 API 能力，与 `bb-browser` 的安装及浏览器连接相互独立。

#### 会话记忆存储

普通对话原文和会话摘要保存在被 Git 忽略的 `data/memory/`：原文按 JSONL 逐条写入 `conversations/`，摘要和文件路径记录在 `index.json`。默认每 8 个已完成轮次生成或更新摘要；新建对话时也会整理待更新的旧会话。该摘要存储目前独立于长期记忆文件 `modules/mem/memory.md`，不会自动写入该文件；工作流的长期记忆节点读取的是 `memory.md`。

## 素材来源

- `data/voice/atri/` 中的语音包和 `data/pets/atri/click/` 中的点击音效来源：[语音包来源](https://re.xcdream.com/article/430.html)。
- `data/pets/atri/live2d/` 中的 Live2D 模型来源：[Bilibili 专栏](https://www.bilibili.com/opus/777050104809914386)。
