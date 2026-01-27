from typing import Any, Dict, List, Optional, Tuple  # 类型提示

from pydantic import Field  # Pydantic字段定义

from app.agent.toolcall import ToolCallAgent  # 工具调用代理基类
from app.logger import logger  # 日志记录器
from app.prompt.mcp import MULTIMEDIA_RESPONSE_PROMPT, NEXT_STEP_PROMPT, SYSTEM_PROMPT  # MCP代理的提示词
from app.schema import AgentState, Message  # 代理状态枚举和消息模型
from app.tool.base import ToolResult  # 工具结果基类
from app.tool.mcp import MCPClients  # MCP客户端工具集合


class MCPAgent(ToolCallAgent):
    """MCP代理类

    用于与MCP（Model Context Protocol）服务器交互的代理。

    该代理使用SSE或stdio传输连接到MCP服务器，
    并通过代理的工具接口使服务器的工具可用。
    """

    name: str = "mcp_agent"  # 代理名称
    description: str = "An agent that connects to an MCP server and uses its tools."  # 代理描述

    system_prompt: str = SYSTEM_PROMPT  # 系统提示词
    next_step_prompt: str = NEXT_STEP_PROMPT  # 下一步提示词

    # 初始化MCP工具集合
    mcp_clients: MCPClients = Field(default_factory=MCPClients)  # MCP客户端工具集合
    available_tools: MCPClients = None  # 可用工具，将在initialize()中设置

    max_steps: int = 20  # 最大步骤数
    connection_type: str = "stdio"  # 连接类型："stdio"或"sse"

    # 跟踪工具Schema以检测变化
    tool_schemas: Dict[str, Dict[str, Any]] = Field(default_factory=dict)  # 工具Schema字典
    _refresh_tools_interval: int = 5  # 每N步刷新一次工具

    # 应该触发终止的特殊工具名称
    special_tool_names: List[str] = Field(default_factory=lambda: ["terminate"])  # 特殊工具名称列表：终止工具

    async def initialize(
        self,
        connection_type: Optional[str] = None,
        server_url: Optional[str] = None,
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
    ) -> None:
        """初始化MCP连接

        Args:
            connection_type: 要使用的连接类型（"stdio"或"sse"）
            server_url: MCP服务器的URL（用于SSE连接）
            command: 要运行的命令（用于stdio连接）
            args: 命令的参数（用于stdio连接）

        Raises:
            ValueError: 如果连接类型不支持或缺少必需参数
        """
        if connection_type:  # 如果提供了连接类型
            self.connection_type = connection_type  # 设置连接类型

        # 根据连接类型连接到MCP服务器
        if self.connection_type == "sse":  # 如果是SSE连接
            if not server_url:  # 如果未提供服务器URL
                raise ValueError("Server URL is required for SSE connection")  # 抛出值错误
            await self.mcp_clients.connect_sse(server_url=server_url)  # 连接SSE服务器
        elif self.connection_type == "stdio":  # 如果是stdio连接
            if not command:  # 如果未提供命令
                raise ValueError("Command is required for stdio connection")  # 抛出值错误
            await self.mcp_clients.connect_stdio(command=command, args=args or [])  # 连接stdio服务器
        else:  # 如果连接类型不支持
            raise ValueError(f"Unsupported connection type: {self.connection_type}")  # 抛出值错误

        # 将available_tools设置为我们的MCP实例
        self.available_tools = self.mcp_clients  # 设置可用工具

        # 存储初始工具Schema
        await self._refresh_tools()  # 刷新工具列表

        # 添加关于可用工具的系统消息
        tool_names = list(self.mcp_clients.tool_map.keys())  # 获取所有工具名称
        tools_info = ", ".join(tool_names)  # 将工具名称连接为字符串

        # 添加系统提示和可用工具信息
        self.memory.add_message(
            Message.system_message(
                f"{self.system_prompt}\n\nAvailable MCP tools: {tools_info}"  # 格式化系统消息
            )
        )

    async def _refresh_tools(self) -> Tuple[List[str], List[str]]:
        """从MCP服务器刷新可用工具列表

        Returns:
            Tuple[List[str], List[str]]: (添加的工具列表, 移除的工具列表)元组
        """
        if not self.mcp_clients.sessions:  # 如果没有MCP会话
            return [], []  # 返回空列表

        # 直接从服务器获取当前工具Schema
        response = await self.mcp_clients.list_tools()  # 列出所有工具
        current_tools = {tool.name: tool.inputSchema for tool in response.tools}  # 构建工具名称到Schema的映射

        # 确定添加、移除和更改的工具
        current_names = set(current_tools.keys())  # 当前工具名称集合
        previous_names = set(self.tool_schemas.keys())  # 之前的工具名称集合

        added_tools = list(current_names - previous_names)  # 添加的工具（当前有但之前没有）
        removed_tools = list(previous_names - current_names)  # 移除的工具（之前有但当前没有）

        # 检查现有工具的Schema变化
        changed_tools = []  # 更改的工具列表
        for name in current_names.intersection(previous_names):  # 遍历同时存在于当前和之前的工具
            if current_tools[name] != self.tool_schemas.get(name):  # 如果Schema不同
                changed_tools.append(name)  # 添加到更改列表

        # 更新存储的Schema
        self.tool_schemas = current_tools  # 更新工具Schema字典

        # 记录并通知变化
        if added_tools:  # 如果有添加的工具
            logger.info(f"Added MCP tools: {added_tools}")  # 记录信息
            self.memory.add_message(
                Message.system_message(f"New tools available: {', '.join(added_tools)}")  # 添加系统消息
            )
        if removed_tools:  # 如果有移除的工具
            logger.info(f"Removed MCP tools: {removed_tools}")  # 记录信息
            self.memory.add_message(
                Message.system_message(
                    f"Tools no longer available: {', '.join(removed_tools)}"  # 添加系统消息
                )
            )
        if changed_tools:  # 如果有更改的工具
            logger.info(f"Changed MCP tools: {changed_tools}")  # 记录信息

        return added_tools, removed_tools  # 返回添加和移除的工具列表

    async def think(self) -> bool:
        """处理当前状态并决定下一步操作

        Returns:
            bool: 是否需要继续执行
        """
        # 检查MCP会话和工具可用性
        if not self.mcp_clients.sessions or not self.mcp_clients.tool_map:  # 如果没有会话或工具映射
            logger.info("MCP service is no longer available, ending interaction")  # 记录信息
            self.state = AgentState.FINISHED  # 设置状态为完成
            return False  # 返回False，不再继续

        # 定期刷新工具
        if self.current_step % self._refresh_tools_interval == 0:  # 如果达到刷新间隔
            await self._refresh_tools()  # 刷新工具
            # 所有工具被移除表示服务器关闭
            if not self.mcp_clients.tool_map:  # 如果工具映射为空
                logger.info("MCP service has shut down, ending interaction")  # 记录信息
                self.state = AgentState.FINISHED  # 设置状态为完成
                return False  # 返回False，不再继续

        # 使用父类的think方法
        return await super().think()  # 调用父类方法

    async def _handle_special_tool(self, name: str, result: Any, **kwargs) -> None:
        """处理特殊工具执行和状态变化

        Args:
            name: 工具名称
            result: 工具执行结果
            **kwargs: 其他参数
        """
        # 首先使用父类处理器处理
        await super()._handle_special_tool(name, result, **kwargs)  # 调用父类方法

        # 处理多媒体响应
        if isinstance(result, ToolResult) and result.base64_image:  # 如果结果是ToolResult且包含base64图像
            self.memory.add_message(
                Message.system_message(
                    MULTIMEDIA_RESPONSE_PROMPT.format(tool_name=name)  # 格式化多媒体响应提示
                )
            )

    def _should_finish_execution(self, name: str, **kwargs) -> bool:
        """确定工具执行是否应该完成代理

        Args:
            name: 工具名称
            **kwargs: 其他参数

        Returns:
            bool: 如果应该完成则返回True
        """
        # 如果工具名称是'terminate'则终止
        return name.lower() == "terminate"  # 检查是否为终止工具

    async def cleanup(self) -> None:
        """完成时清理MCP连接"""
        if self.mcp_clients.sessions:  # 如果有MCP会话
            await self.mcp_clients.disconnect()  # 断开连接
            logger.info("MCP connection closed")  # 记录信息

    async def run(self, request: Optional[str] = None) -> str:
        """运行代理，完成后清理

        Args:
            request: 请求文本，可选

        Returns:
            str: 执行结果
        """
        try:
            result = await super().run(request)  # 调用父类run方法
            return result  # 返回结果
        finally:
            # 确保即使有错误也会执行清理
            await self.cleanup()  # 清理资源
