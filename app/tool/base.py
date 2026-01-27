import json  # JSON解析库，用于序列化字典数据
from abc import ABC, abstractmethod  # 抽象基类和抽象方法装饰器
from typing import Any, Dict, Optional, Union  # 类型提示

from pydantic import BaseModel, Field  # Pydantic数据验证库

from app.utils.logger import logger  # 日志记录器


# 以下是已注释的旧版BaseTool实现，保留作为参考
# class BaseTool(ABC, BaseModel):
#     name: str
#     description: str
#     parameters: Optional[dict] = None

#     class Config:
#         arbitrary_types_allowed = True

#     async def __call__(self, **kwargs) -> Any:
#         """Execute the tool with given parameters."""
#         return await self.execute(**kwargs)

#     @abstractmethod
#     async def execute(self, **kwargs) -> Any:
#         """Execute the tool with given parameters."""

#     def to_param(self) -> Dict:
#         """Convert tool to function call format."""
#         return {
#             "type": "function",
#             "function": {
#                 "name": self.name,
#                 "description": self.description,
#                 "parameters": self.parameters,
#             },
#         }


class ToolResult(BaseModel):
    """工具执行结果模型类

    表示工具执行的结果，支持成功输出、错误信息、图像数据和系统消息。
    """

    output: Any = Field(default=None)  # 成功输出，可以是任何类型，默认为None
    error: Optional[str] = Field(default=None)  # 错误信息，可选字符串
    base64_image: Optional[str] = Field(default=None)  # Base64编码的图像数据，可选
    system: Optional[str] = Field(default=None)  # 系统消息，可选字符串

    class Config:
        arbitrary_types_allowed = True  # 允许任意类型（用于output字段）

    def __bool__(self):
        """布尔值转换：如果任何字段有值则返回True

        Returns:
            bool: 如果任何字段有值返回True，否则返回False
        """
        return any(getattr(self, field) for field in self.__fields__)  # 检查任何字段是否有值

    def __add__(self, other: "ToolResult"):
        """加法运算符：合并两个ToolResult对象

        Args:
            other: 另一个ToolResult对象

        Returns:
            ToolResult: 合并后的新ToolResult对象

        Raises:
            ValueError: 如果无法合并某些字段（如图像数据）
        """
        def combine_fields(
            field: Optional[str], other_field: Optional[str], concatenate: bool = True
        ):
            """内部函数：合并两个字段值"""
            if field and other_field:  # 如果两个字段都有值
                if concatenate:  # 如果可以连接
                    return field + other_field  # 返回连接后的字符串
                raise ValueError("Cannot combine tool results")  # 否则抛出错误（如图像数据不能合并）
            return field or other_field  # 返回有值的字段

        return ToolResult(
            output=combine_fields(self.output, other.output),  # 合并输出
            error=combine_fields(self.error, other.error),  # 合并错误
            base64_image=combine_fields(self.base64_image, other.base64_image, False),  # 合并图像（不允许连接）
            system=combine_fields(self.system, other.system),  # 合并系统消息
        )

    def __str__(self):
        """字符串表示：如果有错误返回错误信息，否则返回输出

        Returns:
            str: 错误信息或输出内容
        """
        return f"Error: {self.error}" if self.error else self.output  # 优先返回错误信息

    def replace(self, **kwargs):
        """返回一个新ToolResult，用给定字段替换原有字段

        Args:
            **kwargs: 要替换的字段和值

        Returns:
            ToolResult: 新的ToolResult实例
        """
        # return self.copy(update=kwargs)  # 旧实现（已注释）
        return type(self)(**{**self.dict(), **kwargs})  # 创建新实例，合并原有字段和新字段


class BaseTool(ABC, BaseModel):
    """工具基类：整合了BaseModel和工具功能

    提供：
    - Pydantic模型验证
    - Schema注册（已注释）
    - 标准化结果处理
    - 抽象执行接口

    属性:
        name (str): 工具名称
        description (str): 工具描述
        parameters (dict): 工具参数Schema（JSON Schema格式）
        _schemas (Dict[str, List[ToolSchema]]): 注册的方法Schema（已注释）
    """

    name: str  # 工具名称，必填字段
    description: str  # 工具描述，必填字段
    parameters: Optional[dict] = None  # 工具参数Schema，可选，JSON Schema格式
    # _schemas: Dict[str, List[ToolSchema]] = {}  # Schema注册字典（已注释）

    class Config:
        arbitrary_types_allowed = True  # 允许任意类型
        underscore_attrs_are_private = False  # 下划线属性不是私有的

    # 以下是已注释的初始化方法，保留作为参考
    # def __init__(self, **data):
    #     """Initialize tool with model validation and schema registration."""
    #     super().__init__(**data)
    #     logger.debug(f"Initializing tool class: {self.__class__.__name__}")
    #     self._register_schemas()

    # def _register_schemas(self):
    #     """Register schemas from all decorated methods."""
    #     for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
    #         if hasattr(method, 'tool_schemas'):
    #             self._schemas[name] = method.tool_schemas
    #             logger.debug(f"Registered schemas for method '{name}' in {self.__class__.__name__}")

    async def __call__(self, **kwargs) -> Any:
        """调用运算符：使用给定参数执行工具

        Args:
            **kwargs: 工具参数

        Returns:
            Any: 工具执行结果
        """
        return await self.execute(**kwargs)  # 调用execute方法

    @abstractmethod
    async def execute(self, **kwargs) -> Any:
        """执行工具：使用给定参数执行工具逻辑

        抽象方法，必须由子类实现。

        Args:
            **kwargs: 工具参数

        Returns:
            Any: 工具执行结果（通常是ToolResult）
        """

    def to_param(self) -> Dict:
        """转换为函数调用格式

        将工具转换为OpenAI函数调用格式，用于LLM函数调用。

        Returns:
            Dict: 包含工具元数据的字典，符合OpenAI函数调用格式
        """
        return {
            "type": "function",  # 类型固定为"function"
            "function": {
                "name": self.name,  # 工具名称
                "description": self.description,  # 工具描述
                "parameters": self.parameters,  # 参数Schema
            },
        }

    # 以下是已注释的Schema获取方法，保留作为参考
    # def get_schemas(self) -> Dict[str, List[ToolSchema]]:
    #     """Get all registered tool schemas.

    #     Returns:
    #         Dict mapping method names to their schema definitions
    #     """
    #     return self._schemas

    def success_response(self, data: Union[Dict[str, Any], str]) -> ToolResult:
        """创建成功的工具结果

        Args:
            data: 结果数据（字典或字符串）

        Returns:
            ToolResult: 包含成功输出的ToolResult对象
        """
        if isinstance(data, str):  # 如果数据是字符串
            text = data  # 直接使用字符串
        else:  # 如果数据是字典
            text = json.dumps(data, indent=2)  # 将字典转换为格式化的JSON字符串
        logger.debug(f"Created success response for {self.__class__.__name__}")  # 记录调试日志
        return ToolResult(output=text)  # 返回成功结果

    def fail_response(self, msg: str) -> ToolResult:
        """创建失败的工具结果

        Args:
            msg: 描述失败的错误消息

        Returns:
            ToolResult: 包含错误信息的ToolResult对象
        """
        logger.debug(f"Tool {self.__class__.__name__} returned failed result: {msg}")  # 记录调试日志
        return ToolResult(error=msg)  # 返回失败结果


class CLIResult(ToolResult):
    """CLI结果类

    继承自ToolResult，表示可以作为CLI输出渲染的工具结果。
    """


class ToolFailure(ToolResult):
    """工具失败类

    继承自ToolResult，表示工具执行失败的结果。
    """
