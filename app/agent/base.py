from abc import ABC, abstractmethod  # 抽象基类和抽象方法装饰器
from contextlib import asynccontextmanager  # 异步上下文管理器装饰器
from typing import List, Optional  # 类型提示

from pydantic import BaseModel, Field, model_validator  # Pydantic数据验证库

from app.llm import LLM  # LLM客户端
from app.logger import logger  # 日志记录器
from app.sandbox.client import SANDBOX_CLIENT  # 沙箱客户端单例
from app.schema import ROLE_TYPE, AgentState, Memory, Message  # 数据模型和枚举


class BaseAgent(BaseModel, ABC):
    """代理基类：管理代理状态和执行

    提供状态转换、内存管理和基于步骤的执行循环等基础功能。
    子类必须实现`step`方法。
    """

    # 核心属性
    name: str = Field(..., description="Unique name of the agent")  # 代理的唯一名称，必填字段
    description: Optional[str] = Field(None, description="Optional agent description")  # 代理描述，可选

    # 提示词
    system_prompt: Optional[str] = Field(
        None, description="System-level instruction prompt"
    )  # 系统级指令提示词，用于指导代理行为
    next_step_prompt: Optional[str] = Field(
        None, description="Prompt for determining next action"
    )  # 下一步行动提示词，用于动态调整代理行为

    # 依赖组件
    llm: LLM = Field(default_factory=LLM, description="Language model instance")  # 语言模型实例，默认创建新实例
    memory: Memory = Field(default_factory=Memory, description="Agent's memory store")  # 代理的内存存储，用于保存对话历史
    state: AgentState = Field(
        default=AgentState.IDLE, description="Current agent state"
    )  # 当前代理状态，默认为IDLE（空闲）

    # 执行控制
    max_steps: int = Field(default=10, description="Maximum steps before termination")  # 终止前的最大步数，默认10步
    current_step: int = Field(default=0, description="Current step in execution")  # 当前执行步骤，默认0

    duplicate_threshold: int = 2  # 重复阈值，用于检测代理是否卡死（重复响应次数）

    class Config:
        arbitrary_types_allowed = True  # 允许任意类型（用于LLM、Memory等复杂类型）
        extra = "allow"  # 允许额外字段，为子类提供灵活性

    @model_validator(mode="after")
    def initialize_agent(self) -> "BaseAgent":
        """初始化代理：如果未提供则使用默认设置

        在Pydantic模型验证后调用，确保LLM和Memory已正确初始化

        Returns:
            BaseAgent: 初始化后的代理实例
        """
        if self.llm is None or not isinstance(self.llm, LLM):  # 如果LLM未初始化或类型不正确
            self.llm = LLM(config_name=self.name.lower())  # 使用代理名称创建LLM实例
        if not isinstance(self.memory, Memory):  # 如果Memory未初始化
            self.memory = Memory()  # 创建新的Memory实例
        return self  # 返回自身以支持链式调用

    @asynccontextmanager
    async def state_context(self, new_state: AgentState):
        """状态上下文管理器：安全地进行代理状态转换

        使用上下文管理器确保状态转换的安全性：
        - 进入上下文时转换到新状态
        - 发生异常时转换到ERROR状态
        - 退出上下文时恢复到之前的状态

        Args:
            new_state: 在上下文期间要转换到的状态

        Yields:
            None: 允许在新状态下执行代码

        Raises:
            ValueError: 如果new_state无效
        """
        if not isinstance(new_state, AgentState):  # 验证状态类型
            raise ValueError(f"Invalid state: {new_state}")  # 抛出值错误

        previous_state = self.state  # 保存之前的状态
        self.state = new_state  # 转换到新状态
        try:
            yield  # 执行上下文内的代码
        except Exception as e:  # 捕获任何异常
            self.state = AgentState.ERROR  # 发生异常时转换到ERROR状态
            raise e  # 重新抛出异常
        finally:
            self.state = previous_state  # 无论是否发生异常，都恢复到之前的状态

    def update_memory(
        self,
        role: ROLE_TYPE,  # type: ignore
        content: str,
        base64_image: Optional[str] = None,
        **kwargs,
    ) -> None:
        """更新内存：向代理的内存中添加一条消息

        Args:
            role: 消息发送者的角色（user, system, assistant, tool）
            content: 消息内容
            base64_image: 可选的base64编码图像
            **kwargs: 额外参数（例如tool消息的tool_call_id）

        Raises:
            ValueError: 如果角色不受支持
        """
        # 消息类型到创建函数的映射
        message_map = {
            "user": Message.user_message,  # 用户消息创建函数
            "system": Message.system_message,  # 系统消息创建函数
            "assistant": Message.assistant_message,  # 助手消息创建函数
            "tool": lambda content, **kw: Message.tool_message(content, **kw),  # 工具消息创建函数（lambda）
        }

        if role not in message_map:  # 检查角色是否支持
            raise ValueError(f"Unsupported message role: {role}")  # 抛出值错误

        # 根据角色创建消息，使用适当的参数
        kwargs = {"base64_image": base64_image, **(kwargs if role == "tool" else {})}  # 合并参数，tool消息需要额外参数
        self.memory.add_message(message_map[role](content, **kwargs))  # 调用对应的消息创建函数并添加到内存

    async def run(self, request: Optional[str] = None) -> str:
        """异步执行代理的主循环

        这是代理的主要执行入口，负责：
        1. 验证初始状态
        2. 添加用户请求到内存
        3. 进入RUNNING状态
        4. 循环执行step()直到完成或达到最大步数
        5. 检测和处理卡死状态
        6. 清理资源

        Args:
            request: 可选的初始用户请求

        Returns:
            str: 执行结果的摘要字符串

        Raises:
            RuntimeError: 如果代理不是从IDLE状态开始
        """
        if self.state != AgentState.IDLE:  # 检查初始状态
            raise RuntimeError(f"Cannot run agent from state: {self.state}")  # 如果不是IDLE状态则抛出运行时错误

        if request:  # 如果提供了请求
            self.update_memory("user", request)  # 将用户请求添加到内存

        results: List[str] = []  # 初始化结果列表
        async with self.state_context(AgentState.RUNNING):  # 进入RUNNING状态上下文
            while (
                self.current_step < self.max_steps and self.state != AgentState.FINISHED
            ):  # 循环条件：未达到最大步数且未完成
                self.current_step += 1  # 增加当前步数
                logger.info(f"Executing step {self.current_step}/{self.max_steps}")  # 记录日志
                step_result = await self.step()  # 执行单步（抽象方法，由子类实现）

                # 检查卡死状态
                if self.is_stuck():  # 如果检测到卡死
                    self.handle_stuck_state()  # 处理卡死状态（添加提示词）

                results.append(f"Step {self.current_step}: {step_result}")  # 将步骤结果添加到结果列表

            if self.current_step >= self.max_steps:  # 如果达到最大步数
                self.current_step = 0  # 重置当前步数
                self.state = AgentState.IDLE  # 转换到IDLE状态
                results.append(f"Terminated: Reached max steps ({self.max_steps})")  # 添加终止消息
        await SANDBOX_CLIENT.cleanup()  # 清理沙箱资源
        return "\n".join(results) if results else "No steps executed"  # 返回结果摘要，如果没有结果则返回默认消息

    @abstractmethod
    async def step(self) -> str:
        """执行代理工作流中的单步

        抽象方法，必须由子类实现以定义具体行为。
        这是代理执行的核心方法，每个子类都会有不同的实现。
        """

    def handle_stuck_state(self):
        """处理卡死状态：通过添加提示词来改变策略

        当检测到代理卡死时，会在next_step_prompt前添加提示词，
        引导代理尝试新的策略，避免重复无效的路径。
        """
        stuck_prompt = "\
        Observed duplicate responses. Consider new strategies and avoid repeating ineffective paths already attempted."  # 卡死提示词
        self.next_step_prompt = f"{stuck_prompt}\n{self.next_step_prompt}"  # 将卡死提示词添加到next_step_prompt前面
        logger.warning(f"Agent detected stuck state. Added prompt: {stuck_prompt}")  # 记录警告日志

    def is_stuck(self) -> bool:
        """检查代理是否卡死：通过检测重复内容来判断

        通过检查最近的消息中是否有重复的助手响应来判断代理是否卡死。
        如果最近的助手消息中有duplicate_threshold条相同内容，则认为卡死。

        Returns:
            bool: 如果检测到卡死则返回True，否则返回False
        """
        if len(self.memory.messages) < 2:  # 如果消息数量少于2条，无法判断卡死
            return False  # 返回False

        last_message = self.memory.messages[-1]  # 获取最后一条消息
        if not last_message.content:  # 如果最后一条消息没有内容
            return False  # 返回False

        # 统计相同内容的出现次数
        duplicate_count = sum(
            1  # 计数加1
            for msg in reversed(self.memory.messages[:-1])  # 从倒数第二条消息开始向前遍历
            if msg.role == "assistant" and msg.content == last_message.content  # 如果是助手消息且内容相同
        )

        return duplicate_count >= self.duplicate_threshold  # 如果重复次数达到阈值则返回True

    @property
    def messages(self) -> List[Message]:
        """获取代理内存中的消息列表

        Returns:
            List[Message]: 消息列表
        """
        return self.memory.messages  # 返回内存中的消息列表

    @messages.setter
    def messages(self, value: List[Message]):
        """设置代理内存中的消息列表

        Args:
            value: 要设置的消息列表
        """
        self.memory.messages = value  # 设置内存中的消息列表
