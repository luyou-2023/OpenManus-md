from typing import Dict, List, Optional  # 类型提示

from pydantic import Field, model_validator  # Pydantic字段定义和模型验证器

from app.agent.browser import BrowserContextHelper  # 浏览器上下文辅助类
from app.agent.toolcall import ToolCallAgent  # 工具调用代理基类
from app.config import config  # 配置单例
from app.logger import logger  # 日志记录器
from app.prompt.manus import NEXT_STEP_PROMPT, SYSTEM_PROMPT  # Manus代理的提示词模板
from app.tool import Terminate, ToolCollection  # 工具类和工具集合
from app.tool.ask_human import AskHuman  # 人工交互工具
from app.tool.browser_use_tool import BrowserUseTool  # 浏览器使用工具
from app.tool.mcp import MCPClients, MCPClientTool  # MCP客户端和工具
from app.tool.python_execute import PythonExecute  # Python执行工具
from app.tool.str_replace_editor import StrReplaceEditor  # 字符串替换编辑器工具


class Manus(ToolCallAgent):
    """Manus通用代理类

    一个多功能的通用代理，支持本地工具和MCP（Model Context Protocol）工具。
    继承自ToolCallAgent，集成了多种通用工具，包括Python执行、浏览器自动化、文件编辑等。
    """

    name: str = "Manus"  # 代理名称，固定为"Manus"
    description: str = "A versatile agent that can solve various tasks using multiple tools including MCP-based tools"  # 代理描述

    system_prompt: str = SYSTEM_PROMPT.format(directory=config.workspace_root)  # 系统提示词，格式化工作空间目录路径
    next_step_prompt: str = NEXT_STEP_PROMPT  # 下一步提示词

    max_observe: int = 10000  # 最大观察长度，用于限制工具输出长度，默认10000字符
    max_steps: int = 20  # 最大步数，默认20步

    # MCP客户端，用于远程工具访问
    mcp_clients: MCPClients = Field(default_factory=MCPClients)  # MCP客户端集合，默认创建新实例

    # 添加通用工具到工具集合
    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(  # 默认工具集合工厂函数
            PythonExecute(),  # Python代码执行工具
            BrowserUseTool(),  # 浏览器自动化工具
            StrReplaceEditor(),  # 字符串替换编辑器工具
            AskHuman(),  # 人工交互工具
            Terminate(),  # 终止工具
        )
    )  # 可用工具集合，包含所有通用工具

    special_tool_names: list[str] = Field(default_factory=lambda: [Terminate().name])  # 特殊工具名称列表，默认包含终止工具
    browser_context_helper: Optional[BrowserContextHelper] = None  # 浏览器上下文辅助对象，可选

    # 跟踪已连接的MCP服务器
    connected_servers: Dict[str, str] = Field(
        default_factory=dict
    )  # server_id -> url/command  # 已连接服务器字典，键为服务器ID，值为URL或命令
    _initialized: bool = False  # 初始化标志，用于跟踪MCP服务器是否已初始化

    @model_validator(mode="after")
    def initialize_helper(self) -> "Manus":
        """同步初始化基础组件

        在Pydantic模型验证后调用，用于初始化浏览器上下文辅助对象

        Returns:
            Manus: 初始化后的代理实例
        """
        self.browser_context_helper = BrowserContextHelper(self)  # 创建浏览器上下文辅助对象
        return self  # 返回自身以支持链式调用

    @classmethod
    async def create(cls, **kwargs) -> "Manus":
        """工厂方法：创建并正确初始化Manus实例

        这是推荐的创建Manus实例的方式，因为它会异步初始化MCP服务器连接。

        Args:
            **kwargs: 传递给构造函数的参数

        Returns:
            Manus: 完全初始化的Manus实例
        """
        instance = cls(**kwargs)  # 创建实例
        await instance.initialize_mcp_servers()  # 异步初始化MCP服务器
        instance._initialized = True  # 标记为已初始化
        return instance  # 返回实例

    async def initialize_mcp_servers(self) -> None:
        """初始化到配置的MCP服务器的连接

        遍历配置中的所有MCP服务器，根据连接类型（SSE或stdio）建立连接。
        如果连接失败，会记录错误但不会中断其他服务器的连接。
        """
        for server_id, server_config in config.mcp_config.servers.items():  # 遍历所有MCP服务器配置
            try:
                if server_config.type == "sse":  # 如果连接类型为SSE（Server-Sent Events）
                    if server_config.url:  # 如果提供了URL
                        await self.connect_mcp_server(server_config.url, server_id)  # 连接到SSE服务器
                        logger.info(
                            f"Connected to MCP server {server_id} at {server_config.url}"  # 记录连接成功日志
                        )
                elif server_config.type == "stdio":  # 如果连接类型为stdio（标准输入输出）
                    if server_config.command:  # 如果提供了命令
                        await self.connect_mcp_server(  # 连接到stdio服务器
                            server_config.command,  # 命令
                            server_id,  # 服务器ID
                            use_stdio=True,  # 使用stdio模式
                            stdio_args=server_config.args,  # stdio参数
                        )
                        logger.info(
                            f"Connected to MCP server {server_id} using command {server_config.command}"  # 记录连接成功日志
                        )
            except Exception as e:  # 捕获连接过程中的异常
                logger.error(f"Failed to connect to MCP server {server_id}: {e}")  # 记录错误日志，但不中断其他服务器连接

    async def connect_mcp_server(
        self,
        server_url: str,
        server_id: str = "",
        use_stdio: bool = False,
        stdio_args: List[str] = None,
    ) -> None:
        """连接到MCP服务器并添加其工具

        Args:
            server_url: 服务器URL或命令
            server_id: 服务器ID，默认为空字符串
            use_stdio: 是否使用stdio连接，默认False（使用SSE）
            stdio_args: stdio连接的参数列表，可选
        """
        if use_stdio:  # 如果使用stdio连接
            await self.mcp_clients.connect_stdio(  # 通过stdio连接
                server_url, stdio_args or [], server_id  # 传入URL/命令、参数列表和服务器ID
            )
            self.connected_servers[server_id or server_url] = server_url  # 记录已连接服务器
        else:  # 如果使用SSE连接
            await self.mcp_clients.connect_sse(server_url, server_id)  # 通过SSE连接
            self.connected_servers[server_id or server_url] = server_url  # 记录已连接服务器

        # 更新可用工具，只添加来自此服务器的新工具
        new_tools = [
            tool for tool in self.mcp_clients.tools if tool.server_id == server_id  # 筛选出属于此服务器的工具
        ]
        self.available_tools.add_tools(*new_tools)  # 将新工具添加到可用工具集合

    async def disconnect_mcp_server(self, server_id: str = "") -> None:
        """断开MCP服务器连接并移除其工具

        Args:
            server_id: 要断开的服务器ID，如果为空字符串则断开所有服务器
        """
        await self.mcp_clients.disconnect(server_id)  # 断开MCP客户端连接
        if server_id:  # 如果指定了服务器ID
            self.connected_servers.pop(server_id, None)  # 从已连接服务器字典中移除
        else:  # 如果没有指定服务器ID
            self.connected_servers.clear()  # 清空所有已连接服务器记录

        # 重建可用工具集合，排除已断开服务器的工具
        base_tools = [
            tool
            for tool in self.available_tools.tools
            if not isinstance(tool, MCPClientTool)  # 保留非MCP工具
        ]
        self.available_tools = ToolCollection(*base_tools)  # 创建新的工具集合，只包含基础工具
        self.available_tools.add_tools(*self.mcp_clients.tools)  # 添加剩余的MCP工具

    async def cleanup(self):
        """清理Manus代理资源

        清理浏览器上下文和MCP服务器连接。
        只有在已初始化的情况下才会断开MCP服务器。
        """
        if self.browser_context_helper:  # 如果存在浏览器上下文辅助对象
            await self.browser_context_helper.cleanup_browser()  # 清理浏览器资源
        # 只有在已初始化的情况下才断开所有MCP服务器
        if self._initialized:  # 如果已初始化
            await self.disconnect_mcp_server()  # 断开所有MCP服务器
            self._initialized = False  # 重置初始化标志

    async def think(self) -> bool:
        """思考阶段：处理当前状态并使用适当的上下文决定下一步行动

        重写父类的think方法，添加了以下功能：
        1. 延迟初始化MCP服务器（如果未初始化）
        2. 检测浏览器工具使用情况
        3. 如果使用浏览器工具，动态调整提示词以包含浏览器上下文

        Returns:
            bool: 如果需要执行行动返回True，否则返回False
        """
        if not self._initialized:  # 如果未初始化
            await self.initialize_mcp_servers()  # 初始化MCP服务器
            self._initialized = True  # 标记为已初始化

        original_prompt = self.next_step_prompt  # 保存原始提示词
        recent_messages = self.memory.messages[-3:] if self.memory.messages else []  # 获取最近3条消息
        browser_in_use = any(  # 检查是否在使用浏览器工具
            tc.function.name == BrowserUseTool().name  # 检查工具调用名称是否为浏览器工具
            for msg in recent_messages  # 遍历最近的消息
            if msg.tool_calls  # 如果消息包含工具调用
            for tc in msg.tool_calls  # 遍历工具调用
        )

        if browser_in_use:  # 如果正在使用浏览器工具
            self.next_step_prompt = (
                await self.browser_context_helper.format_next_step_prompt()  # 使用浏览器上下文格式化提示词
            )

        result = await super().think()  # 调用父类的think方法

        # 恢复原始提示词
        self.next_step_prompt = original_prompt  # 恢复原始提示词，避免影响后续步骤

        return result  # 返回思考结果
