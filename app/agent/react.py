from abc import ABC, abstractmethod  # 抽象基类和抽象方法装饰器
from typing import Optional  # 类型提示

from pydantic import Field  # Pydantic字段定义

from app.agent.base import BaseAgent  # 代理基类
from app.llm import LLM  # LLM客户端
from app.schema import AgentState, Memory  # 代理状态和内存模型


class ReActAgent(BaseAgent, ABC):
    """ReAct代理基类

    实现ReAct（Reasoning + Acting）模式，将代理行为分为思考（think）和行动（act）两个阶段。
    这是模板方法模式的实现，定义了执行框架，子类需要实现think()和act()方法。
    """
    name: str  # 代理名称，必填字段
    description: Optional[str] = None  # 代理描述，可选

    system_prompt: Optional[str] = None  # 系统提示词，可选
    next_step_prompt: Optional[str] = None  # 下一步提示词，可选

    llm: Optional[LLM] = Field(default_factory=LLM)  # LLM实例，默认创建新实例
    memory: Memory = Field(default_factory=Memory)  # 内存实例，默认创建新实例
    state: AgentState = AgentState.IDLE  # 代理状态，默认为IDLE

    max_steps: int = 10  # 最大步数，默认10步
    current_step: int = 0  # 当前步数，默认0

    @abstractmethod
    async def think(self) -> bool:
        """思考阶段：处理当前状态并决定下一步行动

        抽象方法，必须由子类实现。子类应该在此方法中：
        1. 分析当前状态和内存
        2. 决定需要执行什么行动
        3. 返回是否需要执行行动

        Returns:
            bool: 如果需要执行行动返回True，否则返回False
        """

    @abstractmethod
    async def act(self) -> str:
        """行动阶段：执行决定的行动

        抽象方法，必须由子类实现。子类应该在此方法中：
        1. 执行之前思考阶段决定的行动
        2. 处理行动结果
        3. 返回行动结果摘要

        Returns:
            str: 行动结果的摘要字符串
        """

    async def step(self) -> str:
        """执行单步：思考然后行动

        这是模板方法模式的实现，定义了ReAct模式的执行流程：
        1. 先调用think()进行思考
        2. 如果需要行动，则调用act()执行行动
        3. 返回执行结果

        Returns:
            str: 步骤执行结果的摘要
        """
        should_act = await self.think()  # 思考阶段，获取是否需要行动
        if not should_act:  # 如果不需要行动
            return "Thinking complete - no action needed"  # 返回思考完成消息
        return await self.act()  # 如果需要行动，执行行动并返回结果
