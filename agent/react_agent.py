"""
ReAct Agent - Thought-Action-Observation循环实现
"""
import ast
import re
from typing import Dict, Tuple, Optional, Any
from .base_agent import BaseAgent, Colors


class ReactAgent(BaseAgent):
    """ReAct Agent，实现Thought-Action-Observation循环"""

    def __init__(self, max_iterations: int = 10, max_history_turns: int = 10):
        # 调用父类初始化
        super().__init__()
        # 最大循环次数，防止Agent无限循环
        self.max_iterations = max_iterations
        # 保留的最大历史对话轮数（一轮 = user + assistant）
        self.max_history_turns = max_history_turns
        # 历史对话记录，只保存对外的 user/assistant 消息，不包含 ReAct 内部细节
        self._history: list = []

    def _inject_module_descriptions(
        self,
        base_prompt: str,
        target: str,
        placeholder: str,
        action: str
    ) -> str:
        """
        从指定模块获取描述文本，并注入到系统提示词中。

        支持占位符替换：如果 base_prompt 中包含占位符，则替换为描述文本；
        否则将描述文本追加到系统提示词末尾。
        """
        try:
            response = self.bus.request(
                source='agent',
                target=target,
                payload={'action': action}
            )
            descriptions = response.payload.get('text', '')
        except Exception:
            # 如果目标模块未响应，保持原提示词不变
            return base_prompt

        if not descriptions:
            return base_prompt

        if placeholder in base_prompt:
            return base_prompt.replace(placeholder, descriptions)

        return base_prompt + '\n\n' + descriptions

    def _inject_tool_descriptions(self, base_prompt: str, tools_id: str) -> str:
        """注入工具描述到系统提示词（{{TOOLS}} 占位符）"""
        return self._inject_module_descriptions(
            base_prompt, tools_id, '{{TOOLS}}', 'format_tool_descriptions'
        )

    def _inject_skill_overview(self, base_prompt: str, skills_id: str) -> str:
        """注入技能目录简介到系统提示词（{{SKILLS}} 占位符）"""
        return self._inject_module_descriptions(
            base_prompt, skills_id, '{{SKILLS}}', 'format_skill_overview'
        )

    def parse_output(self, output: str) -> Tuple[str, str, str]:
        """
        解析LLM输出，提取Thought和Action
        :param output: LLM的原始输出
        :return: (thought, action, error)
                 - thought: 思考内容
                 - action: 行动内容
                 - error: 错误信息（如果有）
        """
        # 尝试截断多余的Thought-Action对（模型可能输出多对）
        match = re.search(
            r'(Thought:.*?Action:.*?)(?=\n\s*(?:Thought:|Action:)|\Z)',
            output,
            re.DOTALL
        )
        # 如果匹配到，只保留第一对
        if match:
            output = match.group(1).strip()
        
        # 解析Thought内容（从"Thought:"到"Action:"之间）
        thought_match = re.search(r'Thought:\s*(.*?)\s*(?=Action:)', output, re.DOTALL)
        # 解析Action内容（"Action:"之后的所有内容）
        action_match = re.search(r'Action:\s*(.*)', output, re.DOTALL)
        
        # 如果没有匹配到 Action，尝试将输出作为直接回答处理
        if not action_match:
            output = output.strip()
            if output:
                # 将无 Action 的输出回退为 Finish[输出内容]
                return (
                    "用户的问题不需要使用工具，直接回答即可。",
                    f"Finish[{output}]",
                    ""
                )
            return "", "", "未能解析到 Action 字段，请确保格式为 'Thought: ... Action: ...'"

        # 提取Thought内容（如果没有则为空）
        thought = thought_match.group(1).strip() if thought_match else ""
        # 提取Action内容
        action = action_match.group(1).strip()

        return thought, action, ""
    
    def execute_action(self, action: str, tools_module_id: str = 'tools') -> Tuple[Optional[str], str]:
        """
        执行Action，返回观察结果或最终答案
        :param action: Action内容
        :param tools_module_id: 工具模块ID
        :return: (observation, final_answer)
                 - observation: 工具执行结果（如果未完成）
                 - final_answer: 最终答案（如果任务完成）
        """
        # 检查是否是Finish（任务完成）
        if "Finish" in action:
            # 提取最终答案
            finish_match = re.search(r"Finish\[(.*)\]", action)
            # 如果匹配到Finish[...]格式
            if finish_match:
                return None, finish_match.group(1)
            # 否则取Finish后面的所有内容
            return None, action.replace("Finish", "").strip("[]").strip()

        # 解析工具调用：提取工具名和参数
        tool_name_match = re.search(r"(\w+)\(", action)
        # 如果没有匹配到工具调用格式，返回错误
        if not tool_name_match:
            return f"无法解析工具调用 '{action}'", ""

        # 提取工具名称
        tool_name = tool_name_match.group(1)
        # 提取参数字符串（支持简单嵌套括号）
        args_match = re.search(r"\((.*)\)", action)
        args_str = args_match.group(1).strip() if args_match else ""
        # 解析参数为字典（支持 key="value"、key='value'、key=数字/布尔等）
        tool_kwargs: Dict[str, Any] = {}
        if args_str:
            for key, dquote, squote, bare in re.findall(
                r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^,]+))',
                args_str
            ):
                value: Any = dquote or squote or bare.strip()
                # 尝试将字面量转换为 Python 对象（数字、布尔、None 等）
                try:
                    value = ast.literal_eval(value)
                except (ValueError, SyntaxError):
                    pass
                tool_kwargs[key] = value

        # 检查工具模块是否启用
        if not self._enabled.get(tools_module_id, False):
            observation = "错误: 工具模块已禁用，无法执行工具调用"
            print(f"{Colors.RED}{observation}{Colors.RESET}")
            return observation, ""

        # 蓝色输出：正在调用工具
        print(f"{Colors.BLUE}正在调用工具: {tool_name}({tool_kwargs}){Colors.RESET}")

        # 通过总线调用工具
        try:
            response = self.bus.request(
                source='agent',
                target=tools_module_id,
                payload={
                    'action': 'call',
                    'tool_name': tool_name,
                    'params': tool_kwargs
                }
            )
            # 检查响应中是否有错误
            if 'error' in response.payload:
                observation = f"错误: {response.payload['error']}"
                print(f"{Colors.RED}{observation}{Colors.RESET}")
            else:
                observation = response.payload.get('result', '')
        except Exception as e:
            # 红色输出：工具调用失败
            observation = f"错误: 工具调用失败 - {str(e)}"
            print(f"{Colors.RED}{observation}{Colors.RESET}")

        return observation, ""
    
    def run(
        self,
        user_input: str,
        prompt_name: str = 'default',
        prompt_id: str = 'prompt',
        llm_id: str = 'llm',
        tools_id: str = 'tools',
        skills_id: str = 'skills',
        **kwargs
    ) -> str:
        """
        运行ReAct Agent
        :param user_input: 用户输入
        :param prompt_name: 使用的系统提示词名称
        :param prompt_id: 使用的提示词模块ID
        :param llm_id: 使用的LLM模块ID
        :param tools_id: 使用的工具模块ID
        :param skills_id: 使用的技能模块ID
        :return: 最终回答
        """
        # 检查必要模块是否存在且启用
        if not self._enabled.get(prompt_id, False):
            # 红色输出：错误信息
            print(f"{Colors.RED}错误: PromptManager模块 {prompt_id} 未启用{Colors.RESET}")
            return "错误: 提示词模块不可用"
        if not self._enabled.get(llm_id, False):
            # 红色输出：错误信息
            print(f"{Colors.RED}错误: LLM模块 {llm_id} 未启用{Colors.RESET}")
            return f"错误: LLM模块 {llm_id} 不可用"
        # tools 和 skills 模块为可选，关闭时不影响基础对话

        # 通过总线获取系统提示词
        try:
            prompt_response = self.bus.request(
                source='agent',
                target=prompt_id,
                payload={
                    'action': 'get_system_prompt',
                    'prompt_name': prompt_name
                }
            )
            base_prompt = prompt_response.payload.get('system_prompt', '')
        except Exception as e:
            # 红色输出：获取提示词失败
            print(f"{Colors.RED}错误: 获取系统提示词失败 - {str(e)}{Colors.RESET}")
            return "错误: 获取系统提示词失败"

        # 构建完整的系统提示词：注入工具描述和技能描述
        system_prompt = base_prompt
        # 如果工具模块已启用，注入工具描述
        if self._enabled.get(tools_id, False):
            system_prompt = self._inject_tool_descriptions(system_prompt, tools_id)
        # 如果技能模块已启用，注入技能目录简介
        if self._enabled.get(skills_id, False):
            system_prompt = self._inject_skill_overview(system_prompt, skills_id)

        # 构建历史对话记录，使用标准messages格式
        # 取最近的 max_history_turns 轮对话 + 当前用户输入
        context_messages = self._history[-self.max_history_turns * 2:]
        messages = [
            {"role": "system", "content": system_prompt},
            *context_messages,
            {"role": "user", "content": user_input}
        ]

        # 品红色输出：用户输入
        print(f"\n{Colors.MAGENTA}{Colors.BOLD}用户输入:{Colors.RESET} {user_input}")
        print(f"{Colors.DIM}{'='*50}{Colors.RESET}")

        # 开始ReAct循环
        for i in range(self.max_iterations):
            # 青色输出：循环开始
            print(f"\n{Colors.CYAN}{Colors.BOLD}--- 循环 {i+1} ---{Colors.RESET}\n")

            # 暗淡输出：正在调用LLM
            print(f"{Colors.DIM}正在调用LLM...{Colors.RESET}")

            # 通过总线调用LLM
            try:
                llm_response = self.bus.request(
                    source='agent',
                    target=llm_id,
                    payload={
                        'action': 'generate',
                        'messages': messages
                    }
                )
                output = llm_response.payload.get('response', '')
            except Exception as e:
                # 红色输出：LLM调用失败
                print(f"{Colors.RED}错误: LLM调用失败 - {str(e)}{Colors.RESET}")
                return "错误: LLM调用失败"

            # 绿色输出：模型回复
            print(f"{Colors.GREEN}{Colors.BOLD}模型输出:{Colors.RESET}\n{output}\n")
            # 将助手回复加入messages
            messages.append({"role": "assistant", "content": output})

            # 解析LLM输出
            thought, action, error = self.parse_output(output)

            # 如果解析出错，记录错误并继续
            if error:
                observation_str = f"Observation: 错误: {error}"
                # 红色输出：解析错误
                print(f"{Colors.RED}{observation_str}{Colors.RESET}")
                print(f"{Colors.DIM}{'='*50}{Colors.RESET}")
                # 将观察结果加入messages
                messages.append({"role": "user", "content": observation_str})
                continue

            # 执行Action（通过总线调用工具）
            observation, final_answer = self.execute_action(action, tools_id)

            # 如果任务完成，返回最终答案
            if final_answer:
                # 保存本轮对外的 user/assistant 消息到历史
                self._add_to_history(user_input, final_answer)
                # 绿色加粗输出：最终答案
                print(f"\n{Colors.GREEN}{Colors.BOLD}任务完成，最终答案:{Colors.RESET} {final_answer}")
                return final_answer

            # 将工具返回结果格式化并加入messages
            observation_str = f"Observation: {observation}"
            # 黄色输出：观察结果
            print(f"{Colors.GREEN}{observation_str}{Colors.RESET}")
            print(f"{Colors.DIM}{'='*50}{Colors.RESET}")
            messages.append({"role": "user", "content": observation_str})
            print(f"{Colors.CYAN}{messages}{Colors.RESET}")

        # 如果循环结束仍未得到最终答案
        # 红色输出：超出最大循环次数
        fallback = f"已达到最大循环次数 {self.max_iterations}，任务未完成"
        print(f"{Colors.RED}{fallback}{Colors.RESET}")
        # 仍然保存本轮记录，避免历史完全丢失
        self._add_to_history(user_input, fallback)
        return fallback

    def _add_to_history(self, user_input: str, assistant_answer: str) -> None:
        """将一轮对外的 user/assistant 消息加入历史，并裁剪到窗口大小"""
        self._history.append({"role": "user", "content": user_input})
        self._history.append({"role": "assistant", "content": assistant_answer})
        # 只保留最近 max_history_turns 轮
        self._history = self._history[-self.max_history_turns * 2:]
