"""
MyDearATRI-Agent 启动脚本
模块化Agent架构演示
"""
import sys
import os

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


def main():
    """主函数：创建并运行Agent"""

    # 1. 创建Agent（内部创建EventBus）
    agent = ReactAgent(max_iterations=5)

    # 2. 创建模块实例（每个模块都持有bus引用）
    prompt_mgr = PromptManager("prompt", agent.bus)
    llm = ModelScopeLLM("llm", agent.bus, model_path="./Qwen/Qwen3-0.6B")
    tools = ToolModule("tools", agent.bus)

    # 3. 自动扫描并注册 system_tools 目录下的工具函数
    tools_dir = os.path.join(os.path.dirname(__file__), "modules", "tools", "system_tools")
    tools.register_tools_from_directory(tools_dir)

    # 4. 注册模块到Agent
    agent.register_module(prompt_mgr, enabled=True)
    agent.register_module(llm, enabled=True)
    agent.register_module(tools, enabled=True)

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
