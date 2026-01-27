import json  # JSON解析库，用于解析浏览器状态
from typing import TYPE_CHECKING, Optional  # 类型提示

from pydantic import Field, model_validator  # Pydantic字段和验证器

from app.agent.toolcall import ToolCallAgent  # 工具调用代理基类
from app.logger import logger  # 日志记录器
from app.prompt.browser import NEXT_STEP_PROMPT, SYSTEM_PROMPT  # 浏览器代理的提示词
from app.schema import Message, ToolChoice  # 消息和工具选择枚举
from app.tool import BrowserUseTool, Terminate, ToolCollection  # 浏览器工具、终止工具、工具集合
from app.tool.sandbox.sb_browser_tool import SandboxBrowserTool  # 沙箱浏览器工具


# 避免循环导入，如果BrowserAgent需要BrowserContextHelper
if TYPE_CHECKING:  # 仅在类型检查时导入
    from app.agent.base import BaseAgent  # 代理基类


class BrowserContextHelper:
    """浏览器上下文助手类

    帮助管理浏览器状态，获取浏览器截图，并格式化下一步提示。
    """
    def __init__(self, agent: "BaseAgent"):
        """初始化浏览器上下文助手

        Args:
            agent: 代理实例
        """
        self.agent = agent  # 保存代理实例
        self._current_base64_image: Optional[str] = None  # 当前浏览器截图的base64编码

    async def get_browser_state(self) -> Optional[dict]:
        """获取当前浏览器状态

        Returns:
            Optional[dict]: 浏览器状态字典，如果获取失败则返回None
        """
        browser_tool = self.agent.available_tools.get_tool(BrowserUseTool().name)  # 尝试获取浏览器工具
        if not browser_tool:  # 如果未找到浏览器工具
            browser_tool = self.agent.available_tools.get_tool(
                SandboxBrowserTool().name  # 尝试获取沙箱浏览器工具
            )
        if not browser_tool or not hasattr(browser_tool, "get_current_state"):  # 如果工具不存在或没有get_current_state方法
            logger.warning("BrowserUseTool not found or doesn't have get_current_state")  # 记录警告
            return None  # 返回None
        try:
            result = await browser_tool.get_current_state()  # 获取浏览器当前状态
            if result.error:  # 如果有错误
                logger.debug(f"Browser state error: {result.error}")  # 记录调试信息
                return None  # 返回None
            if hasattr(result, "base64_image") and result.base64_image:  # 如果结果包含base64图像
                self._current_base64_image = result.base64_image  # 保存图像
            else:  # 如果没有图像
                self._current_base64_image = None  # 清空图像
            return json.loads(result.output)  # 解析并返回状态字典
        except Exception as e:  # 捕获任何异常
            logger.debug(f"Failed to get browser state: {str(e)}")  # 记录调试信息
            return None  # 返回None

    async def format_next_step_prompt(self) -> str:
        """获取浏览器状态并格式化浏览器提示

        Returns:
            str: 格式化后的下一步提示文本
        """
        browser_state = await self.get_browser_state()  # 获取浏览器状态
        url_info, tabs_info, content_above_info, content_below_info = "", "", "", ""  # 初始化信息变量
        results_info = ""  # 结果信息，如果需要可以从代理获取

        if browser_state and not browser_state.get("error"):  # 如果浏览器状态存在且无错误
            url_info = f"\n   URL: {browser_state.get('url', 'N/A')}\n   Title: {browser_state.get('title', 'N/A')}"  # 格式化URL和标题信息
            tabs = browser_state.get("tabs", [])  # 获取标签页列表
            if tabs:  # 如果有标签页
                tabs_info = f"\n   {len(tabs)} tab(s) available"  # 格式化标签页信息
            pixels_above = browser_state.get("pixels_above", 0)  # 获取上方像素数
            pixels_below = browser_state.get("pixels_below", 0)  # 获取下方像素数
            if pixels_above > 0:  # 如果上方有内容
                content_above_info = f" ({pixels_above} pixels)"  # 格式化上方内容信息
            if pixels_below > 0:  # 如果下方有内容
                content_below_info = f" ({pixels_below} pixels)"  # 格式化下方内容信息

            if self._current_base64_image:  # 如果有当前截图
                image_message = Message.user_message(
                    content="Current browser screenshot:",  # 消息内容
                    base64_image=self._current_base64_image,  # base64图像
                )
                self.agent.memory.add_message(image_message)  # 将图像消息添加到内存
                self._current_base64_image = None  # 添加后清空图像（消费图像）

        return NEXT_STEP_PROMPT.format(
            url_placeholder=url_info,  # URL占位符
            tabs_placeholder=tabs_info,  # 标签页占位符
            content_above_placeholder=content_above_info,  # 上方内容占位符
            content_below_placeholder=content_below_info,  # 下方内容占位符
            results_placeholder=results_info,  # 结果占位符
        )

    async def cleanup_browser(self):
        """清理浏览器资源"""
        browser_tool = self.agent.available_tools.get_tool(BrowserUseTool().name)  # 获取浏览器工具
        if browser_tool and hasattr(browser_tool, "cleanup"):  # 如果工具存在且有cleanup方法
            await browser_tool.cleanup()  # 清理浏览器工具


class BrowserAgent(ToolCallAgent):
    """浏览器代理类

    使用browser_use库控制浏览器的代理。

    该代理可以导航网页、与元素交互、填写表单、
    提取内容，并执行其他基于浏览器的操作来完成任务。
    """

    name: str = "browser"  # 代理名称
    description: str = "A browser agent that can control a browser to accomplish tasks"  # 代理描述

    system_prompt: str = SYSTEM_PROMPT  # 系统提示词
    next_step_prompt: str = NEXT_STEP_PROMPT  # 下一步提示词

    max_observe: int = 10000  # 最大观察长度
    max_steps: int = 20  # 最大步骤数

    # 配置可用工具
    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(BrowserUseTool(), Terminate())  # 默认工具集合：浏览器工具和终止工具
    )

    # 使用Auto工具选择，允许工具使用和自由形式响应
    tool_choices: ToolChoice = ToolChoice.AUTO  # 工具选择策略：自动
    special_tool_names: list[str] = Field(default_factory=lambda: [Terminate().name])  # 特殊工具名称列表：终止工具

    browser_context_helper: Optional[BrowserContextHelper] = None  # 浏览器上下文助手，可选

    @model_validator(mode="after")
    def initialize_helper(self) -> "BrowserAgent":
        """初始化浏览器上下文助手

        Returns:
            BrowserAgent: 自身实例
        """
        self.browser_context_helper = BrowserContextHelper(self)  # 创建浏览器上下文助手
        return self  # 返回自身

    async def think(self) -> bool:
        """处理当前状态并决定下一步操作，添加浏览器状态信息

        Returns:
            bool: 是否需要继续执行
        """
        self.next_step_prompt = (
            await self.browser_context_helper.format_next_step_prompt()  # 格式化下一步提示，包含浏览器状态
        )
        return await super().think()  # 调用父类的think方法

    async def cleanup(self):
        """清理浏览器代理资源，调用父类清理方法"""
        await self.browser_context_helper.cleanup_browser()  # 清理浏览器资源
