"""工具集合类：用于管理多个工具"""
from typing import Any, Dict, List  # 类型提示

from app.exceptions import ToolError  # 工具错误异常
from app.logger import logger  # 日志记录器
from app.tool.base import BaseTool, ToolFailure, ToolResult  # 工具基类和结果类


class ToolCollection:
    """工具集合类

    用于管理多个工具，提供工具的注册、查找、执行等功能。
    支持通过名称快速查找工具，并批量执行工具。
    """

    class Config:
        arbitrary_types_allowed = True  # 允许任意类型（用于BaseTool）

    def __init__(self, *tools: BaseTool):
        """初始化工具集合

        Args:
            *tools: 可变数量的工具对象
        """
        self.tools = tools  # 工具元组，保存所有工具
        self.tool_map = {tool.name: tool for tool in tools}  # 工具字典，键为工具名称，值为工具对象，用于快速查找

    def __iter__(self):
        """迭代器：支持遍历工具集合

        Returns:
            iterator: 工具迭代器
        """
        return iter(self.tools)  # 返回工具的迭代器

    def to_params(self) -> List[Dict[str, Any]]:
        """将工具集合转换为LLM函数调用参数列表

        Returns:
            List[Dict[str, Any]]: 工具参数列表，每个元素是一个工具的LLM函数调用格式
        """
        return [tool.to_param() for tool in self.tools]  # 遍历所有工具并转换为参数格式

    async def execute(
        self, *, name: str, tool_input: Dict[str, Any] = None
    ) -> ToolResult:
        """执行指定名称的工具

        Args:
            name: 工具名称
            tool_input: 工具输入参数字典，默认为None（空字典）

        Returns:
            ToolResult: 工具执行结果，如果工具不存在或执行失败则返回ToolFailure
        """
        tool = self.tool_map.get(name)  # 从工具字典中查找工具
        if not tool:  # 如果工具不存在
            return ToolFailure(error=f"Tool {name} is invalid")  # 返回工具无效错误
        try:
            result = await tool(**tool_input)  # 调用工具执行方法，传入参数
            return result  # 返回执行结果
        except ToolError as e:  # 捕获工具错误异常
            return ToolFailure(error=e.message)  # 返回工具错误结果

    async def execute_all(self) -> List[ToolResult]:
        """顺序执行集合中的所有工具

        遍历所有工具并依次执行，不传入参数。

        Returns:
            List[ToolResult]: 所有工具的执行结果列表
        """
        results = []  # 初始化结果列表
        for tool in self.tools:  # 遍历所有工具
            try:
                result = await tool()  # 执行工具（不传入参数）
                results.append(result)  # 将结果添加到列表
            except ToolError as e:  # 捕获工具错误异常
                results.append(ToolFailure(error=e.message))  # 添加错误结果到列表
        return results  # 返回所有结果

    def get_tool(self, name: str) -> BaseTool:
        """根据名称获取工具对象

        Args:
            name: 工具名称

        Returns:
            BaseTool: 工具对象，如果不存在则返回None
        """
        return self.tool_map.get(name)  # 从工具字典中获取工具

    def add_tool(self, tool: BaseTool):
        """向集合中添加单个工具

        如果工具名称已存在，会跳过并记录警告日志。

        Args:
            tool: 要添加的工具对象

        Returns:
            ToolCollection: 返回自身以支持链式调用
        """
        if tool.name in self.tool_map:  # 如果工具名称已存在
            logger.warning(f"Tool {tool.name} already exists in collection, skipping")  # 记录警告日志
            return self  # 返回自身，不添加工具

        self.tools += (tool,)  # 将工具添加到工具元组
        self.tool_map[tool.name] = tool  # 将工具添加到工具字典
        return self  # 返回自身以支持链式调用

    def add_tools(self, *tools: BaseTool):
        """向集合中添加多个工具

        如果任何工具存在名称冲突，会跳过并记录警告日志。

        Args:
            *tools: 可变数量的工具对象

        Returns:
            ToolCollection: 返回自身以支持链式调用
        """
        for tool in tools:  # 遍历所有要添加的工具
            self.add_tool(tool)  # 调用add_tool方法添加每个工具
        return self  # 返回自身以支持链式调用
