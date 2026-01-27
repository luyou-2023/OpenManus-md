from typing import Any, List, Optional, Type, Union, get_args, get_origin  # 类型提示和类型检查工具

from pydantic import BaseModel, Field  # Pydantic数据验证库

from app.tool import BaseTool  # 工具基类


class CreateChatCompletion(BaseTool):
    """创建聊天完成工具类

    创建具有指定输出格式的结构化完成。
    支持根据响应类型动态构建参数Schema。
    """
    name: str = "create_chat_completion"  # 工具名称
    description: str = (
        "Creates a structured completion with specified output formatting."  # 工具描述
    )

    # JSON Schema的类型映射
    type_mapping: dict = {
        str: "string",  # 字符串类型映射
        int: "integer",  # 整数类型映射
        float: "number",  # 浮点数类型映射
        bool: "boolean",  # 布尔类型映射
        dict: "object",  # 字典类型映射
        list: "array",  # 列表类型映射
    }
    response_type: Optional[Type] = None  # 响应类型，可选
    required: List[str] = Field(default_factory=lambda: ["response"])  # 必需字段列表，默认为["response"]

    def __init__(self, response_type: Optional[Type] = str):
        """使用特定响应类型初始化

        Args:
            response_type: 响应类型，默认为str
        """
        super().__init__()  # 调用父类构造函数
        self.response_type = response_type  # 设置响应类型
        self.parameters = self._build_parameters()  # 根据响应类型构建参数Schema

    def _build_parameters(self) -> dict:
        """基于响应类型构建参数Schema

        Returns:
            dict: JSON Schema格式的参数定义
        """
        if self.response_type == str:  # 如果响应类型为字符串
            return {
                "type": "object",  # 对象类型
                "properties": {
                    "response": {
                        "type": "string",  # 字符串类型
                        "description": "The response text that should be delivered to the user.",  # 响应描述
                    },
                },
                "required": self.required,  # 必需字段
            }

        if isinstance(self.response_type, type) and issubclass(
            self.response_type, BaseModel
        ):  # 如果响应类型是Pydantic模型
            schema = self.response_type.model_json_schema()  # 获取模型的JSON Schema
            return {
                "type": "object",  # 对象类型
                "properties": schema["properties"],  # 使用模型的属性
                "required": schema.get("required", self.required),  # 使用模型的必需字段或默认值
            }

        return self._create_type_schema(self.response_type)  # 否则创建类型Schema

    def _create_type_schema(self, type_hint: Type) -> dict:
        """为给定类型创建JSON Schema

        Args:
            type_hint: 类型提示

        Returns:
            dict: JSON Schema字典
        """
        origin = get_origin(type_hint)  # 获取类型的原始类型（如List、Dict、Union等）
        args = get_args(type_hint)  # 获取类型参数（如List[str]中的str）

        # 处理原始类型（非泛型）
        if origin is None:  # 如果是原始类型（如str、int等）
            return {
                "type": "object",  # 对象类型
                "properties": {
                    "response": {
                        "type": self.type_mapping.get(type_hint, "string"),  # 从类型映射获取JSON Schema类型
                        "description": f"Response of type {type_hint.__name__}",  # 类型描述
                    }
                },
                "required": self.required,  # 必需字段
            }

        # 处理List类型
        if origin is list:  # 如果原始类型是list
            item_type = args[0] if args else Any  # 获取列表元素类型，如果没有参数则使用Any
            return {
                "type": "object",  # 对象类型
                "properties": {
                    "response": {
                        "type": "array",  # 数组类型
                        "items": self._get_type_info(item_type),  # 数组元素类型信息
                    }
                },
                "required": self.required,  # 必需字段
            }

        # 处理Dict类型
        if origin is dict:  # 如果原始类型是dict
            value_type = args[1] if len(args) > 1 else Any  # 获取字典值类型，如果没有第二个参数则使用Any
            return {
                "type": "object",  # 对象类型
                "properties": {
                    "response": {
                        "type": "object",  # 对象类型
                        "additionalProperties": self._get_type_info(value_type),  # 字典值类型信息
                    }
                },
                "required": self.required,  # 必需字段
            }

        # 处理Union类型
        if origin is Union:  # 如果原始类型是Union
            return self._create_union_schema(args)  # 创建Union类型的Schema

        return self._build_parameters()  # 默认情况，重新构建参数

    def _get_type_info(self, type_hint: Type) -> dict:
        """获取单个类型的类型信息

        Args:
            type_hint: 类型提示

        Returns:
            dict: 类型信息字典
        """
        if isinstance(type_hint, type) and issubclass(type_hint, BaseModel):  # 如果是Pydantic模型
            return type_hint.model_json_schema()  # 返回模型的JSON Schema

        return {
            "type": self.type_mapping.get(type_hint, "string"),  # 从类型映射获取类型
            "description": f"Value of type {getattr(type_hint, '__name__', 'any')}",  # 类型描述
        }

    def _create_union_schema(self, types: tuple) -> dict:
        """为Union类型创建Schema

        Args:
            types: Union类型的类型元组

        Returns:
            dict: Union类型的JSON Schema
        """
        return {
            "type": "object",  # 对象类型
            "properties": {
                "response": {"anyOf": [self._get_type_info(t) for t in types]}  # 使用anyOf表示Union类型
            },
            "required": self.required,  # 必需字段
        }

    async def execute(self, required: list | None = None, **kwargs) -> Any:
        """执行聊天完成，带类型转换

        Args:
            required: 必需字段名称列表，可选
            **kwargs: 响应数据

        Returns:
            Any: 根据response_type转换后的响应
        """
        required = required or self.required  # 使用提供的required或默认值

        # 处理required是列表的情况
        if isinstance(required, list) and len(required) > 0:  # 如果required是列表且不为空
            if len(required) == 1:  # 如果只有一个必需字段
                required_field = required[0]  # 获取字段名
                result = kwargs.get(required_field, "")  # 获取字段值
            else:  # 如果有多个必需字段
                # 返回多个字段作为字典
                return {field: kwargs.get(field, "") for field in required}  # 返回字段字典
        else:  # 如果required不是列表或为空
            required_field = "response"  # 使用默认字段名
            result = kwargs.get(required_field, "")  # 获取字段值

        # 类型转换逻辑
        if self.response_type == str:  # 如果响应类型是字符串
            return result  # 直接返回结果

        if isinstance(self.response_type, type) and issubclass(
            self.response_type, BaseModel
        ):  # 如果响应类型是Pydantic模型
            return self.response_type(**kwargs)  # 使用kwargs创建模型实例

        if get_origin(self.response_type) in (list, dict):  # 如果响应类型是list或dict
            return result  # 假设结果已经是正确格式，直接返回

        try:
            return self.response_type(result)  # 尝试将结果转换为响应类型
        except (ValueError, TypeError):  # 如果转换失败
            return result  # 返回原始结果
