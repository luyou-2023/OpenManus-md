from enum import Enum  # 枚举类型
from typing import Dict, List, Union  # 类型提示

from app.agent.base import BaseAgent  # 代理基类
from app.flow.base import BaseFlow  # 流程基类
from app.flow.planning import PlanningFlow  # 规划流程类


class FlowType(str, Enum):
    """流程类型枚举类

    定义了系统中支持的流程类型
    """
    PLANNING = "planning"  # 规划流程类型


class FlowFactory:
    """流程工厂类

    用于创建不同类型的流程，支持多代理。
    使用工厂模式，根据流程类型创建相应的流程实例。
    """

    @staticmethod
    def create_flow(
        flow_type: FlowType,
        agents: Union[BaseAgent, List[BaseAgent], Dict[str, BaseAgent]],
        **kwargs,
    ) -> BaseFlow:
        """创建流程实例

        根据流程类型创建相应的流程实例。

        Args:
            flow_type: 流程类型枚举值
            agents: 代理对象、代理列表或代理字典
            **kwargs: 其他参数，传递给流程构造函数

        Returns:
            BaseFlow: 流程实例

        Raises:
            ValueError: 如果流程类型未知
        """
        flows = {
            FlowType.PLANNING: PlanningFlow,  # 规划流程类型映射到PlanningFlow类
        }  # 流程类型到流程类的映射字典

        flow_class = flows.get(flow_type)  # 根据流程类型获取流程类
        if not flow_class:  # 如果流程类不存在
            raise ValueError(f"Unknown flow type: {flow_type}")  # 抛出值错误

        return flow_class(agents, **kwargs)  # 创建并返回流程实例
