from enum import Enum  # 枚举类型，用于定义固定值的集合
from typing import Any, List, Literal, Optional, Union  # 类型提示工具

from pydantic import BaseModel, Field  # Pydantic数据验证库


class Role(str, Enum):
    """消息角色枚举类

    定义了对话中消息的角色类型，用于标识消息的发送者类型
    """

    SYSTEM = "system"  # 系统消息角色，用于系统指令和提示
    USER = "user"  # 用户消息角色，表示用户输入
    ASSISTANT = "assistant"  # 助手消息角色，表示AI助手的回复
    TOOL = "tool"  # 工具消息角色，表示工具执行的结果


ROLE_VALUES = tuple(role.value for role in Role)  # 将所有角色值提取为元组，用于类型检查
ROLE_TYPE = Literal[ROLE_VALUES]  # type: ignore  # 创建字面量类型，限制只能使用ROLE_VALUES中的值


class ToolChoice(str, Enum):
    """工具选择策略枚举类

    定义了LLM在函数调用时的工具选择策略
    """

    NONE = "none"  # 不使用工具，LLM只能返回文本回复
    AUTO = "auto"  # 自动选择，LLM可以决定是否使用工具
    REQUIRED = "required"  # 必须使用工具，LLM必须调用至少一个工具


TOOL_CHOICE_VALUES = tuple(choice.value for choice in ToolChoice)  # 将所有工具选择值提取为元组
TOOL_CHOICE_TYPE = Literal[TOOL_CHOICE_VALUES]  # type: ignore  # 创建字面量类型，限制只能使用TOOL_CHOICE_VALUES中的值


class AgentState(str, Enum):
    """代理执行状态枚举类

    定义了代理在执行过程中的各种状态
    """

    IDLE = "IDLE"  # 空闲状态，代理未在执行任务
    RUNNING = "RUNNING"  # 运行状态，代理正在执行任务
    FINISHED = "FINISHED"  # 完成状态，代理已完成任务
    ERROR = "ERROR"  # 错误状态，代理执行过程中发生错误


class Function(BaseModel):
    """函数调用信息模型类

    表示一个函数调用的基本信息
    """
    name: str  # 函数名称
    arguments: str  # 函数参数（JSON字符串格式）


class ToolCall(BaseModel):
    """工具调用模型类

    表示消息中的一个工具/函数调用，包含调用ID、类型和函数信息
    """

    id: str  # 工具调用的唯一标识符
    type: str = "function"  # 调用类型，默认为"function"
    function: Function  # 函数调用信息对象


class Message(BaseModel):
    """消息模型类

    表示对话中的一条消息，支持文本、工具调用和多模态内容
    """

    role: ROLE_TYPE = Field(...)  # type: ignore  # 消息角色，必填字段，必须是Role枚举值之一
    content: Optional[str] = Field(default=None)  # 消息文本内容，可选
    tool_calls: Optional[List[ToolCall]] = Field(default=None)  # 工具调用列表，可选，用于助手消息中包含的工具调用
    name: Optional[str] = Field(default=None)  # 消息名称，可选，用于工具消息标识工具名称
    tool_call_id: Optional[str] = Field(default=None)  # 工具调用ID，可选，用于工具消息关联对应的工具调用
    base64_image: Optional[str] = Field(default=None)  # Base64编码的图像数据，可选，用于多模态输入

    def __add__(self, other) -> List["Message"]:
        """支持 Message + list 或 Message + Message 的操作

        重载加法运算符，允许将Message对象与列表或其他Message对象相加

        Args:
            other: 要相加的对象（list或Message）

        Returns:
            List[Message]: 包含当前消息和other的消息列表

        Raises:
            TypeError: 如果other不是list或Message类型
        """
        if isinstance(other, list):  # 如果other是列表
            return [self] + other  # 返回包含当前消息和列表所有元素的新列表
        elif isinstance(other, Message):  # 如果other是Message对象
            return [self, other]  # 返回包含两个消息的列表
        else:  # 其他类型不支持
            raise TypeError(
                f"unsupported operand type(s) for +: '{type(self).__name__}' and '{type(other).__name__}'"
            )  # 抛出类型错误

    def __radd__(self, other) -> List["Message"]:
        """支持 list + Message 的操作（右加法）

        当列表在左侧，Message在右侧时调用此方法

        Args:
            other: 左侧的列表对象

        Returns:
            List[Message]: 包含列表元素和当前消息的新列表

        Raises:
            TypeError: 如果other不是list类型
        """
        if isinstance(other, list):  # 如果other是列表
            return other + [self]  # 返回列表元素加上当前消息的新列表
        else:  # 其他类型不支持
            raise TypeError(
                f"unsupported operand type(s) for +: '{type(other).__name__}' and '{type(self).__name__}'"
            )  # 抛出类型错误

    def to_dict(self) -> dict:
        """将消息转换为字典格式

        用于序列化消息对象，只包含非None的字段

        Returns:
            dict: 消息的字典表示
        """
        message = {"role": self.role}  # 创建基础字典，包含角色
        if self.content is not None:  # 如果内容不为None
            message["content"] = self.content  # 添加内容字段
        if self.tool_calls is not None:  # 如果工具调用列表不为None
            message["tool_calls"] = [tool_call.dict() for tool_call in self.tool_calls]  # 将工具调用列表转换为字典列表
        if self.name is not None:  # 如果名称不为None
            message["name"] = self.name  # 添加名称字段
        if self.tool_call_id is not None:  # 如果工具调用ID不为None
            message["tool_call_id"] = self.tool_call_id  # 添加工具调用ID字段
        if self.base64_image is not None:  # 如果图像数据不为None
            message["base64_image"] = self.base64_image  # 添加图像数据字段
        return message  # 返回完整的消息字典

    @classmethod
    def user_message(
        cls, content: str, base64_image: Optional[str] = None
    ) -> "Message":
        """创建用户消息的类方法

        Args:
            content: 消息文本内容
            base64_image: 可选的Base64编码图像

        Returns:
            Message: 用户角色的消息对象
        """
        return cls(role=Role.USER, content=content, base64_image=base64_image)  # 创建用户角色消息

    @classmethod
    def system_message(cls, content: str) -> "Message":
        """创建系统消息的类方法

        Args:
            content: 系统消息内容

        Returns:
            Message: 系统角色的消息对象
        """
        return cls(role=Role.SYSTEM, content=content)  # 创建系统角色消息

    @classmethod
    def assistant_message(
        cls, content: Optional[str] = None, base64_image: Optional[str] = None
    ) -> "Message":
        """创建助手消息的类方法

        Args:
            content: 可选的助手回复内容
            base64_image: 可选的Base64编码图像

        Returns:
            Message: 助手角色的消息对象
        """
        return cls(role=Role.ASSISTANT, content=content, base64_image=base64_image)  # 创建助手角色消息

    @classmethod
    def tool_message(
        cls, content: str, name, tool_call_id: str, base64_image: Optional[str] = None
    ) -> "Message":
        """创建工具消息的类方法

        Args:
            content: 工具执行结果内容
            name: 工具名称
            tool_call_id: 关联的工具调用ID
            base64_image: 可选的Base64编码图像（工具可能返回图像）

        Returns:
            Message: 工具角色的消息对象
        """
        return cls(
            role=Role.TOOL,  # 工具角色
            content=content,  # 工具执行结果
            name=name,  # 工具名称
            tool_call_id=tool_call_id,  # 关联的工具调用ID
            base64_image=base64_image,  # 可选的图像数据
        )

    @classmethod
    def from_tool_calls(
        cls,
        tool_calls: List[Any],
        content: Union[str, List[str]] = "",
        base64_image: Optional[str] = None,
        **kwargs,
    ):
        """从原始工具调用创建包含工具调用的助手消息

        用于将LLM返回的工具调用转换为Message对象

        Args:
            tool_calls: LLM返回的原始工具调用列表
            content: 可选的消息内容（字符串或字符串列表）
            base64_image: 可选的Base64编码图像
            **kwargs: 其他额外参数

        Returns:
            Message: 包含工具调用的助手消息对象
        """
        formatted_calls = [
            {"id": call.id, "function": call.function.model_dump(), "type": "function"}  # 格式化每个工具调用
            for call in tool_calls  # 遍历所有工具调用
        ]  # 将工具调用对象转换为字典格式
        return cls(
            role=Role.ASSISTANT,  # 助手角色
            content=content,  # 消息内容
            tool_calls=formatted_calls,  # 格式化后的工具调用列表
            base64_image=base64_image,  # 可选的图像数据
            **kwargs,  # 其他参数
        )


class Memory(BaseModel):
    """内存模型类

    用于存储和管理对话历史消息，支持消息数量限制
    """
    messages: List[Message] = Field(default_factory=list)  # 消息列表，默认使用空列表工厂函数
    max_messages: int = Field(default=100)  # 最大消息数量限制，默认100条

    def add_message(self, message: Message) -> None:
        """向内存中添加一条消息

        如果超过最大消息数量限制，会保留最近的max_messages条消息

        Args:
            message: 要添加的消息对象
        """
        self.messages.append(message)  # 将消息添加到列表末尾
        # 可选：实现消息数量限制
        if len(self.messages) > self.max_messages:  # 如果消息数量超过限制
            self.messages = self.messages[-self.max_messages :]  # 只保留最近的max_messages条消息

    def add_messages(self, messages: List[Message]) -> None:
        """向内存中添加多条消息

        批量添加消息，如果超过最大消息数量限制，会保留最近的max_messages条消息

        Args:
            messages: 要添加的消息列表
        """
        self.messages.extend(messages)  # 将消息列表扩展到当前消息列表
        # 可选：实现消息数量限制
        if len(self.messages) > self.max_messages:  # 如果消息数量超过限制
            self.messages = self.messages[-self.max_messages :]  # 只保留最近的max_messages条消息

    def clear(self) -> None:
        """清空所有消息

        移除内存中的所有消息
        """
        self.messages.clear()  # 清空消息列表

    def get_recent_messages(self, n: int) -> List[Message]:
        """获取最近的n条消息

        Args:
            n: 要获取的消息数量

        Returns:
            List[Message]: 最近的n条消息列表
        """
        return self.messages[-n:]  # 返回列表的最后n个元素

    def to_dict_list(self) -> List[dict]:
        """将消息列表转换为字典列表

        用于序列化内存中的所有消息

        Returns:
            List[dict]: 消息字典列表
        """
        return [msg.to_dict() for msg in self.messages]  # 遍历所有消息并转换为字典
