"""
MyDearATRI-Agent 启动脚本
模块化Agent架构演示
"""
import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bus import EventBus
from agent import ReactAgent
from modules.prompt import PromptManager
from modules.llm import ModelScopeLLM
from modules.tools import BaseTool
from modules.tools.system_tools.weather import get_weather


def main():
    """主函数：创建并运行Agent"""
    
    # 1. 创建Agent（内部创建EventBus）
    agent = ReactAgent(max_iterations=5)
    
    # 2. 创建模块实例（每个模块都持有bus引用）
    prompt_mgr = PromptManager("prompt", agent.bus)
    llm = ModelScopeLLM("llm", agent.bus, model_path="./Qwen/Qwen3-0.6B")
    tools = BaseTool("tools", agent.bus)
    
    # 3. 注册工具函数到ToolModule
    tools.register_tool("get_weather", get_weather)
    
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
    
    # 7. 停止Agent（清理资源）
    agent.stop()


if __name__ == "__main__":
    main()
