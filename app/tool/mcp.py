from contextlib import AsyncExitStack  # 异步退出栈，用于管理异步上下文
from typing import Dict, List, Optional  # 类型提示

from mcp import ClientSession, StdioServerParameters  # MCP客户端会话和stdio服务器参数
from mcp.client.sse import sse_client  # SSE客户端
from mcp.client.stdio import stdio_client  # stdio客户端
from mcp.types import ListToolsResult, TextContent  # MCP类型定义

from app.logger import logger  # 日志记录器
from app.tool.base import BaseTool, ToolResult  # 工具基类和结果类
from app.tool.tool_collection import ToolCollection  # 工具集合类


class MCPClientTool(BaseTool):
    """MCP客户端工具类

    表示一个工具代理，可以从客户端调用MCP服务器上的工具。
    封装了与MCP服务器的通信逻辑。
    """

    session: Optional[ClientSession] = None  # MCP客户端会话，可选
    server_id: str = ""  # 服务器标识符
    original_name: str = ""  # 原始工具名称（在服务器上的名称）

    async def execute(self, **kwargs) -> ToolResult:
        """通过向MCP服务器发起远程调用来执行工具

        Args:
            **kwargs: 工具参数

        Returns:
            ToolResult: 工具执行结果
        """
        if not self.session:  # 如果未连接到MCP服务器
            return ToolResult(error="Not connected to MCP server")  # 返回错误结果

        try:
            logger.info(f"Executing tool: {self.original_name}")  # 记录执行日志
            result = await self.session.call_tool(self.original_name, kwargs)  # 调用MCP服务器上的工具
            content_str = ", ".join(
                item.text for item in result.content if isinstance(item, TextContent)  # 提取文本内容
            )
            return ToolResult(output=content_str or "No output returned.")  # 返回结果
        except Exception as e:  # 捕获任何异常
            return ToolResult(error=f"Error executing tool: {str(e)}")  # 返回错误结果


class MCPClients(ToolCollection):
    """MCP客户端工具集合类

    连接到多个MCP服务器并通过Model Context Protocol管理可用工具的集合。
    支持SSE和stdio两种传输方式。
    """

    sessions: Dict[str, ClientSession] = {}  # 服务器ID到客户端会话的映射
    exit_stacks: Dict[str, AsyncExitStack] = {}  # 服务器ID到退出栈的映射，用于资源清理
    description: str = "MCP client tools for server interaction"  # 描述文本

    def __init__(self):
        """初始化MCP客户端工具集合"""
        super().__init__()  # 使用空工具列表初始化父类
        self.name = "mcp"  # 保持名称以向后兼容

    async def connect_sse(self, server_url: str, server_id: str = "") -> None:
        """使用SSE传输连接到MCP服务器

        Args:
            server_url: 服务器URL
            server_id: 服务器标识符，如果不提供则使用URL

        Raises:
            ValueError: 如果服务器URL为空
        """
        if not server_url:  # 如果服务器URL为空
            raise ValueError("Server URL is required.")  # 抛出值错误

        server_id = server_id or server_url  # 使用提供的server_id或URL

        # 在新连接之前始终确保清理旧连接
        if server_id in self.sessions:  # 如果服务器已连接
            await self.disconnect(server_id)  # 断开连接

        exit_stack = AsyncExitStack()  # 创建异步退出栈
        self.exit_stacks[server_id] = exit_stack  # 保存退出栈

        streams_context = sse_client(url=server_url)  # 创建SSE客户端上下文
        streams = await exit_stack.enter_async_context(streams_context)  # 进入SSE上下文
        session = await exit_stack.enter_async_context(ClientSession(*streams))  # 创建客户端会话
        self.sessions[server_id] = session  # 保存会话

        await self._initialize_and_list_tools(server_id)  # 初始化并列出工具

    async def connect_stdio(
        self, command: str, args: List[str], server_id: str = ""
    ) -> None:
        """使用stdio传输连接到MCP服务器

        Args:
            command: 服务器命令
            args: 命令参数列表
            server_id: 服务器标识符，如果不提供则使用command

        Raises:
            ValueError: 如果服务器命令为空
        """
        if not command:  # 如果命令为空
            raise ValueError("Server command is required.")  # 抛出值错误

        server_id = server_id or command  # 使用提供的server_id或command

        # 在新连接之前始终确保清理旧连接
        if server_id in self.sessions:  # 如果服务器已连接
            await self.disconnect(server_id)  # 断开连接

        exit_stack = AsyncExitStack()  # 创建异步退出栈
        self.exit_stacks[server_id] = exit_stack  # 保存退出栈

        server_params = StdioServerParameters(command=command, args=args)  # 创建stdio服务器参数
        stdio_transport = await exit_stack.enter_async_context(
            stdio_client(server_params)  # 创建stdio客户端
        )
        read, write = stdio_transport  # 获取读写流
        session = await exit_stack.enter_async_context(ClientSession(read, write))  # 创建客户端会话
        self.sessions[server_id] = session  # 保存会话

        await self._initialize_and_list_tools(server_id)  # 初始化并列出工具

    async def _initialize_and_list_tools(self, server_id: str) -> None:
        """初始化会话并填充工具映射

        Args:
            server_id: 服务器标识符

        Raises:
            RuntimeError: 如果会话未初始化
        """
        session = self.sessions.get(server_id)  # 获取会话
        if not session:  # 如果会话不存在
            raise RuntimeError(f"Session not initialized for server {server_id}")  # 抛出运行时错误

        await session.initialize()  # 初始化会话
        response = await session.list_tools()  # 列出服务器上的工具

        # 为每个服务器工具创建适当的工具对象
        for tool in response.tools:  # 遍历所有工具
            original_name = tool.name  # 获取原始工具名称
            tool_name = f"mcp_{server_id}_{original_name}"  # 构建唯一工具名称
            tool_name = self._sanitize_tool_name(tool_name)  # 清理工具名称

            server_tool = MCPClientTool(  # 创建MCP客户端工具实例
                name=tool_name,  # 工具名称
                description=tool.description,  # 工具描述
                parameters=tool.inputSchema,  # 工具参数Schema
                session=session,  # 客户端会话
                server_id=server_id,  # 服务器ID
                original_name=original_name,  # 原始名称
            )
            self.tool_map[tool_name] = server_tool  # 添加到工具映射

        # 更新工具元组
        self.tools = tuple(self.tool_map.values())  # 更新工具元组
        logger.info(
            f"Connected to server {server_id} with tools: {[tool.name for tool in response.tools]}"  # 记录连接日志
        )

    def _sanitize_tool_name(self, name: str) -> str:
        """Sanitize tool name to match MCPClientTool requirements."""
        import re

        # Replace invalid characters with underscores
        sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", name)

        # Remove consecutive underscores
        sanitized = re.sub(r"_+", "_", sanitized)

        # Remove leading/trailing underscores
        sanitized = sanitized.strip("_")

        # Truncate to 64 characters if needed
        if len(sanitized) > 64:
            sanitized = sanitized[:64]

        return sanitized

    async def list_tools(self) -> ListToolsResult:
        """List all available tools."""
        tools_result = ListToolsResult(tools=[])
        for session in self.sessions.values():
            response = await session.list_tools()
            tools_result.tools += response.tools
        return tools_result

    async def disconnect(self, server_id: str = "") -> None:
        """Disconnect from a specific MCP server or all servers if no server_id provided."""
        if server_id:
            if server_id in self.sessions:
                try:
                    exit_stack = self.exit_stacks.get(server_id)

                    # Close the exit stack which will handle session cleanup
                    if exit_stack:
                        try:
                            await exit_stack.aclose()
                        except RuntimeError as e:
                            if "cancel scope" in str(e).lower():
                                logger.warning(
                                    f"Cancel scope error during disconnect from {server_id}, continuing with cleanup: {e}"
                                )
                            else:
                                raise

                    # Clean up references
                    self.sessions.pop(server_id, None)
                    self.exit_stacks.pop(server_id, None)

                    # Remove tools associated with this server
                    self.tool_map = {
                        k: v
                        for k, v in self.tool_map.items()
                        if v.server_id != server_id
                    }
                    self.tools = tuple(self.tool_map.values())
                    logger.info(f"Disconnected from MCP server {server_id}")
                except Exception as e:
                    logger.error(f"Error disconnecting from server {server_id}: {e}")
        else:
            # Disconnect from all servers in a deterministic order
            for sid in sorted(list(self.sessions.keys())):
                await self.disconnect(sid)
            self.tool_map = {}
            self.tools = tuple()
            logger.info("Disconnected from all MCP servers")
