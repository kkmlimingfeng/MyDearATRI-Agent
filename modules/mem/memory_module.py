"""
文件记忆模块

自动读取项目中的记忆文件（modules/mem/memory.md），并在每次对话时
通过总线将记忆内容注入到系统提示词中。

Agent 可以通过 file_operations 技能中描述的 exec_sandbox_cmd 命令
随时追加或修改记忆文件。
"""
import os
from modules.base import BaseModule
from bus.base import Message, MessageType


class MemoryModule(BaseModule):
    """文件记忆模块：读取本地 markdown 记忆文件并注入上下文"""

    def __init__(self, module_id: str, bus, memory_path: str = None):
        super().__init__(module_id, bus)
        if memory_path is None:
            memory_path = os.path.join(
                os.path.dirname(__file__), "memory.md"
            )
        self.memory_path = os.path.abspath(memory_path)
        self._memory_content: str = ""

    def initialize(self) -> None:
        """初始化：读取记忆文件"""
        self._memory_content = self._read_memory()
        self._initialized = True

    def _read_memory(self) -> str:
        """读取记忆文件内容，不存在则返回空字符串"""
        if not os.path.isfile(self.memory_path):
            return ""
        try:
            with open(self.memory_path, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except Exception as e:
            print(f"[memory] 读取记忆文件失败: {e}")
            return ""

    def get_memory(self) -> str:
        """获取当前记忆内容（会重新读取文件）"""
        self._memory_content = self._read_memory()
        return self._memory_content

    def handle_message(self, message: Message) -> None:
        """处理总线消息

        支持 action:
            - 'get_memory': 返回当前记忆内容
        """
        if message.type != MessageType.REQUEST:
            return

        action = message.payload.get('action')
        if action == 'get_memory':
            self.send(
                target=message.source,
                payload={'memory': self.get_memory()},
                msg_type=MessageType.RESPONSE,
                correlation_id=message.correlation_id
            )

    def shutdown(self) -> None:
        """关闭记忆模块"""
        self._memory_content = ""
        self._initialized = False
