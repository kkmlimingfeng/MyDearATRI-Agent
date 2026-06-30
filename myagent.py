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


def _select_model_numbered(models: dict) -> str:
    """没有 readchar 时的回退：数字编号选择模型"""
    keys = list(models.keys())
    print("\n请选择模型：")
    for i, key in enumerate(keys, 1):
        cfg = models[key]
        print(f"  {i}. {key}: {cfg.get('model_name')} @ {cfg.get('base_url')}")

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
            print(f"{prefix}{key}: {cfg.get('model_name')} @ {cfg.get('base_url')}")

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


# 加载 config/.env 中的环境变量
_env_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "config",
    ".env"
)
_load_env_file(_env_path)


from bus import EventBus
from agent import ReactAgent
from modules.prompt import PromptManager
from modules.llm.openai_llm import OpenAILLM
from modules.tools import ToolModule
from modules.skills import SkillModule
from modules.mem import MemoryModule
from modules.reviewer import ReviewerModule


def main():
    """主函数：创建并运行Agent"""

    # 模块开关：通过命令行参数控制各模块是否启用
    parser = argparse.ArgumentParser(description="MyDearATRI-Agent 启动脚本")
    parser.add_argument("--disable-prompt", action="store_true", help="禁用提示词模块")
    parser.add_argument("--disable-llm", action="store_true", help="禁用LLM模块")
    parser.add_argument("--disable-tools", action="store_true", help="禁用工具模块")
    parser.add_argument("--disable-skills", action="store_true", help="禁用技能模块")
    parser.add_argument("--disable-memory", action="store_true", help="禁用记忆模块")
    parser.add_argument("--enable-reviewer", action="store_true", help="启用Reviewer模块（默认禁用）")
    parser.add_argument("--model", "-m", type=str, default="", help="选择预定义模型（在 config/models.json 中配置）")
    parser.add_argument("--select-model", action="store_true", help="启动时交互式选择模型（支持 ↑↓ 方向键）")
    parser.add_argument("--list-models", action="store_true", help="列出 config/models.json 中可用的模型并退出")
    args = parser.parse_args()

    enable_prompt = not args.disable_prompt
    enable_llm = not args.disable_llm
    enable_tools = not args.disable_tools
    enable_skills = not args.disable_skills
    enable_memory = not args.disable_memory
    enable_reviewer = args.enable_reviewer

    # 1. 创建Agent（内部创建EventBus）
    agent = ReactAgent(max_iterations=5)

    # 配置文件路径（用于工具/技能级开关）
    config_dir = os.path.join(os.path.dirname(__file__), "config")
    tools_config_path = os.path.join(config_dir, "tools.json")
    skills_config_path = os.path.join(config_dir, "skills.json")
    models_config_path = os.path.join(config_dir, "models.json")

    # 加载预定义模型配置
    models_config = _load_models_config(models_config_path)

    # 如果用户要求列出模型，打印后退出
    if args.list_models:
        print("\n可用模型列表（config/models.json）：")
        if not models_config:
            print("  （暂无预定义模型）")
        for key, cfg in models_config.items():
            print(f"  - {key}: {cfg.get('model_name')} @ {cfg.get('base_url')}")
        print()
        return

    # 2. 创建模块实例（每个模块都持有bus引用）
    prompt_mgr = PromptManager("prompt", agent.bus) if enable_prompt else None

    # 选择并创建 LLM 模块
    if enable_llm:
        # 如果要求交互式选择，或者没有通过 --model 指定且 models.json 里有多个模型
        if args.select_model or (not args.model and len(models_config) > 1):
            selected_key = _select_model_interactive(models_config)
            model_cfg = models_config[selected_key]
        else:
            model_cfg = _select_model_config(models_config, args.model)

        # 命令行/交互式选择的模型优先级最高；未指定时回退到环境变量
        base_url = model_cfg.get("base_url") or os.environ.get("OPENAI_BASE_URL", "")
        model_name = model_cfg.get("model_name") or os.environ.get("OPENAI_MODEL_NAME", "")
        api_key = os.environ.get("OPENAI_API_KEY", "")

        if not api_key:
            print("[警告] OPENAI_API_KEY 未设置，LLM 调用可能会失败")
        if not base_url or not model_name:
            print("[警告] LLM 的 base_url 或 model_name 未设置，请检查 config/models.json 或 config/.env")

        llm = OpenAILLM(
            "llm",
            agent.bus,
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
        )
    else:
        llm = None

    tools = ToolModule("tools", agent.bus, config_path=tools_config_path) if enable_tools else None
    skills = SkillModule("skills", agent.bus, config_path=skills_config_path) if enable_skills else None
    memory = MemoryModule("memory", agent.bus) if enable_memory else None
    reviewer = ReviewerModule("reviewer", agent.bus, llm_id="llm") if enable_reviewer else None

    # 3. 自动扫描并注册 tools / skills
    if enable_tools and tools is not None:
        tools_dir = os.path.join(os.path.dirname(__file__), "modules", "tools", "system_tools")
        tools.register_tools_from_directory(tools_dir)

    if enable_skills and skills is not None:
        skills_dir = os.path.join(os.path.dirname(__file__), "modules", "skills")
        skills.register_skills_from_directory(skills_dir)

    # 4. 注册模块到Agent
    if prompt_mgr is not None:
        agent.register_module(prompt_mgr, enabled=enable_prompt)
    if llm is not None:
        agent.register_module(llm, enabled=enable_llm)
    if tools is not None:
        agent.register_module(tools, enabled=enable_tools)
    if skills is not None:
        agent.register_module(skills, enabled=enable_skills)
    if memory is not None:
        agent.register_module(memory, enabled=enable_memory)
    if reviewer is not None:
        agent.register_module(reviewer, enabled=enable_reviewer)

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
                prompt_name="default",  # 使用 AGENT.md + SOUL.md + USER.md 拼接的系统提示词
                llm_id="llm",
                tools_id="tools",
                skills_id="skills",
                memory_id="memory",
                reviewer_id="reviewer"
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
