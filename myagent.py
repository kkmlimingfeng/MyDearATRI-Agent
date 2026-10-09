"""
MyDearATRI-Agent 启动脚本
模块化Agent架构演示
"""
import sys
import os
import argparse
import json

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _load_env_file(env_path: str) -> None:
    """
    手动解析 .env 文件并将其中的非空键值导出为环境变量。

    不依赖 python-dotenv，避免引入额外依赖。
    """
    if not os.path.isfile(env_path):
        return

    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # 跳过空行和注释行
            if not line or line.startswith('#'):
                continue
            # 只处理第一个等号
            if '=' not in line:
                continue
            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip()
            # 去除两端引号
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            # 仅当环境变量尚未设置且值非空时才写入
            if key and value and key not in os.environ:
                os.environ[key] = value


def _load_models_config(config_path: str) -> dict:
    """
    加载预定义模型配置。

    :param config_path: models.json 文件路径
    :return: 模型名称到配置的字典
    """
    if not os.path.isfile(config_path):
        return {}

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        if not isinstance(config, dict):
            print(f"[警告] {config_path} 格式错误，应为字典")
            return {}
        return config
    except Exception as e:
        print(f"[警告] 加载模型配置 {config_path} 失败: {e}")
        return {}


def _select_model_config(models: dict, model_key: str) -> dict:
    """
    根据用户选择的 key 返回模型配置。

    :param models: 模型配置字典
    :param model_key: 用户指定的模型 key
    :return: 包含 base_url、model_name 的字典
    """
    if model_key:
        if model_key not in models:
            available = ", ".join(models.keys())
            raise ValueError(f"未知模型 '{model_key}'。可用模型: {available}")
        return models[model_key]

    # 未指定时优先使用环境变量，否则使用第一个模型
    return {
        "base_url": os.environ.get("OPENAI_BASE_URL", ""),
        "model_name": os.environ.get("OPENAI_MODEL_NAME", ""),
    }


def _model_summary(config: dict) -> str:
    """Format both remote model endpoints and local model files for the CLI."""
    if config.get("model_path"):
        return f"GGUF: {config['model_path']}"
    return f"{config.get('model_name', '')} @ {config.get('base_url', '')}"


def _select_model_numbered(models: dict) -> str:
    """没有 readchar 时的回退：数字编号选择模型"""
    keys = list(models.keys())
    print("\n请选择模型：")
    for i, key in enumerate(keys, 1):
        cfg = models[key]
        print(f"  {i}. {key}: {_model_summary(cfg)}")

    while True:
        choice = input("请输入编号: ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(keys):
                return keys[idx]
        except ValueError:
            pass
        print("无效选择，请重新输入")


def _select_model_interactive(models: dict) -> str:
    """
    交互式选择模型，支持 ↑↓ 方向键。

    如果未安装 readchar，自动回退到数字编号选择。
    """
    try:
        import readchar
    except ImportError:
        return _select_model_numbered(models)

    keys = list(models.keys())
    if not keys:
        raise ValueError("没有可用的模型")
    if len(keys) == 1:
        return keys[0]

    selected = 0
    prompt_lines = len(keys) + 1

    def render():
        print("\n请选择模型（↑↓ 移动，Enter 确认）：")
        for i, key in enumerate(keys):
            cfg = models[key]
            prefix = "-> " if i == selected else "   "
            print(f"{prefix}{key}: {_model_summary(cfg)}")

    def clear():
        # 光标上移并清除下方内容
        print(f"\033[{prompt_lines}A\033[J", end="", flush=True)

    render()
    while True:
        char = readchar.readchar()
        if char == readchar.key.UP:
            selected = (selected - 1) % len(keys)
            clear()
            render()
        elif char == readchar.key.DOWN:
            selected = (selected + 1) % len(keys)
            clear()
            render()
        elif char in ("\n", "\r"):
            clear()
            print(f"已选择模型: {keys[selected]}\n")
            return keys[selected]


def _approve_tool_call(call, metadata: dict) -> bool:
    """Ask for explicit approval before write/execute tools run."""
    risk = metadata.get("risk", "unknown")
    print(f"\n工具 {call.name} 请求执行高风险操作 (risk={risk})")
    print(json.dumps(call.arguments, ensure_ascii=False, indent=2, default=str))
    return input("批准本次调用？[y/N]: ").strip().lower() in {"y", "yes"}


# 加载 config/.env 中的环境变量
_env_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "config",
    ".env"
)
_load_env_file(_env_path)


from agent.workflow import WorkflowConfigError, load_workflow
from modules.module_loader import ModuleConfigError, build_modules, load_module_specs
from agent.trace import CompositeTraceSink, JsonlTraceSink


def main():
    """主函数：创建并运行Agent"""

    # 模块开关：通过命令行参数控制各模块是否启用
    parser = argparse.ArgumentParser(description="MyDearATRI-Agent 启动脚本")
    parser.add_argument("--disable-prompt", action="store_true", help="禁用提示词模块")
    parser.add_argument("--disable-llm", action="store_true", help="禁用LLM模块")
    parser.add_argument("--disable-tools", action="store_true", help="禁用工具模块")
    parser.add_argument("--disable-skills", action="store_true", help="禁用技能模块")
    parser.add_argument("--disable-memory", action="store_true", help="禁用记忆模块")
    parser.add_argument("--enable-reviewer", action="store_true", help="启用Reviewer模块")
    parser.add_argument("--disable-reviewer", action="store_true", help="禁用Reviewer模块")
    parser.add_argument(
        "--disable-module", action="append", default=[], metavar="ID",
        help="按模块 ID 禁用模块，可重复使用"
    )
    parser.add_argument(
        "--enable-module", action="append", default=[], metavar="ID",
        help="按模块 ID 启用模块，可重复使用"
    )
    parser.add_argument(
        "--modules-config", default="",
        help="模块配置文件路径，默认使用 config/modules.json"
    )
    parser.add_argument(
        "--workflow", default="",
        help="工作流 JSON 路径，默认使用 workflows/default_react.json"
    )
    parser.add_argument("--model", "-m", type=str, default="", help="选择预定义模型（在 config/models.json 中配置）")
    parser.add_argument("--select-model", action="store_true", help="启动时交互式选择模型（支持 ↑↓ 方向键）")
    parser.add_argument("--list-models", action="store_true", help="列出 config/models.json 中可用的模型并退出")
    parser.add_argument(
        "--mode", choices=("normal", "transparent"), default="normal",
        help="对话显示模式：normal 隐藏中间过程，transparent 显示执行轨迹"
    )
    parser.add_argument(
        "--trace-jsonl", default="",
        help="将运行轨迹追加保存为 JSONL 文件"
    )
    args = parser.parse_args()

    enable_llm = not args.disable_llm

    # 配置文件路径
    project_root = os.path.dirname(os.path.abspath(__file__))
    config_dir = os.path.join(project_root, "config")
    modules_config_path = args.modules_config or os.path.join(config_dir, "modules.json")
    workflow_path = args.workflow or os.path.join(project_root, "workflows", "default_react.json")
    models_config_path = os.path.join(config_dir, "models.json")

    try:
        workflow = load_workflow(workflow_path)
        agent = workflow.runtime_class(**workflow.runtime_kwargs)
    except (WorkflowConfigError, ModuleConfigError, TypeError) as e:
        parser.error(f"加载工作流失败: {e}")

    if args.trace_jsonl:
        sink = JsonlTraceSink(os.path.abspath(args.trace_jsonl))
        existing_sink = getattr(agent, "trace_sink", None)
        sinks = [existing_sink] if existing_sink is not None else []
        sinks.append(sink)
        agent.trace_sink = CompositeTraceSink(sinks)
    agent.tool_approval_callback = _approve_tool_call

    # 加载预定义模型配置
    models_config = _load_models_config(models_config_path)

    # 如果用户要求列出模型，打印后退出
    if args.list_models:
        print("\n可用模型列表（config/models.json）：")
        if not models_config:
            print("  （暂无预定义模型）")
        for key, cfg in models_config.items():
            print(f"  - {key}: {_model_summary(cfg)}")
        print()
        return

    # 2. 读取模块配置，并选择 LLM 模型配置
    try:
        module_specs = load_module_specs(modules_config_path)
    except ModuleConfigError as e:
        parser.error(str(e))

    if enable_llm:
        # 如果要求交互式选择，或者没有通过 --model 指定且 models.json 里有多个模型
        if args.select_model or (not args.model and len(models_config) > 1):
            selected_key = _select_model_interactive(models_config)
            model_cfg = models_config[selected_key]
        else:
            model_cfg = _select_model_config(models_config, args.model)

        # 模型配置中的 class / kwargs / 常用字段覆盖 modules.json 中的默认值。
        llm_id = workflow.bindings["llm_id"]
        llm_spec = next((spec for spec in module_specs if spec.get("id") == llm_id), None)
        if llm_spec is None:
            parser.error(f"工作流绑定的模型模块 {llm_id!r} 不在模块清单中")
        selected_llm_class = model_cfg.get("class")
        if selected_llm_class:
            llm_spec["class"] = model_cfg["class"]
        llm_kwargs = (
            {} if selected_llm_class else dict(llm_spec.get("kwargs", {}))
        )
        if isinstance(model_cfg.get("kwargs"), dict):
            llm_kwargs.update(model_cfg["kwargs"])
        # 允许 GGUF 等后端直接在模型条目中声明参数。
        for key, value in model_cfg.items():
            if key not in {"class", "provider", "kwargs", "base_url", "model_name"}:
                llm_kwargs[key] = value
        if "base_url" in model_cfg:
            llm_kwargs["base_url"] = model_cfg["base_url"]
        if "model_name" in model_cfg:
            llm_kwargs["model_name"] = model_cfg["model_name"]
        llm_spec["kwargs"] = llm_kwargs

    # 3. CLI 开关只是配置驱动加载器的兼容覆盖层。
    overrides = {}
    for binding_key, disabled in (
        ("prompt_id", args.disable_prompt),
        ("llm_id", args.disable_llm),
        ("tools_id", args.disable_tools),
        ("skills_id", args.disable_skills),
        ("memory_id", args.disable_memory),
    ):
        module_id = workflow.bindings.get(binding_key)
        if disabled and module_id:
            overrides[module_id] = False
    if args.enable_reviewer:
        reviewer_id = workflow.bindings.get("reviewer_id")
        if reviewer_id:
            overrides[reviewer_id] = True
    if args.disable_reviewer:
        reviewer_id = workflow.bindings.get("reviewer_id")
        if reviewer_id:
            overrides[reviewer_id] = False
    for module_id in args.disable_module:
        overrides[module_id] = False
    for module_id in args.enable_module:
        overrides[module_id] = True

    try:
        modules, configured_enabled = build_modules(
            module_specs,
            agent.bus,
            project_root=project_root,
            enabled_overrides=overrides,
        )
    except (ModuleConfigError, TypeError, ImportError) as e:
        parser.error(f"加载模块失败: {e}")

    # 4. 所有模块统一注册，主循环不需要知道具体模块类。
    for module_id, module in modules.items():
        agent.register_module(module, enabled=configured_enabled.get(module_id, True))

    # 5. 启动Agent（初始化所有模块并注册到总线）
    agent.start()

    # 6. 进入无限循环对话，直到用户输入退出命令
    print(f"\n{'='*60}")
    print(f"Agent 已启动，输入 'exit' 或 'quit' 退出")
    print(f"{'='*60}\n")

    try:
        while True:
            # 获取用户输入
            user_input = input("你: ").strip()

            # 检查退出命令
            if user_input.lower() in ['exit', 'quit', 'q']:
                print("\n再见！")
                break

            # 跳过空输入
            if not user_input:
                continue

            # 运行Agent（ReAct循环）
            result = agent.run(
                user_input=user_input,
                mode=args.mode,
                **workflow.bindings
            )

            # 输出结果
            print(f"\nATRI-Agent: {result}\n")

    except KeyboardInterrupt:
        # 捕获 Ctrl+C
        print("\n\n检测到中断信号，正在退出...")
    finally:
        # 7. 停止Agent（清理资源），确保任何情况下都会执行
        agent.stop()


if __name__ == "__main__":
    main()
