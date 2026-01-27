from typing import Dict, List, Optional  # 类型提示

from pydantic import Field, model_validator  # Pydantic字段和验证器

from app.agent.browser import BrowserContextHelper  # 浏览器上下文助手
from app.agent.toolcall import ToolCallAgent  # 工具调用代理基类
from app.config import config  # 全局配置
from app.daytona.sandbox import create_sandbox, delete_sandbox  # Daytona沙箱创建和删除函数
from app.daytona.tool_base import SandboxToolsBase  # 沙箱工具基类
from app.logger import logger  # 日志记录器
from app.prompt.manus import NEXT_STEP_PROMPT, SYSTEM_PROMPT  # Manus代理的提示词
from app.tool import Terminate, ToolCollection  # 终止工具、工具集合
from app.tool.ask_human import AskHuman  # 人工交互工具
from app.tool.mcp import MCPClients, MCPClientTool  # MCP客户端工具集合和工具类
from app.tool.sandbox.sb_browser_tool import SandboxBrowserTool  # 沙箱浏览器工具
from app.tool.sandbox.sb_files_tool import SandboxFilesTool  # 沙箱文件工具
from app.tool.sandbox.sb_shell_tool import SandboxShellTool  # 沙箱Shell工具
from app.tool.sandbox.sb_vision_tool import SandboxVisionTool  # 沙箱视觉工具


class SandboxManus(ToolCallAgent):
    """沙箱Manus代理类

    一个通用的多功能代理，支持本地工具和MCP工具。
    使用Daytona沙箱环境执行任务。
    """

    name: str = "SandboxManus"  # 代理名称
    description: str = "A versatile agent that can solve various tasks using multiple sandbox-tools including MCP-based tools"  # 代理描述

    system_prompt: str = SYSTEM_PROMPT.format(directory=config.workspace_root)  # 系统提示词，格式化工作目录
    next_step_prompt: str = NEXT_STEP_PROMPT  # 下一步提示词

    max_observe: int = 10000  # 最大观察长度
    max_steps: int = 20  # 最大步骤数

    # 用于远程工具访问的MCP客户端
    mcp_clients: MCPClients = Field(default_factory=MCPClients)  # MCP客户端工具集合

    # 向工具集合添加通用工具
    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(
            # PythonExecute(),  # Python执行工具（已注释）
            # BrowserUseTool(),  # 浏览器工具（已注释）
            # StrReplaceEditor(),  # 字符串替换编辑器（已注释）
            AskHuman(),  # 人工交互工具
            Terminate(),  # 终止工具
        )
    )

    special_tool_names: list[str] = Field(default_factory=lambda: [Terminate().name])  # 特殊工具名称列表：终止工具
    browser_context_helper: Optional[BrowserContextHelper] = None  # 浏览器上下文助手，可选

    # 跟踪已连接的MCP服务器
    connected_servers: Dict[str, str] = Field(
        default_factory=dict
    )  # server_id -> url/command，服务器ID到URL/命令的映射
    _initialized: bool = False  # 初始化标志
    sandbox_link: Optional[dict[str, dict[str, str]]] = Field(default_factory=dict)  # 沙箱链接字典，存储VNC和网站URL

    @model_validator(mode="after")
    def initialize_helper(self) -> "SandboxManus":
        """同步初始化基本组件

        Returns:
            SandboxManus: 自身实例
        """
        self.browser_context_helper = BrowserContextHelper(self)  # 创建浏览器上下文助手
        return self  # 返回自身

    @classmethod
    async def create(cls, **kwargs) -> "SandboxManus":
        """工厂方法：创建并正确初始化Manus实例

        Args:
            **kwargs: 传递给构造函数的参数

        Returns:
            SandboxManus: 初始化后的实例
        """
        instance = cls(**kwargs)  # 创建实例
        await instance.initialize_mcp_servers()  # 初始化MCP服务器连接
        await instance.initialize_sandbox_tools()  # 初始化沙箱工具
        instance._initialized = True  # 设置初始化标志
        return instance  # 返回实例

    async def initialize_sandbox_tools(
        self,
        password: str = config.daytona.VNC_password,
    ) -> None:
        """初始化沙箱工具

        创建Daytona沙箱并添加沙箱相关工具。

        Args:
            password: VNC密码，默认为配置中的密码

        Raises:
            ValueError: 如果密码未提供
            Exception: 如果初始化失败
        """
        try:
            # 创建新沙箱
            if password:  # 如果提供了密码
                sandbox = create_sandbox(password=password)  # 创建沙箱
                self.sandbox = sandbox  # 保存沙箱实例
            else:  # 如果未提供密码
                raise ValueError("password must be provided")  # 抛出值错误
            vnc_link = sandbox.get_preview_link(6080)  # 获取VNC预览链接（端口6080）
            website_link = sandbox.get_preview_link(8080)  # 获取网站预览链接（端口8080）
            vnc_url = vnc_link.url if hasattr(vnc_link, "url") else str(vnc_link)  # 提取VNC URL
            website_url = (
                website_link.url if hasattr(website_link, "url") else str(website_link)  # 提取网站URL
            )

            # 从创建的沙箱获取实际的sandbox_id
            actual_sandbox_id = sandbox.id if hasattr(sandbox, "id") else "new_sandbox"  # 获取沙箱ID
            if not self.sandbox_link:  # 如果sandbox_link未初始化
                self.sandbox_link = {}  # 初始化为空字典
            self.sandbox_link[actual_sandbox_id] = {
                "vnc": vnc_url,  # VNC URL
                "website": website_url,  # 网站URL
            }
            logger.info(f"VNC URL: {vnc_url}")  # 记录VNC URL
            logger.info(f"Website URL: {website_url}")  # 记录网站URL
            SandboxToolsBase._urls_printed = True  # 标记URL已打印
            sb_tools = [
                SandboxBrowserTool(sandbox),  # 沙箱浏览器工具
                SandboxFilesTool(sandbox),  # 沙箱文件工具
                SandboxShellTool(sandbox),  # 沙箱Shell工具
                SandboxVisionTool(sandbox),  # 沙箱视觉工具
            ]
            self.available_tools.add_tools(*sb_tools)  # 添加所有沙箱工具

        except Exception as e:  # 捕获任何异常
            logger.error(f"Error initializing sandbox tools: {e}")  # 记录错误
            raise  # 重新抛出异常

    async def initialize_mcp_servers(self) -> None:
        """初始化到配置的MCP服务器的连接

        遍历配置中的所有MCP服务器并建立连接。
        """
        for server_id, server_config in config.mcp_config.servers.items():  # 遍历所有MCP服务器配置
            try:
                if server_config.type == "sse":  # 如果是SSE类型
                    if server_config.url:  # 如果有URL
                        await self.connect_mcp_server(server_config.url, server_id)  # 连接SSE服务器
                        logger.info(
                            f"Connected to MCP server {server_id} at {server_config.url}"  # 记录连接信息
                        )
                elif server_config.type == "stdio":  # 如果是stdio类型
                    if server_config.command:  # 如果有命令
                        await self.connect_mcp_server(
                            server_config.command,  # 服务器命令
                            server_id,  # 服务器ID
                            use_stdio=True,  # 使用stdio
                            stdio_args=server_config.args,  # stdio参数
                        )
                        logger.info(
                            f"Connected to MCP server {server_id} using command {server_config.command}"  # 记录连接信息
                        )
            except Exception as e:  # 捕获任何异常
                logger.error(f"Failed to connect to MCP server {server_id}: {e}")  # 记录错误

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
            server_id: 服务器标识符，可选
            use_stdio: 是否使用stdio传输，默认为False（使用SSE）
            stdio_args: stdio参数列表，可选
        """
        if use_stdio:  # 如果使用stdio
            await self.mcp_clients.connect_stdio(
                server_url, stdio_args or [], server_id  # 连接stdio服务器
            )
            self.connected_servers[server_id or server_url] = server_url  # 记录连接的服务器
        else:  # 如果使用SSE
            await self.mcp_clients.connect_sse(server_url, server_id)  # 连接SSE服务器
            self.connected_servers[server_id or server_url] = server_url  # 记录连接的服务器

        # 仅使用来自此服务器的新工具更新可用工具
        new_tools = [
            tool for tool in self.mcp_clients.tools if tool.server_id == server_id  # 筛选出此服务器的工具
        ]
        self.available_tools.add_tools(*new_tools)  # 添加新工具

    async def disconnect_mcp_server(self, server_id: str = "") -> None:
        """断开MCP服务器连接并移除其工具

        Args:
            server_id: 服务器标识符，如果为空则断开所有服务器
        """
        await self.mcp_clients.disconnect(server_id)  # 断开MCP客户端连接
        if server_id:  # 如果指定了服务器ID
            self.connected_servers.pop(server_id, None)  # 从连接服务器字典中移除
        else:  # 如果未指定服务器ID
            self.connected_servers.clear()  # 清空所有连接服务器

        # 重建可用工具，不包含已断开服务器的工具
        base_tools = [
            tool
            for tool in self.available_tools.tools
            if not isinstance(tool, MCPClientTool)  # 筛选出非MCP客户端工具
        ]
        self.available_tools = ToolCollection(*base_tools)  # 创建新的工具集合
        self.available_tools.add_tools(*self.mcp_clients.tools)  # 添加剩余的MCP工具

    async def delete_sandbox(self, sandbox_id: str) -> None:
        """按ID删除沙箱

        Args:
            sandbox_id: 沙箱ID

        Raises:
            Exception: 如果删除失败
        """
        try:
            await delete_sandbox(sandbox_id)  # 删除沙箱
            logger.info(f"Sandbox {sandbox_id} deleted successfully")  # 记录成功信息
            if sandbox_id in self.sandbox_link:  # 如果沙箱链接存在
                del self.sandbox_link[sandbox_id]  # 删除沙箱链接
        except Exception as e:  # 捕获任何异常
            logger.error(f"Error deleting sandbox {sandbox_id}: {e}")  # 记录错误
            raise e  # 重新抛出异常

    async def cleanup(self):
        """清理Manus代理资源

        清理浏览器、MCP连接和沙箱。
        """
        if self.browser_context_helper:  # 如果有浏览器上下文助手
            await self.browser_context_helper.cleanup_browser()  # 清理浏览器
        # 只有在已初始化时才断开所有MCP服务器
        if self._initialized:  # 如果已初始化
            await self.disconnect_mcp_server()  # 断开MCP服务器
            await self.delete_sandbox(self.sandbox.id if self.sandbox else "unknown")  # 删除沙箱
            self._initialized = False  # 重置初始化标志

    async def think(self) -> bool:
        """处理当前状态并使用适当的上下文决定下一步操作

        Returns:
            bool: 是否需要继续执行
        """
        if not self._initialized:  # 如果未初始化
            await self.initialize_mcp_servers()  # 初始化MCP服务器
            self._initialized = True  # 设置初始化标志

        original_prompt = self.next_step_prompt  # 保存原始提示
        recent_messages = self.memory.messages[-3:] if self.memory.messages else []  # 获取最近3条消息
        browser_in_use = any(
            tc.function.name == SandboxBrowserTool().name  # 检查是否有浏览器工具调用
            for msg in recent_messages
            if msg.tool_calls  # 如果消息包含工具调用
            for tc in msg.tool_calls  # 遍历工具调用
        )

        if browser_in_use:  # 如果浏览器正在使用
            self.next_step_prompt = (
                await self.browser_context_helper.format_next_step_prompt()  # 格式化包含浏览器状态的提示
            )

        result = await super().think()  # 调用父类think方法

        # 恢复原始提示
        self.next_step_prompt = original_prompt  # 恢复原始提示

        return result  # 返回结果
