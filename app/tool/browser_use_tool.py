import asyncio  # 异步IO库
import base64  # Base64编码库，用于图像编码
import json  # JSON解析库
from typing import Generic, Optional, TypeVar  # 类型提示和泛型

from browser_use import Browser as BrowserUseBrowser  # browser_use库的Browser类
from browser_use import BrowserConfig  # 浏览器配置类
from browser_use.browser.context import BrowserContext, BrowserContextConfig  # 浏览器上下文和配置
from browser_use.dom.service import DomService  # DOM服务类
from pydantic import Field, field_validator  # Pydantic字段和验证器
from pydantic_core.core_schema import ValidationInfo  # Pydantic验证信息

from app.config import config  # 全局配置
from app.llm import LLM  # LLM客户端
from app.tool.base import BaseTool, ToolResult  # 工具基类和结果类
from app.tool.web_search import WebSearch  # 网络搜索工具


_BROWSER_DESCRIPTION = """\
A powerful browser automation tool that allows interaction with web pages through various actions.
* This tool provides commands for controlling a browser session, navigating web pages, and extracting information
* It maintains state across calls, keeping the browser session alive until explicitly closed
* Use this when you need to browse websites, fill forms, click buttons, extract content, or perform web searches
* Each action requires specific parameters as defined in the tool's dependencies

Key capabilities include:
* Navigation: Go to specific URLs, go back, search the web, or refresh pages
* Interaction: Click elements, input text, select from dropdowns, send keyboard commands
* Scrolling: Scroll up/down by pixel amount or scroll to specific text
* Content extraction: Extract and analyze content from web pages based on specific goals
* Tab management: Switch between tabs, open new tabs, or close tabs

Note: When using element indices, refer to the numbered elements shown in the current browser state.
"""  # 浏览器工具的描述文本

Context = TypeVar("Context")  # 上下文类型变量


class BrowserUseTool(BaseTool, Generic[Context]):
    """浏览器使用工具类

    强大的浏览器自动化工具，允许通过各种操作与网页交互。
    使用browser_use库实现浏览器控制。
    """
    name: str = "browser_use"  # 工具名称
    description: str = _BROWSER_DESCRIPTION  # 工具描述
    parameters: dict = {
        "type": "object",  # 参数类型为对象
        "properties": {
            "action": {
                "type": "string",  # 操作类型为字符串
                "enum": [
                    "go_to_url",  # 导航到URL
                    "click_element",  # 点击元素
                    "input_text",  # 输入文本
                    "scroll_down",  # 向下滚动
                    "scroll_up",  # 向上滚动
                    "scroll_to_text",  # 滚动到文本
                    "send_keys",  # 发送按键
                    "get_dropdown_options",  # 获取下拉选项
                    "select_dropdown_option",  # 选择下拉选项
                    "go_back",  # 后退
                    "web_search",  # 网络搜索
                    "wait",  # 等待
                    "extract_content",  # 提取内容
                    "switch_tab",  # 切换标签页
                    "open_tab",  # 打开标签页
                    "close_tab",  # 关闭标签页
                ],
                "description": "The browser action to perform",  # 操作描述
            },
            "url": {
                "type": "string",
                "description": "URL for 'go_to_url' or 'open_tab' actions",
            },
            "index": {
                "type": "integer",
                "description": "Element index for 'click_element', 'input_text', 'get_dropdown_options', or 'select_dropdown_option' actions",
            },
            "text": {
                "type": "string",
                "description": "Text for 'input_text', 'scroll_to_text', or 'select_dropdown_option' actions",
            },
            "scroll_amount": {
                "type": "integer",
                "description": "Pixels to scroll (positive for down, negative for up) for 'scroll_down' or 'scroll_up' actions",
            },
            "tab_id": {
                "type": "integer",
                "description": "Tab ID for 'switch_tab' action",
            },
            "query": {
                "type": "string",
                "description": "Search query for 'web_search' action",
            },
            "goal": {
                "type": "string",
                "description": "Extraction goal for 'extract_content' action",
            },
            "keys": {
                "type": "string",
                "description": "Keys to send for 'send_keys' action",
            },
            "seconds": {
                "type": "integer",
                "description": "Seconds to wait for 'wait' action",
            },
        },
        "required": ["action"],
        "dependencies": {
            "go_to_url": ["url"],
            "click_element": ["index"],
            "input_text": ["index", "text"],
            "switch_tab": ["tab_id"],
            "open_tab": ["url"],
            "scroll_down": ["scroll_amount"],
            "scroll_up": ["scroll_amount"],
            "scroll_to_text": ["text"],
            "send_keys": ["keys"],
            "get_dropdown_options": ["index"],
            "select_dropdown_option": ["index", "text"],
            "go_back": [],
            "web_search": ["query"],
            "wait": ["seconds"],
            "extract_content": ["goal"],
        },
    }

    lock: asyncio.Lock = Field(default_factory=asyncio.Lock)  # 异步锁，用于同步访问
    browser: Optional[BrowserUseBrowser] = Field(default=None, exclude=True)  # 浏览器实例，可选，排除在Schema外
    context: Optional[BrowserContext] = Field(default=None, exclude=True)  # 浏览器上下文，可选，排除在Schema外
    dom_service: Optional[DomService] = Field(default=None, exclude=True)  # DOM服务，可选，排除在Schema外
    web_search_tool: WebSearch = Field(default_factory=WebSearch, exclude=True)  # 网络搜索工具，排除在Schema外

    # 通用功能的上下文
    tool_context: Optional[Context] = Field(default=None, exclude=True)  # 工具上下文，可选，排除在Schema外

    llm: Optional[LLM] = Field(default_factory=LLM)  # LLM客户端，可选

    @field_validator("parameters", mode="before")
    def validate_parameters(cls, v: dict, info: ValidationInfo) -> dict:
        """验证参数

        Args:
            v: 参数字典
            info: 验证信息

        Returns:
            dict: 验证后的参数字典

        Raises:
            ValueError: 如果参数为空
        """
        if not v:  # 如果参数为空
            raise ValueError("Parameters cannot be empty")  # 抛出值错误
        return v  # 返回参数

    async def _ensure_browser_initialized(self) -> BrowserContext:
        """确保浏览器和上下文已初始化

        Returns:
            BrowserContext: 浏览器上下文实例
        """
        if self.browser is None:  # 如果浏览器未初始化
            browser_config_kwargs = {"headless": False, "disable_security": True}  # 默认浏览器配置：非无头模式，禁用安全

            if config.browser_config:  # 如果配置中有浏览器配置
                from browser_use.browser.browser import ProxySettings  # 导入代理设置类

                # 处理代理设置
                if config.browser_config.proxy and config.browser_config.proxy.server:  # 如果配置了代理服务器
                    browser_config_kwargs["proxy"] = ProxySettings(
                        server=config.browser_config.proxy.server,  # 代理服务器
                        username=config.browser_config.proxy.username,  # 代理用户名
                        password=config.browser_config.proxy.password,  # 代理密码
                    )

                browser_attrs = [
                    "headless",  # 无头模式
                    "disable_security",  # 禁用安全
                    "extra_chromium_args",  # 额外Chromium参数
                    "chrome_instance_path",  # Chrome实例路径
                    "wss_url",  # WebSocket URL
                    "cdp_url",  # Chrome DevTools Protocol URL
                ]

                for attr in browser_attrs:  # 遍历浏览器属性
                    value = getattr(config.browser_config, attr, None)  # 获取属性值
                    if value is not None:  # 如果值不为None
                        if not isinstance(value, list) or value:  # 如果不是列表或列表不为空
                            browser_config_kwargs[attr] = value  # 添加到配置字典

            self.browser = BrowserUseBrowser(BrowserConfig(**browser_config_kwargs))  # 创建浏览器实例

        if self.context is None:  # 如果上下文未初始化
            context_config = BrowserContextConfig()  # 创建默认上下文配置

            # 如果配置中有上下文配置，使用它
            if (
                config.browser_config  # 如果浏览器配置存在
                and hasattr(config.browser_config, "new_context_config")  # 且有new_context_config属性
                and config.browser_config.new_context_config  # 且值不为None
            ):
                context_config = config.browser_config.new_context_config  # 使用配置的上下文配置

            self.context = await self.browser.new_context(context_config)  # 创建新上下文
            self.dom_service = DomService(await self.context.get_current_page())  # 创建DOM服务

        return self.context  # 返回上下文

    async def execute(
        self,
        action: str,
        url: Optional[str] = None,
        index: Optional[int] = None,
        text: Optional[str] = None,
        scroll_amount: Optional[int] = None,
        tab_id: Optional[int] = None,
        query: Optional[str] = None,
        goal: Optional[str] = None,
        keys: Optional[str] = None,
        seconds: Optional[int] = None,
        **kwargs,
    ) -> ToolResult:
        """
        Execute a specified browser action.

        Args:
            action: The browser action to perform
            url: URL for navigation or new tab
            index: Element index for click or input actions
            text: Text for input action or search query
            scroll_amount: Pixels to scroll for scroll action
            tab_id: Tab ID for switch_tab action
            query: Search query for Google search
            goal: Extraction goal for content extraction
            keys: Keys to send for keyboard actions
            seconds: Seconds to wait
            **kwargs: Additional arguments

        Returns:
            ToolResult with the action's output or error
        """
        async with self.lock:
            try:
                context = await self._ensure_browser_initialized()

                # Get max content length from config
                max_content_length = getattr(
                    config.browser_config, "max_content_length", 2000
                )

                # Navigation actions
                if action == "go_to_url":
                    if not url:
                        return ToolResult(
                            error="URL is required for 'go_to_url' action"
                        )
                    page = await context.get_current_page()
                    await page.goto(url)
                    await page.wait_for_load_state()
                    return ToolResult(output=f"Navigated to {url}")

                elif action == "go_back":
                    await context.go_back()
                    return ToolResult(output="Navigated back")

                elif action == "refresh":
                    await context.refresh_page()
                    return ToolResult(output="Refreshed current page")

                elif action == "web_search":
                    if not query:
                        return ToolResult(
                            error="Query is required for 'web_search' action"
                        )
                    # Execute the web search and return results directly without browser navigation
                    search_response = await self.web_search_tool.execute(
                        query=query, fetch_content=True, num_results=1
                    )
                    # Navigate to the first search result
                    first_search_result = search_response.results[0]
                    url_to_navigate = first_search_result.url

                    page = await context.get_current_page()
                    await page.goto(url_to_navigate)
                    await page.wait_for_load_state()

                    return search_response

                # Element interaction actions
                elif action == "click_element":
                    if index is None:
                        return ToolResult(
                            error="Index is required for 'click_element' action"
                        )
                    element = await context.get_dom_element_by_index(index)
                    if not element:
                        return ToolResult(error=f"Element with index {index} not found")
                    download_path = await context._click_element_node(element)
                    output = f"Clicked element at index {index}"
                    if download_path:
                        output += f" - Downloaded file to {download_path}"
                    return ToolResult(output=output)

                elif action == "input_text":
                    if index is None or not text:
                        return ToolResult(
                            error="Index and text are required for 'input_text' action"
                        )
                    element = await context.get_dom_element_by_index(index)
                    if not element:
                        return ToolResult(error=f"Element with index {index} not found")
                    await context._input_text_element_node(element, text)
                    return ToolResult(
                        output=f"Input '{text}' into element at index {index}"
                    )

                elif action == "scroll_down" or action == "scroll_up":
                    direction = 1 if action == "scroll_down" else -1
                    amount = (
                        scroll_amount
                        if scroll_amount is not None
                        else context.config.browser_window_size["height"]
                    )
                    await context.execute_javascript(
                        f"window.scrollBy(0, {direction * amount});"
                    )
                    return ToolResult(
                        output=f"Scrolled {'down' if direction > 0 else 'up'} by {amount} pixels"
                    )

                elif action == "scroll_to_text":
                    if not text:
                        return ToolResult(
                            error="Text is required for 'scroll_to_text' action"
                        )
                    page = await context.get_current_page()
                    try:
                        locator = page.get_by_text(text, exact=False)
                        await locator.scroll_into_view_if_needed()
                        return ToolResult(output=f"Scrolled to text: '{text}'")
                    except Exception as e:
                        return ToolResult(error=f"Failed to scroll to text: {str(e)}")

                elif action == "send_keys":
                    if not keys:
                        return ToolResult(
                            error="Keys are required for 'send_keys' action"
                        )
                    page = await context.get_current_page()
                    await page.keyboard.press(keys)
                    return ToolResult(output=f"Sent keys: {keys}")

                elif action == "get_dropdown_options":
                    if index is None:
                        return ToolResult(
                            error="Index is required for 'get_dropdown_options' action"
                        )
                    element = await context.get_dom_element_by_index(index)
                    if not element:
                        return ToolResult(error=f"Element with index {index} not found")
                    page = await context.get_current_page()
                    options = await page.evaluate(
                        """
                        (xpath) => {
                            const select = document.evaluate(xpath, document, null,
                                XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                            if (!select) return null;
                            return Array.from(select.options).map(opt => ({
                                text: opt.text,
                                value: opt.value,
                                index: opt.index
                            }));
                        }
                    """,
                        element.xpath,
                    )
                    return ToolResult(output=f"Dropdown options: {options}")

                elif action == "select_dropdown_option":
                    if index is None or not text:
                        return ToolResult(
                            error="Index and text are required for 'select_dropdown_option' action"
                        )
                    element = await context.get_dom_element_by_index(index)
                    if not element:
                        return ToolResult(error=f"Element with index {index} not found")
                    page = await context.get_current_page()
                    await page.select_option(element.xpath, label=text)
                    return ToolResult(
                        output=f"Selected option '{text}' from dropdown at index {index}"
                    )

                # 内容提取操作
                elif action == "extract_content":  # 如果操作是提取内容
                    if not goal:  # 如果未提供目标
                        return ToolResult(
                            error="Goal is required for 'extract_content' action"  # 返回错误结果
                        )

                    page = await context.get_current_page()  # 获取当前页面
                    import markdownify  # 导入markdownify库

                    content = markdownify.markdownify(await page.content())  # 将页面内容转换为Markdown

                    prompt = f"""\
Your task is to extract the content of the page. You will be given a page and a goal, and you should extract all relevant information around this goal from the page. If the goal is vague, summarize the page. Respond in json format.
Extraction goal: {goal}

Page content:
{content[:max_content_length]}  # 截取内容到最大长度
"""
                    messages = [{"role": "system", "content": prompt}]  # 创建系统消息

                    # 定义提取函数Schema
                    extraction_function = {
                        "type": "function",  # 函数类型
                        "function": {
                            "name": "extract_content",  # 函数名称
                            "description": "Extract specific information from a webpage based on a goal",  # 函数描述
                            "parameters": {
                                "type": "object",  # 参数类型为对象
                                "properties": {
                                    "extracted_content": {
                                        "type": "object",  # 提取内容类型为对象
                                        "description": "The content extracted from the page according to the goal",  # 描述
                                        "properties": {
                                            "text": {
                                                "type": "string",  # 文本类型为字符串
                                                "description": "Text content extracted from the page",  # 文本描述
                                            },
                                            "metadata": {
                                                "type": "object",  # 元数据类型为对象
                                                "description": "Additional metadata about the extracted content",  # 元数据描述
                                                "properties": {
                                                    "source": {
                                                        "type": "string",  # 源类型为字符串
                                                        "description": "Source of the extracted content",  # 源描述
                                                    }
                                                },
                                            },
                                        },
                                    }
                                },
                                "required": ["extracted_content"],  # 必需字段：extracted_content
                            },
                        },
                    }

                    # 使用LLM通过必需的函数调用来提取内容
                    response = await self.llm.ask_tool(
                        messages,  # 消息列表
                        tools=[extraction_function],  # 工具列表
                        tool_choice="required",  # 工具选择：必需
                    )

                    if response and response.tool_calls:  # 如果响应存在且包含工具调用
                        args = json.loads(response.tool_calls[0].function.arguments)  # 解析工具调用参数
                        extracted_content = args.get("extracted_content", {})  # 获取提取的内容
                        return ToolResult(
                            output=f"Extracted from page:\n{extracted_content}\n"  # 返回提取结果
                        )

                    return ToolResult(output="No content was extracted from the page.")  # 返回无内容结果

                # 标签页管理操作
                elif action == "switch_tab":  # 如果操作是切换标签页
                    if tab_id is None:  # 如果未提供标签页ID
                        return ToolResult(
                            error="Tab ID is required for 'switch_tab' action"  # 返回错误结果
                        )
                    await context.switch_to_tab(tab_id)  # 切换到指定标签页
                    page = await context.get_current_page()  # 获取当前页面
                    await page.wait_for_load_state()  # 等待页面加载完成
                    return ToolResult(output=f"Switched to tab {tab_id}")  # 返回成功结果

                elif action == "open_tab":  # 如果操作是打开标签页
                    if not url:  # 如果未提供URL
                        return ToolResult(error="URL is required for 'open_tab' action")  # 返回错误结果
                    await context.create_new_tab(url)  # 创建新标签页
                    return ToolResult(output=f"Opened new tab with {url}")  # 返回成功结果

                elif action == "close_tab":  # 如果操作是关闭标签页
                    await context.close_current_tab()  # 关闭当前标签页
                    return ToolResult(output="Closed current tab")  # 返回成功结果

                # 实用操作
                elif action == "wait":  # 如果操作是等待
                    seconds_to_wait = seconds if seconds is not None else 3  # 使用提供的秒数或默认3秒
                    await asyncio.sleep(seconds_to_wait)  # 等待指定秒数
                    return ToolResult(output=f"Waited for {seconds_to_wait} seconds")  # 返回成功结果

                else:  # 如果操作未知
                    return ToolResult(error=f"Unknown action: {action}")  # 返回错误结果

            except Exception as e:  # 捕获任何异常
                return ToolResult(error=f"Browser action '{action}' failed: {str(e)}")  # 返回错误结果

    async def get_current_state(
        self, context: Optional[BrowserContext] = None
    ) -> ToolResult:
        """获取当前浏览器状态作为ToolResult

        如果未提供context，则使用self.context。

        Args:
            context: 浏览器上下文，可选

        Returns:
            ToolResult: 包含浏览器状态和截图的工具结果
        """
        try:
            # 使用提供的上下文或回退到self.context
            ctx = context or self.context  # 使用提供的上下文或自身上下文
            if not ctx:  # 如果上下文不存在
                return ToolResult(error="Browser context not initialized")  # 返回错误结果

            state = await ctx.get_state()  # 获取浏览器状态

            # 如果不存在viewport_info字典，则创建一个
            viewport_height = 0  # 初始化视口高度
            if hasattr(state, "viewport_info") and state.viewport_info:  # 如果状态有viewport_info属性
                viewport_height = state.viewport_info.height  # 获取视口高度
            elif hasattr(ctx, "config") and hasattr(ctx.config, "browser_window_size"):  # 如果上下文有配置
                viewport_height = ctx.config.browser_window_size.get("height", 0)  # 从配置获取高度

            # 为状态拍摄截图
            page = await ctx.get_current_page()  # 获取当前页面

            await page.bring_to_front()  # 将页面置于前台
            await page.wait_for_load_state()  # 等待页面加载完成

            screenshot = await page.screenshot(
                full_page=True, animations="disabled", type="jpeg", quality=100  # 拍摄全页截图，禁用动画，JPEG格式，质量100
            )

            screenshot = base64.b64encode(screenshot).decode("utf-8")  # 将截图编码为base64

            # 构建包含所有必需字段的状态信息
            state_info = {
                "url": state.url,  # URL
                "title": state.title,  # 标题
                "tabs": [tab.model_dump() for tab in state.tabs],  # 标签页列表
                "help": "[0], [1], [2], etc., represent clickable indices corresponding to the elements listed. Clicking on these indices will navigate to or interact with the respective content behind them.",  # 帮助信息
                "interactive_elements": (
                    state.element_tree.clickable_elements_to_string()  # 交互元素字符串
                    if state.element_tree  # 如果元素树存在
                    else ""  # 否则为空字符串
                ),
                "scroll_info": {
                    "pixels_above": getattr(state, "pixels_above", 0),  # 上方像素数
                    "pixels_below": getattr(state, "pixels_below", 0),  # 下方像素数
                    "total_height": getattr(state, "pixels_above", 0)  # 总高度
                    + getattr(state, "pixels_below", 0)  # 上方+下方+视口高度
                    + viewport_height,
                },
                "viewport_height": viewport_height,  # 视口高度
            }

            return ToolResult(
                output=json.dumps(state_info, indent=4, ensure_ascii=False),  # 输出JSON格式的状态信息
                base64_image=screenshot,  # base64编码的截图
            )
        except Exception as e:  # 捕获任何异常
            return ToolResult(error=f"Failed to get browser state: {str(e)}")  # 返回错误结果

    async def cleanup(self):
        """清理浏览器资源"""
        async with self.lock:  # 使用锁保护清理操作
            if self.context is not None:  # 如果上下文存在
                await self.context.close()  # 关闭上下文
                self.context = None  # 设置为None
                self.dom_service = None  # 设置为None
            if self.browser is not None:  # 如果浏览器存在
                await self.browser.close()  # 关闭浏览器
                self.browser = None  # 设置为None

    def __del__(self):
        """确保对象销毁时进行清理"""
        if self.browser is not None or self.context is not None:  # 如果浏览器或上下文存在
            try:
                asyncio.run(self.cleanup())  # 运行清理
            except RuntimeError:  # 如果运行时错误（可能已有事件循环）
                loop = asyncio.new_event_loop()  # 创建新事件循环
                loop.run_until_complete(self.cleanup())  # 运行清理直到完成
                loop.close()  # 关闭循环

    @classmethod
    def create_with_context(cls, context: Context) -> "BrowserUseTool[Context]":
        """工厂方法：创建具有特定上下文的BrowserUseTool

        Args:
            context: 上下文对象

        Returns:
            BrowserUseTool[Context]: 浏览器工具实例
        """
        tool = cls()  # 创建工具实例
        tool.tool_context = context  # 设置工具上下文
        return tool  # 返回工具
