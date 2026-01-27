import asyncio  # 异步IO库，用于检查协程函数
import json  # JSON解析库，用于解析工具参数
from typing import Any, List, Optional, Union  # 类型提示

from pydantic import Field  # Pydantic字段定义

from app.agent.react import ReActAgent  # ReAct代理基类
from app.exceptions import TokenLimitExceeded  # Token限制超出异常
from app.logger import logger  # 日志记录器
from app.prompt.toolcall import NEXT_STEP_PROMPT, SYSTEM_PROMPT  # 提示词模板
from app.schema import TOOL_CHOICE_TYPE, AgentState, Message, ToolCall, ToolChoice  # 数据模型和枚举
from app.tool import CreateChatCompletion, Terminate, ToolCollection  # 工具类


TOOL_CALL_REQUIRED = "Tool calls required but none provided"  # 工具调用必需的错误消息常量


class ToolCallAgent(ReActAgent):
    """工具调用代理基类

    基于工具/函数调用的代理实现，支持LLM函数调用（Function Calling）。
    继承自ReActAgent，实现了think-act模式中的工具调用逻辑。
    """

    name: str = "toolcall"  # 代理名称，默认"toolcall"
    description: str = "an agent that can execute tool calls."  # 代理描述

    system_prompt: str = SYSTEM_PROMPT  # 系统提示词，从prompt模块导入
    next_step_prompt: str = NEXT_STEP_PROMPT  # 下一步提示词，从prompt模块导入

    available_tools: ToolCollection = ToolCollection(
        CreateChatCompletion(), Terminate()  # 默认工具集合：创建聊天完成和终止工具
    )  # 可用工具集合，默认包含基础工具
    tool_choices: TOOL_CHOICE_TYPE = ToolChoice.AUTO  # type: ignore  # 工具选择策略，默认自动选择
    special_tool_names: List[str] = Field(default_factory=lambda: [Terminate().name])  # 特殊工具名称列表，默认包含终止工具

    tool_calls: List[ToolCall] = Field(default_factory=list)  # 当前步骤的工具调用列表，默认为空列表
    _current_base64_image: Optional[str] = None  # 当前工具调用的Base64图像数据，用于工具消息

    max_steps: int = 30  # 最大步数，默认30步
    max_observe: Optional[Union[int, bool]] = None  # 最大观察长度限制，用于截断工具输出，None表示不限制

    async def think(self) -> bool:
        """思考阶段：处理当前状态并使用工具决定下一步行动

        这是ReAct模式中的think阶段，主要流程：
        1. 如果有next_step_prompt，添加到消息中
        2. 调用LLM的ask_tool方法，传入工具列表
        3. 解析LLM响应中的工具调用
        4. 根据工具选择策略处理响应
        5. 处理Token限制错误

        Returns:
            bool: 如果需要执行行动（有工具调用或内容）返回True，否则返回False
        """
        if self.next_step_prompt:  # 如果存在下一步提示词
            user_msg = Message.user_message(self.next_step_prompt)  # 创建用户消息
            self.messages += [user_msg]  # 将消息添加到消息列表

        try:
            # 获取带工具选项的LLM响应
            response = await self.llm.ask_tool(  # 调用LLM的工具调用接口
                messages=self.messages,  # 传入当前消息列表
                system_msgs=(
                    [Message.system_message(self.system_prompt)]  # 如果有系统提示词则创建系统消息
                    if self.system_prompt  # 检查系统提示词是否存在
                    else None  # 否则为None
                ),
                tools=self.available_tools.to_params(),  # 将工具集合转换为LLM函数调用格式
                tool_choice=self.tool_choices,  # 传入工具选择策略
            )
        except ValueError:  # 捕获值错误
            raise  # 直接重新抛出
        except Exception as e:  # 捕获其他异常
            # 检查是否是包含TokenLimitExceeded的RetryError
            if hasattr(e, "__cause__") and isinstance(e.__cause__, TokenLimitExceeded):  # 检查异常原因是否为TokenLimitExceeded
                token_limit_error = e.__cause__  # 获取Token限制错误
                logger.error(
                    f"🚨 Token limit error (from RetryError): {token_limit_error}"  # 记录错误日志
                )
                self.memory.add_message(  # 添加消息到内存
                    Message.assistant_message(  # 创建助手消息
                        f"Maximum token limit reached, cannot continue execution: {str(token_limit_error)}"  # Token限制错误消息
                    )
                )
                self.state = AgentState.FINISHED  # 设置代理状态为完成
                return False  # 返回False，表示不需要继续执行
            raise  # 其他异常直接重新抛出

        # 解析响应中的工具调用和内容
        self.tool_calls = tool_calls = (
            response.tool_calls if response and response.tool_calls else []  # 提取工具调用列表，如果不存在则为空列表
        )
        content = response.content if response and response.content else ""  # 提取文本内容，如果不存在则为空字符串

        # 记录响应信息日志
        logger.info(f"✨ {self.name}'s thoughts: {content}")  # 记录代理的思考内容
        logger.info(
            f"🛠️ {self.name} selected {len(tool_calls) if tool_calls else 0} tools to use"  # 记录选择的工具数量
        )
        if tool_calls:  # 如果有工具调用
            logger.info(
                f"🧰 Tools being prepared: {[call.function.name for call in tool_calls]}"  # 记录工具名称列表
            )
            logger.info(f"🔧 Tool arguments: {tool_calls[0].function.arguments}")  # 记录第一个工具的参数

        try:
            if response is None:  # 如果响应为None
                raise RuntimeError("No response received from the LLM")  # 抛出运行时错误

            # 处理不同的工具选择模式
            if self.tool_choices == ToolChoice.NONE:  # 如果工具选择策略为NONE（不使用工具）
                if tool_calls:  # 如果LLM仍然返回了工具调用
                    logger.warning(
                        f"🤔 Hmm, {self.name} tried to use tools when they weren't available!"  # 记录警告日志
                    )
                if content:  # 如果有文本内容
                    self.memory.add_message(Message.assistant_message(content))  # 添加助手消息到内存
                    return True  # 返回True，表示有内容需要处理
                return False  # 如果没有内容，返回False

            # 创建并添加助手消息
            assistant_msg = (
                Message.from_tool_calls(content=content, tool_calls=self.tool_calls)  # 如果有工具调用，创建包含工具调用的消息
                if self.tool_calls  # 检查是否有工具调用
                else Message.assistant_message(content)  # 否则创建普通助手消息
            )
            self.memory.add_message(assistant_msg)  # 将助手消息添加到内存

            if self.tool_choices == ToolChoice.REQUIRED and not self.tool_calls:  # 如果要求必须使用工具但没有工具调用
                return True  # 返回True，将在act()中处理错误

            # 对于'auto'模式，如果没有工具调用但有内容，继续处理内容
            if self.tool_choices == ToolChoice.AUTO and not self.tool_calls:  # 如果自动模式且没有工具调用
                return bool(content)  # 根据是否有内容返回布尔值

            return bool(self.tool_calls)  # 返回是否有工具调用
        except Exception as e:  # 捕获任何异常
            logger.error(f"🚨 Oops! The {self.name}'s thinking process hit a snag: {e}")  # 记录错误日志
            self.memory.add_message(  # 添加错误消息到内存
                Message.assistant_message(
                    f"Error encountered while processing: {str(e)}"  # 错误消息内容
                )
            )
            return False  # 返回False，表示思考阶段失败

    async def act(self) -> str:
        """行动阶段：执行工具调用并处理结果

        这是ReAct模式中的act阶段，主要流程：
        1. 检查是否有工具调用
        2. 遍历每个工具调用并执行
        3. 处理工具执行结果
        4. 将工具结果添加到内存
        5. 返回所有结果的摘要

        Returns:
            str: 所有工具执行结果的摘要字符串

        Raises:
            ValueError: 如果工具选择策略为REQUIRED但没有工具调用
        """
        if not self.tool_calls:  # 如果没有工具调用
            if self.tool_choices == ToolChoice.REQUIRED:  # 如果工具选择策略为REQUIRED（必须使用工具）
                raise ValueError(TOOL_CALL_REQUIRED)  # 抛出值错误

            # 如果没有工具调用，返回最后一条消息的内容
            return self.messages[-1].content or "No content or commands to execute"  # 返回内容或默认消息

        results = []  # 初始化结果列表
        for command in self.tool_calls:  # 遍历每个工具调用
            # 为每个工具调用重置base64_image
            self._current_base64_image = None  # 重置图像数据

            result = await self.execute_tool(command)  # 执行工具调用

            if self.max_observe:  # 如果设置了最大观察长度限制
                result = result[: self.max_observe]  # 截断结果到最大长度

            logger.info(
                f"🎯 Tool '{command.function.name}' completed its mission! Result: {result}"  # 记录工具执行完成日志
            )

            # 将工具响应添加到内存
            tool_msg = Message.tool_message(  # 创建工具消息
                content=result,  # 工具执行结果
                tool_call_id=command.id,  # 关联的工具调用ID
                name=command.function.name,  # 工具名称
                base64_image=self._current_base64_image,  # 可选的图像数据
            )
            self.memory.add_message(tool_msg)  # 将工具消息添加到内存
            results.append(result)  # 将结果添加到结果列表

        return "\n\n".join(results)  # 返回所有结果，用双换行符连接

    async def execute_tool(self, command: ToolCall) -> str:
        """执行单个工具调用，包含健壮的错误处理

        Args:
            command: 工具调用对象，包含工具名称和参数

        Returns:
            str: 工具执行结果的观察字符串，如果出错则返回错误消息
        """
        if not command or not command.function or not command.function.name:  # 验证命令格式
            return "Error: Invalid command format"  # 返回格式错误消息

        name = command.function.name  # 获取工具名称
        if name not in self.available_tools.tool_map:  # 检查工具是否存在
            return f"Error: Unknown tool '{name}'"  # 返回未知工具错误消息

        try:
            # 解析参数
            args = json.loads(command.function.arguments or "{}")  # 将JSON字符串解析为字典，如果为空则使用空字典

            # 执行工具
            logger.info(f"🔧 Activating tool: '{name}'...")  # 记录工具激活日志
            result = await self.available_tools.execute(name=name, tool_input=args)  # 通过工具集合执行工具

            # 处理特殊工具
            await self._handle_special_tool(name=name, result=result)  # 检查并处理特殊工具（如Terminate）

            # 检查结果是否是包含base64_image的ToolResult
            if hasattr(result, "base64_image") and result.base64_image:  # 如果结果包含图像数据
                # 存储base64_image以便在tool_message中使用
                self._current_base64_image = result.base64_image  # 保存图像数据到实例变量

            # 格式化结果显示（标准情况）
            observation = (
                f"Observed output of cmd `{name}` executed:\n{str(result)}"  # 如果有结果，格式化观察消息
                if result  # 检查是否有结果
                else f"Cmd `{name}` completed with no output"  # 如果没有结果，返回完成消息
            )

            return observation  # 返回观察消息
        except json.JSONDecodeError:  # 捕获JSON解析错误
            error_msg = f"Error parsing arguments for {name}: Invalid JSON format"  # 构建错误消息
            logger.error(
                f"📝 Oops! The arguments for '{name}' don't make sense - invalid JSON, arguments:{command.function.arguments}"  # 记录错误日志
            )
            return f"Error: {error_msg}"  # 返回错误消息
        except Exception as e:  # 捕获其他异常
            error_msg = f"⚠️ Tool '{name}' encountered a problem: {str(e)}"  # 构建错误消息
            logger.exception(error_msg)  # 记录异常日志（包含堆栈跟踪）
            return f"Error: {error_msg}"  # 返回错误消息

    async def _handle_special_tool(self, name: str, result: Any, **kwargs):
        """处理特殊工具执行和状态变化

        特殊工具（如Terminate）可能会改变代理的执行状态

        Args:
            name: 工具名称
            result: 工具执行结果
            **kwargs: 其他参数
        """
        if not self._is_special_tool(name):  # 检查是否是特殊工具
            return  # 如果不是特殊工具，直接返回

        if self._should_finish_execution(name=name, result=result, **kwargs):  # 检查是否应该完成执行
            # 设置代理状态为完成
            logger.info(f"🏁 Special tool '{name}' has completed the task!")  # 记录完成日志
            self.state = AgentState.FINISHED  # 设置状态为完成

    @staticmethod
    def _should_finish_execution(**kwargs) -> bool:
        """判断工具执行是否应该完成代理

        静态方法，子类可以覆盖此方法以自定义完成逻辑

        Args:
            **kwargs: 参数（name, result等）

        Returns:
            bool: 如果应该完成执行返回True，否则返回False
        """
        return True  # 默认返回True，表示特殊工具执行后应该完成

    def _is_special_tool(self, name: str) -> bool:
        """检查工具名称是否在特殊工具列表中

        Args:
            name: 工具名称

        Returns:
            bool: 如果是特殊工具返回True，否则返回False
        """
        return name.lower() in [n.lower() for n in self.special_tool_names]  # 不区分大小写比较

    async def cleanup(self):
        """清理代理工具使用的资源

        遍历所有工具，如果工具有cleanup方法，则调用它进行清理。
        用于释放浏览器连接、文件句柄等资源。
        """
        logger.info(f"🧹 Cleaning up resources for agent '{self.name}'...")  # 记录清理开始日志
        for tool_name, tool_instance in self.available_tools.tool_map.items():  # 遍历所有工具
            if hasattr(tool_instance, "cleanup") and asyncio.iscoroutinefunction(
                tool_instance.cleanup
            ):  # 检查工具是否有异步cleanup方法
                try:
                    logger.debug(f"🧼 Cleaning up tool: {tool_name}")  # 记录工具清理日志
                    await tool_instance.cleanup()  # 调用工具的cleanup方法
                except Exception as e:  # 捕获清理过程中的异常
                    logger.error(
                        f"🚨 Error cleaning up tool '{tool_name}': {e}", exc_info=True  # 记录错误日志（包含堆栈跟踪）
                    )
        logger.info(f"✨ Cleanup complete for agent '{self.name}'.")  # 记录清理完成日志

    async def run(self, request: Optional[str] = None) -> str:
        """运行代理，完成后进行清理

        重写父类的run方法，确保无论是否发生异常都会清理资源

        Args:
            request: 可选的初始用户请求

        Returns:
            str: 执行结果摘要
        """
        try:
            return await super().run(request)  # 调用父类的run方法
        finally:
            await self.cleanup()  # 无论是否发生异常，都执行清理
