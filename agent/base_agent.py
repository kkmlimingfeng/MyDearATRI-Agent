"""
Agent基类 - 负责模块管理、生命周期管理
"""
from abc import ABC, abstractmethod
from typing import Dict, Optional
from bus.event_bus import EventBus
from modules.base import BaseModule


# ANSI颜色码，用于终端彩色输出
class Colors:
    RESET = "\033[0m"       # 重置颜色
    BLUE = "\033[94m"       # 蓝色
    GREEN = "\033[92m"      # 绿色
    YELLOW = "\033[93m"     # 黄色
    RED = "\033[91m"        # 红色
    CYAN = "\033[96m"       # 青色
    MAGENTA = "\033[95m"    # 品红色
    BOLD = "\033[1m"        # 加粗
    DIM = "\033[2m"         # 暗淡


class BaseAgent(ABC):
    """
    Agent基类，负责：
    1. 模块字典管理（注册、启用/禁用模块）
    2. 模块生命周期管理（初始化、注册、关闭）
    """
    
    def __init__(self):
        # 创建事件总线，所有模块通过它通信
        self.bus = EventBus()
        # 模块字典：key是模块ID，value是模块实例
        self._modules: Dict[str, BaseModule] = {}
        # 模块开关字典：key是模块ID，value是是否启用
        self._enabled: Dict[str, bool] = {}
    
    # ==================== 模块管理 ====================
    
    def register_module(self, module: BaseModule, enabled: bool = True) -> None:
        """
        注册一个模块到Agent
        :param module: 要注册的模块实例
        :param enabled: 是否启用该模块，默认启用
        """
        # 将模块存入字典
        self._modules[module.module_id] = module
        # 设置模块的启用状态
        self._enabled[module.module_id] = enabled
    
    def enable_module(self, module_id: str) -> None:
        """启用指定模块"""
        # 设置模块为启用状态
        self._enabled[module_id] = True
    
    def disable_module(self, module_id: str) -> None:
        """禁用指定模块"""
        # 设置模块为禁用状态
        self._enabled[module_id] = False
    
    def get_module(self, module_id: str) -> Optional[BaseModule]:
        """根据模块ID获取模块实例"""
        # 从字典中查找并返回模块
        return self._modules.get(module_id)
    
    def list_modules(self) -> Dict[str, bool]:
        """列出所有模块及其启用状态"""
        # 返回模块ID到启用状态的映射
        return dict(self._enabled)
    
    # ==================== 生命周期 ====================
    
    def start(self) -> None:
        """启动Agent：初始化并注册所有已启用的模块"""
        # 青色输出：初始化信息
        print(f"{Colors.CYAN}{Colors.BOLD}{'='*50}{Colors.RESET}")
        print(f"{Colors.CYAN}{Colors.BOLD}  Agent 正在初始化...{Colors.RESET}")
        print(f"{Colors.CYAN}{Colors.BOLD}{'='*50}{Colors.RESET}")
        
        # 遍历所有已注册的模块
        for module_id, module in self._modules.items():
            # 检查模块是否启用
            if self._enabled.get(module_id, False):
                # 初始化模块
                module.initialize()
                # 将模块注册到总线
                module.register()
                # 绿色输出：模块初始化成功
                print(f"{Colors.GREEN}  [✓] 模块 {module_id} 已初始化{Colors.RESET}")
            else:
                # 黄色输出：模块被禁用
                print(f"{Colors.YELLOW}  [×] 模块 {module_id} 已禁用，跳过{Colors.RESET}")
        
        # 青色输出：初始化完成
        print(f"{Colors.CYAN}{Colors.BOLD}{'='*50}{Colors.RESET}")
        print(f"{Colors.GREEN}{Colors.BOLD}  Agent 初始化完成！{Colors.RESET}")
        print(f"{Colors.CYAN}{Colors.BOLD}{'='*50}{Colors.RESET}")
    
    def stop(self) -> None:
        """停止Agent：关闭所有已启用的模块"""
        # 黄色输出：关闭信息
        print(f"\n{Colors.YELLOW}{Colors.BOLD}  Agent 正在关闭...{Colors.RESET}")
        
        # 遍历所有已注册的模块
        for module_id, module in self._modules.items():
            # 检查模块是否启用
            if self._enabled.get(module_id, False):
                # 从总线取消注册
                module.unregister()
                # 关闭模块
                module.shutdown()
                # 蓝色输出：模块已关闭
                print(f"{Colors.BLUE}  [✓] 模块 {module_id} 已关闭{Colors.RESET}")
        
        # 清空总线上的所有订阅
        self.bus.clear()
        # 绿色输出：关闭完成
        print(f"{Colors.GREEN}{Colors.BOLD}  Agent 已完全关闭{Colors.RESET}")
    
    # ==================== 抽象方法 ====================
    
    @abstractmethod
    def run(self, user_input: str, **kwargs) -> str:
        """
        运行Agent主循环，子类必须实现
        :param user_input: 用户输入
        :param kwargs: 其他参数
        :return: 最终回答
        """
        pass
