from typing import List  # 类型提示

from pydantic import Field  # Pydantic字段定义

from app.agent.toolcall import ToolCallAgent  # 工具调用代理基类
from app.prompt.swe import SYSTEM_PROMPT  # SWE代理的系统提示词
from app.tool import Bash, StrReplaceEditor, Terminate, ToolCollection  # Bash工具、字符串替换编辑器、终止工具、工具集合


class SWEAgent(ToolCallAgent):
    """SWE代理类

    实现SWEAgent范式，用于执行代码和自然对话的代理。
    SWE (Software Engineering) Agent是一个自主的AI程序员，
    直接与计算机交互来解决问题。
    """

    name: str = "swe"  # 代理名称
    description: str = "an autonomous AI programmer that interacts directly with the computer to solve tasks."  # 代理描述

    system_prompt: str = SYSTEM_PROMPT  # 系统提示词
    next_step_prompt: str = ""  # 下一步提示词（空字符串）

    available_tools: ToolCollection = ToolCollection(
        Bash(),  # Bash命令执行工具
        StrReplaceEditor(),  # 字符串替换编辑器工具
        Terminate()  # 终止工具
    )
    special_tool_names: List[str] = Field(default_factory=lambda: [Terminate().name])  # 特殊工具名称列表：终止工具

    max_steps: int = 20  # 最大步骤数
