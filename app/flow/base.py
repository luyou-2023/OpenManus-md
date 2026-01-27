from abc import ABC, abstractmethod  # 抽象基类和抽象方法装饰器
from typing import Dict, List, Optional, Union  # 类型提示

from pydantic import BaseModel  # Pydantic数据验证库

from app.agent.base import BaseAgent  # 代理基类


class BaseFlow(BaseModel, ABC):
    """流程基类：支持多代理的执行流程

    定义了多代理流程的基础结构，包括代理管理、主代理选择等功能。
    子类需要实现execute方法来定义具体的执行逻辑。
    """

    agents: Dict[str, BaseAgent]  # 代理字典，键为代理键名，值为代理对象
    tools: Optional[List] = None  # 工具列表，可选，用于流程级别的工具
    primary_agent_key: Optional[str] = None  # 主代理键名，可选，用于标识主要执行的代理

    class Config:
        arbitrary_types_allowed = True  # 允许任意类型（用于BaseAgent）

    def __init__(
        self, agents: Union[BaseAgent, List[BaseAgent], Dict[str, BaseAgent]], **data
    ):
        """初始化流程对象

        支持多种方式提供代理：
        1. 单个代理对象 -> 转换为{"default": agent}
        2. 代理列表 -> 转换为{"agent_0": agent0, "agent_1": agent1, ...}
        3. 代理字典 -> 直接使用

        Args:
            agents: 代理对象、代理列表或代理字典
            **data: 其他数据（如primary_agent_key）
        """
        # 处理不同的代理提供方式
        if isinstance(agents, BaseAgent):  # 如果是单个代理对象
            agents_dict = {"default": agents}  # 转换为字典，键为"default"
        elif isinstance(agents, list):  # 如果是代理列表
            agents_dict = {f"agent_{i}": agent for i, agent in enumerate(agents)}  # 转换为字典，键为"agent_0", "agent_1"等
        else:  # 如果已经是字典
            agents_dict = agents  # 直接使用

        # 如果未指定主代理，使用第一个代理
        primary_key = data.get("primary_agent_key")  # 从data中获取主代理键名
        if not primary_key and agents_dict:  # 如果未指定主代理键名且代理字典不为空
            primary_key = next(iter(agents_dict))  # 获取第一个键名
            data["primary_agent_key"] = primary_key  # 设置主代理键名

        # 设置代理字典
        data["agents"] = agents_dict  # 将处理后的代理字典添加到data中

        # 使用BaseModel的init进行初始化
        super().__init__(**data)  # 调用父类构造函数

    @property
    def primary_agent(self) -> Optional[BaseAgent]:
        """获取流程的主代理

        Returns:
            Optional[BaseAgent]: 主代理对象，如果不存在则返回None
        """
        return self.agents.get(self.primary_agent_key)  # 从代理字典中获取主代理

    def get_agent(self, key: str) -> Optional[BaseAgent]:
        """根据键名获取特定代理

        Args:
            key: 代理键名

        Returns:
            Optional[BaseAgent]: 代理对象，如果不存在则返回None
        """
        return self.agents.get(key)  # 从代理字典中获取代理

    def add_agent(self, key: str, agent: BaseAgent) -> None:
        """向流程中添加新代理

        Args:
            key: 代理键名
            agent: 代理对象
        """
        self.agents[key] = agent  # 将代理添加到代理字典

    @abstractmethod
    async def execute(self, input_text: str) -> str:
        """执行流程：使用给定输入执行流程

        抽象方法，必须由子类实现以定义具体的执行逻辑。

        Args:
            input_text: 输入文本

        Returns:
            str: 执行结果摘要
        """
