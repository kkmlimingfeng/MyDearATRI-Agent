"""
MyDearATRI-Agent 启动脚本
模块化Agent架构演示
"""
import sys
import os
import argparse

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
from modules.llm import ModelScopeLLM
from modules.tools import ToolModule
from modules.skills import SkillModule


def main():
    """主函数：创建并运行Agent"""

    # 模块开关：通过命令行参数控制各模块是否启用
    parser = argparse.ArgumentParser(description="MyDearATRI-Agent 启动脚本")
    parser.add_argument("--disable-prompt", action="store_true", help="禁用提示词模块")
    parser.add_argument("--disable-llm", action="store_true", help="禁用LLM模块")
    parser.add_argument("--disable-tools", action="store_true", help="禁用工具模块")
    parser.add_argument("--disable-skills", action="store_true", help="禁用技能模块")
    args = parser.parse_args()

    enable_prompt = not args.disable_prompt
    enable_llm = not args.disable_llm
    enable_tools = not args.disable_tools
    enable_skills = not args.disable_skills

    # 1. 创建Agent（内部创建EventBus）
    agent = ReactAgent(max_iterations=5)

    # 配置文件路径（用于工具/技能级开关）
    config_dir = os.path.join(os.path.dirname(__file__), "config")
    tools_config_path = os.path.join(config_dir, "tools.json")
    skills_config_path = os.path.join(config_dir, "skills.json")

    # 2. 创建模块实例（每个模块都持有bus引用）
    prompt_mgr = PromptManager("prompt", agent.bus) if enable_prompt else None
    llm = ModelScopeLLM("llm", agent.bus, model_path="./Qwen/Qwen3-0.6B") if enable_llm else None
    tools = ToolModule("tools", agent.bus, config_path=tools_config_path) if enable_tools else None
    skills = SkillModule("skills", agent.bus, config_path=skills_config_path) if enable_skills else None

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
                prompt_name="travel",  # 使用travel.md系统提示词
                llm_id="llm",
                tools_id="tools"
            )

            # 输出结果
            print(f"\nAgent: {result}\n")

    except KeyboardInterrupt:
        # 捕获 Ctrl+C
        print("\n\n检测到中断信号，正在退出...")
    finally:
        # 7. 停止Agent（清理资源），确保任何情况下都会执行
        agent.stop()


if __name__ == "__main__":
    main()
