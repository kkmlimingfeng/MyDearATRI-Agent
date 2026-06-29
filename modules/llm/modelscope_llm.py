"""
ModelScope本地LLM模块 - 使用ModelScope加载本地模型进行推理（如Qwen等）
"""
import re
import torch
import gc
from typing import Optional, List, Dict, Any
from modelscope import AutoModelForCausalLM, AutoTokenizer
from .base_llm import BaseLLM


# ANSI颜色码，用于终端彩色输出
class Colors:
    RESET = "\033[0m"      # 重置颜色
    BLUE = "\033[94m"      # 蓝色
    GREEN = "\033[92m"     # 绿色
    YELLOW = "\033[93m"    # 黄色
    RED = "\033[91m"       # 红色
    CYAN = "\033[96m"      # 青色


class ModelScopeLLM(BaseLLM):
    """ModelScope本地LLM模块，加载本地模型进行推理"""
    
    def __init__(
        self,
        module_id: str,
        bus,
        model_path: str = "./Qwen/Qwen3-0.6B",
        dtype: torch.dtype = torch.bfloat16,
        enable_thinking: bool = True,      # 思考模式开关，默认开启
        max_new_tokens: int = 32768        # 最大生成token数，可配置
    ):
        # 调用父类初始化
        super().__init__(module_id, bus)
        self.model_path = model_path              # 本地模型路径
        self.dtype = dtype                        # 模型精度（bfloat16或float16）
        self.enable_thinking = enable_thinking    # 思考模式开关
        self.max_new_tokens = max_new_tokens      # 最大生成token数
        self.model = None                         # 模型实例
        self.tokenizer = None                     # 分词器实例
    
    def initialize(self) -> None:
        """初始化：加载本地模型和分词器"""
        # 蓝色输出：模型加载开始
        print(f"{Colors.BLUE}[{self.module_id}] 正在加载模型: {self.model_path}{Colors.RESET}")
        # 加载分词器
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        # 加载模型，指定精度和设备映射
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            dtype=self.dtype,
            device_map="auto"             # 自动分配到可用GPU
        )
        # 设置为评估模式，禁用 dropout 等训练专用层
        self.model.eval()
        self._initialized = True
        # 绿色输出：模型加载完成
        print(f"{Colors.GREEN}[{self.module_id}] 模型加载完成{Colors.RESET}")
    
    def generate(self, messages: List[Dict[str, str]]) -> str:
        """
        使用本地模型生成文本
        :param messages: 标准messages格式，如[{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
        :return: 模型生成的文本
        """
        # 使用分词器的chat模板格式化输入
        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,                # 不直接转为tensor，先返回字符串
            add_generation_prompt=True,    # 添加生成起始标记
            enable_thinking=self.enable_thinking  # 思考模式开关
        )
        # 将文本编码为模型输入的tensor，放到模型所在的设备上
        model_inputs = self.tokenizer([text], return_tensors="pt").to(self.model.device)
        # 模型生成，使用可配置的max_new_tokens，关闭梯度计算以节省显存
        with torch.no_grad():
            generated_ids = self.model.generate(
                **model_inputs,
                max_new_tokens=self.max_new_tokens
            )
        # 截取新生成的token ids（去掉输入部分）
        output_ids = generated_ids[0][len(model_inputs.input_ids[0]):].tolist()
        
        # 如果开启思考模式，需要分离思考内容和最终输出
        if self.enable_thinking:
            try:
                # 查找</think>标记的位置（token id为151668），分离思考内容和最终输出
                index = len(output_ids) - output_ids[::-1].index(151668)
            except ValueError:
                # 如果没有</think>标记，说明没有思考内容，index设为0
                index = 0
            # 解码最终输出内容（</think>之后的部分）
            content = self.tokenizer.decode(output_ids[index:], skip_special_tokens=True).strip("\n")
        else:
            # 未开启思考模式，直接解码全部输出
            content = self.tokenizer.decode(output_ids, skip_special_tokens=True).strip("\n")
        
        # 返回最终输出
        return content
    
    def shutdown(self) -> None:
        """关闭模型，释放GPU显存"""
        if self.model is not None:
            del self.model               # 删除模型引用
        if self.tokenizer is not None:
            del self.tokenizer           # 删除分词器引用
        self.model = None
        self.tokenizer = None
        torch.cuda.empty_cache()         # 清空GPU缓存
        gc.collect()                     # 触发Python垃圾回收
        self._initialized = False
        # 绿色输出：模型已卸载
        print(f"{Colors.GREEN}[{self.module_id}] 模型已卸载{Colors.RESET}")
