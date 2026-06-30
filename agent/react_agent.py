"""
ReAct Agent - Thought-Action-Observation循环实现
"""
import ast
import json
import os
import re
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any
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

    def _inject_memory(self, base_prompt: str, memory_id: str = 'memory') -> str:
        """
        自动注入长期记忆到系统提示词。

        如果 memory 模块已启用，则从总线获取 memory.md 内容并追加到系统提示词。
        """
        if not self._enabled.get(memory_id, False):
            return base_prompt

        try:
            response = self.bus.request(
                source='agent',
                target=memory_id,
                payload={'action': 'get_memory'}
            )
            memory_content = response.payload.get('memory', '')
        except Exception:
            return base_prompt

        if not memory_content:
            return base_prompt

        memory_section = f"## 长期记忆\n\n{memory_content}"
        return base_prompt + '\n\n' + memory_section

    def parse_output(self, output: str) -> Tuple[str, List[str], str]:
        """
        解析LLM输出，提取Thought和一个或多个Action
        :param output: LLM的原始输出
        :return: (thought, actions, error)
                 - thought: 思考内容
                 - actions: 行动内容列表（每个元素是一个 Action 字符串）
                 - error: 错误信息（如果有）
        """
        output = output.strip()
        if not output:
            return "", [], "输出为空"

        # 提取第一个 Thought-Action 块（若模型输出多对 Thought-Action，只取第一块）
        block_match = re.search(
            r'Thought:\s*(.*?)\s*(?=(?:Thought:)|\Z)',
            output,
            re.DOTALL
        )
        block = block_match.group(1).strip() if block_match else output

        # 提取 Thought 内容（从块开头到第一个 Action: 之前）
        thought_match = re.search(r'^(.*?)\s*(?=Action:)', block, re.DOTALL)
        thought = thought_match.group(1).strip() if thought_match else ""

        # 提取所有 Action（每行一个 Action: ...）
        actions = re.findall(r'Action:\s*(.+)', block)
        actions = [a.strip() for a in actions if a.strip()]

        if not actions:
            # 如果没有匹配到 Action，尝试将输出作为直接回答处理
            if output:
                return (
                    "用户的问题不需要使用工具，直接回答即可。",
                    [f"Finish[{output}]"],
                    ""
                )
            return "", [], "未能解析到 Action 字段，请确保格式为 'Thought: ... Action: ...'"

        return thought, actions, ""
    
    def execute_action(
        self,
        actions: List[str],
        tools_module_id: str = 'tools'
    ) -> Tuple[Optional[str], str]:
        """
        执行一个或多个Action，返回观察结果或最终答案
        :param actions: Action 内容列表（支持多个独立工具调用）
        :param tools_module_id: 工具模块ID
        :return: (observation, final_answer)
                 - observation: 工具执行结果（如果未完成），多个结果会合并
                 - final_answer: 最终答案（如果任务完成）
        """
        if not actions:
            return "错误: 没有可执行的 Action", ""

        # 如果包含 Finish，必须单独出现
        finish_actions = [a for a in actions if "Finish" in a]
        if finish_actions:
            if len(actions) > 1:
                return "错误: Finish 不能与其他 Action 同时执行", ""
            return self._execute_finish(finish_actions[0])

        # 检查工具模块是否启用
        if not self._enabled.get(tools_module_id, False):
            observation = "错误: 工具模块已禁用，无法执行工具调用"
            print(f"{Colors.RED}{observation}{Colors.RESET}")
            return observation, ""

        results = []
        for action in actions:
            result = self._execute_single_tool(action, tools_module_id)
            results.append((action, result))

        # 合并多个 Observation，格式与 AGENT.md 中说明的一致
        if len(results) == 1:
            observation = results[0][1]
        else:
            lines = ["- " + action + " -> " + result for action, result in results]
            observation = "\n".join(lines)

        return observation, ""

    def _execute_finish(self, action: str) -> Tuple[Optional[str], str]:
        """执行 Finish Action，提取最终答案"""
        finish_match = re.search(r"Finish\[(.*)\]", action)
        if finish_match:
            return None, finish_match.group(1)
        return None, action.replace("Finish", "").strip("[]").strip()

    def _parse_tool_call(self, action: str) -> Tuple[str, Dict[str, Any]]:
        """解析单个工具调用，返回 (tool_name, tool_kwargs)"""
        tool_name_match = re.search(r"(\w+)\(", action)
        if not tool_name_match:
            raise ValueError(f"无法解析工具调用 '{action}'")

        tool_name = tool_name_match.group(1)
        args_match = re.search(r"\((.*)\)", action)
        args_str = args_match.group(1).strip() if args_match else ""

        tool_kwargs: Dict[str, Any] = {}
        if args_str:
            for key, dquote, squote, bare in re.findall(
                r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^,]+))',
                args_str
            ):
                value: Any = dquote or squote or bare.strip()
                try:
                    value = ast.literal_eval(value)
                except (ValueError, SyntaxError):
                    pass
                tool_kwargs[key] = value

        return tool_name, tool_kwargs

    def _execute_single_tool(
        self,
        action: str,
        tools_module_id: str = 'tools'
    ) -> str:
        """执行单个工具调用，返回观察结果字符串"""
        try:
            tool_name, tool_kwargs = self._parse_tool_call(action)
        except ValueError as e:
            error_msg = str(e)
            print(f"{Colors.RED}{error_msg}{Colors.RESET}")
            return error_msg

        # 蓝色输出：正在调用工具
        print(f"{Colors.BLUE}正在调用工具: {tool_name}({tool_kwargs}){Colors.RESET}")

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
            if 'error' in response.payload:
                observation = f"错误: {response.payload['error']}"
                print(f"{Colors.RED}{observation}{Colors.RESET}")
            else:
                observation = response.payload.get('result', '')
        except Exception as e:
            observation = f"错误: 工具调用失败 - {str(e)}"
            print(f"{Colors.RED}{observation}{Colors.RESET}")

        return observation
    
    def run(
        self,
        user_input: str,
        prompt_name: str = 'default',
        prompt_id: str = 'prompt',
        llm_id: str = 'llm',
        tools_id: str = 'tools',
        skills_id: str = 'skills',
        memory_id: str = 'memory',
        reviewer_id: str = 'reviewer',
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
        :param memory_id: 使用的记忆模块ID
        :param reviewer_id: 使用的Reviewer模块ID
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

        # 构建完整的系统提示词：注入工具描述、技能描述和长期记忆
        system_prompt = base_prompt
        # 如果工具模块已启用，注入工具描述
        if self._enabled.get(tools_id, False):
            system_prompt = self._inject_tool_descriptions(system_prompt, tools_id)
        # 如果技能模块已启用，注入技能目录简介
        if self._enabled.get(skills_id, False):
            system_prompt = self._inject_skill_overview(system_prompt, skills_id)
        # 如果记忆模块已启用，自动注入长期记忆
        system_prompt = self._inject_memory(system_prompt, memory_id)

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
            thought, actions, error = self.parse_output(output)

            # 如果解析出错，记录错误并继续
            if error:
                observation_str = f"Observation: 错误: {error}"
                # 红色输出：解析错误
                print(f"{Colors.RED}{observation_str}{Colors.RESET}")
                print(f"{Colors.DIM}{'='*50}{Colors.RESET}")
                # 将观察结果加入messages
                messages.append({"role": "user", "content": observation_str})
                continue

            # 执行Action（通过总线调用工具，支持多个 Action 顺序执行）
            observation, final_answer = self.execute_action(actions, tools_id)

            # 如果任务完成，先触发 reviewer 总结，再返回最终答案
            if final_answer:
                # 保存本轮对外的 user/assistant 消息到历史
                self._add_to_history(user_input, final_answer)
                # 绿色加粗输出：最终答案
                # print(f"\n{Colors.GREEN}{Colors.BOLD}任务完成，最终答案:{Colors.RESET} {final_answer}")
                # 后台 reviewer 处理（用户不可见）
                self._run_reviewer(
                    user_input=user_input,
                    final_answer=final_answer,
                    messages=messages,
                    reviewer_id=reviewer_id,
                    prompt_id=prompt_id
                )
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
        # 后台 reviewer 处理（用户不可见）
        self._run_reviewer(
            user_input=user_input,
            final_answer=fallback,
            messages=messages,
            reviewer_id=reviewer_id,
            prompt_id=prompt_id
        )
        return fallback

    def _run_reviewer(
        self,
        user_input: str,
        final_answer: str,
        messages: list,
        reviewer_id: str,
        prompt_id: str
    ) -> None:
        """
        在最终答案输出后，后台调用 Reviewer 模块进行总结。

        该过程对用户不可见，只负责更新 memory.md 和 USER.md。
        """
        if not self._enabled.get(reviewer_id, False):
            return

        try:
            reviewer_prompt = self._get_reviewer_prompt(prompt_id)
            if not reviewer_prompt:
                return

            conversation_text = self._build_conversation_text(messages, final_answer)

            response = self.bus.request(
                source='agent',
                target=reviewer_id,
                payload={
                    'action': 'review',
                    'system_prompt': reviewer_prompt,
                    'conversation_text': conversation_text
                }
            )

            if 'error' in response.payload:
                return

            result = response.payload.get('result', {})
            self._apply_review_result(result)
        except Exception:
            # Reviewer 失败不应影响主流程
            pass

    def _get_reviewer_prompt(self, prompt_id: str) -> str:
        """从 PromptManager 获取 reviewer 系统提示词"""
        try:
            response = self.bus.request(
                source='agent',
                target=prompt_id,
                payload={
                    'action': 'get_system_prompt',
                    'prompt_name': 'reviewer'
                }
            )
            return response.payload.get('system_prompt', '')
        except Exception:
            return ''

    def _build_conversation_text(self, messages: list, final_answer: str) -> str:
        """将 messages 列表构建为供 reviewer 阅读的对话文本"""
        lines = []
        for msg in messages:
            role = msg.get('role', '')
            content = msg.get('content', '')
            if role == 'system':
                lines.append(f"[系统提示词]\n{content}")
            elif role == 'user':
                lines.append(f"[用户]\n{content}")
            elif role == 'assistant':
                lines.append(f"[Agent]\n{content}")
        lines.append(f"[最终回答]\n{final_answer}")
        return '\n\n'.join(lines)

    def _apply_review_result(self, result: Dict[str, Any]) -> None:
        """应用 reviewer 输出，更新 memory.md 和 USER.md"""
        memory_entries = result.get('memory_entries', [])
        profile_updates = result.get('user_profile_updates', {})

        if memory_entries:
            self._append_memory_entries(memory_entries)

        if profile_updates:
            self._update_user_profile(profile_updates)

    def _append_memory_entries(self, entries: list) -> None:
        """将记忆条目追加到 modules/mem/memory.md"""
        memory_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "modules", "mem", "memory.md"
        )
        try:
            os.makedirs(os.path.dirname(memory_path), exist_ok=True)
            with open(memory_path, 'a', encoding='utf-8') as f:
                for entry in entries:
                    f.write(f"- {entry}\n")
        except Exception:
            pass

    def _update_user_profile(self, updates: Dict[str, str]) -> None:
        """更新 modules/prompt/SystemPrompt/USER.md"""
        user_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "modules", "prompt", "SystemPrompt", "USER.md"
        )
        try:
            os.makedirs(os.path.dirname(user_path), exist_ok=True)

            if os.path.isfile(user_path):
                with open(user_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            else:
                content = ""

            content = self._merge_user_profile(content, updates)

            with open(user_path, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception:
            pass

    def _merge_user_profile(self, content: str, updates: Dict[str, str]) -> str:
        """合并用户画像更新到现有 markdown 内容"""
        if not content.strip():
            content = "# USER\n\n## 基本信息\n\n## 偏好\n\n## 目标\n"

        for key, value in updates.items():
            if '-' not in key:
                continue
            section, item = key.split('-', 1)
            content = self._update_profile_item(content, section, item, value)

        return content

    def _update_profile_item(
        self,
        content: str,
        section: str,
        item: str,
        value: str
    ) -> str:
        """在 markdown 中更新或添加某个画像项目"""
        section_pattern = re.compile(rf'^(##\s*{re.escape(section)}\s*)$', re.MULTILINE)
        match = section_pattern.search(content)

        if not match:
            # 章节不存在，追加到末尾
            content += f"\n\n## {section}\n\n- {item}：{value}"
            return content

        section_start = match.end()
        # 找到下一个 ## 标题，或文件末尾
        next_section = re.search(r'\n##\s', content[section_start:])
        if next_section:
            section_end = section_start + next_section.start()
            section_text = content[section_start:section_end]
            remainder = content[section_end:]
        else:
            section_text = content[section_start:]
            remainder = ""

        item_pattern = re.compile(rf'^(-\s*{re.escape(item)}\s*：\s*).*$', re.MULTILINE)
        if item_pattern.search(section_text):
            section_text = item_pattern.sub(rf'\g<1>{value}', section_text)
        else:
            section_text = section_text.rstrip() + f"\n- {item}：{value}"

        return content[:section_start] + section_text + remainder

    def _add_to_history(self, user_input: str, assistant_answer: str) -> None:
        """将一轮对外的 user/assistant 消息加入历史，并裁剪到窗口大小"""
        self._history.append({"role": "user", "content": user_input})
        self._history.append({"role": "assistant", "content": assistant_answer})
        # 只保留最近 max_history_turns 轮
        self._history = self._history[-self.max_history_turns * 2:]
