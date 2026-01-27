from pydantic import Field  # Pydantic字段定义

from app.agent.toolcall import ToolCallAgent  # 工具调用代理基类
from app.config import config  # 全局配置
from app.prompt.visualization import NEXT_STEP_PROMPT, SYSTEM_PROMPT  # 数据可视化代理的提示词
from app.tool import Terminate, ToolCollection  # 终止工具、工具集合
from app.tool.chart_visualization.chart_prepare import VisualizationPrepare  # 图表准备工具
from app.tool.chart_visualization.data_visualization import DataVisualization  # 数据可视化工具
from app.tool.chart_visualization.python_execute import NormalPythonExecute  # 普通Python执行工具


class DataAnalysis(ToolCallAgent):
    """数据分析代理类

    使用规划来解决各种数据分析任务的代理。

    该代理扩展了ToolCallAgent，提供了一套完整的工具和能力，
    包括数据分析、图表可视化、数据报告。
    """

    name: str = "Data_Analysis"  # 代理名称
    description: str = "An analytical agent that utilizes python and data visualization tools to solve diverse data analysis tasks"  # 代理描述

    system_prompt: str = SYSTEM_PROMPT.format(directory=config.workspace_root)  # 系统提示词，格式化工作目录
    next_step_prompt: str = NEXT_STEP_PROMPT  # 下一步提示词

    max_observe: int = 15000  # 最大观察长度
    max_steps: int = 20  # 最大步骤数

    # 向工具集合添加通用工具
    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(
            NormalPythonExecute(),  # 普通Python执行工具
            VisualizationPrepare(),  # 可视化准备工具
            DataVisualization(),  # 数据可视化工具
            Terminate(),  # 终止工具
        )
    )
