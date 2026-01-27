import logging  # Python标准日志库
import sys  # 系统相关功能


logging.basicConfig(level=logging.INFO, handlers=[logging.StreamHandler(sys.stderr)])  # 配置基础日志，输出到标准错误

import argparse  # 命令行参数解析库
import asyncio  # 异步IO库，用于运行异步清理函数
import atexit  # 退出处理库，用于注册退出时的清理函数
import json  # JSON解析库，用于序列化工具结果
from inspect import Parameter, Signature  # 函数签名相关，用于构建工具方法的签名
from typing import Any, Dict, Optional  # 类型提示

from mcp.server.fastmcp import FastMCP  # FastMCP服务器框架

from app.logger import logger  # 应用日志记录器
from app.tool.base import BaseTool  # 工具基类
from app.tool.bash import Bash  # Bash工具
from app.tool.browser_use_tool import BrowserUseTool  # 浏览器工具
from app.tool.str_replace_editor import StrReplaceEditor  # 字符串替换编辑器工具
from app.tool.terminate import Terminate  # 终止工具


class MCPServer:
    """MCP服务器实现类

    实现Model Context Protocol服务器，提供工具注册和管理功能。
    将OpenManus的工具暴露为MCP工具，供MCP客户端调用。
    """

    def __init__(self, name: str = "openmanus"):
        """初始化MCP服务器

        Args:
            name: 服务器名称，默认为"openmanus"
        """
        self.server = FastMCP(name)  # 创建FastMCP服务器实例
        self.tools: Dict[str, BaseTool] = {}  # 工具字典，键为工具名称，值为工具对象

        # 初始化标准工具
        self.tools["bash"] = Bash()  # Bash命令执行工具
        self.tools["browser"] = BrowserUseTool()  # 浏览器自动化工具
        self.tools["editor"] = StrReplaceEditor()  # 文件编辑工具
        self.tools["terminate"] = Terminate()  # 终止工具

    def register_tool(self, tool: BaseTool, method_name: Optional[str] = None) -> None:
        """注册工具：使用参数验证和文档

        将工具注册到MCP服务器，创建异步方法包装器，并设置元数据。

        Args:
            tool: 要注册的工具对象
            method_name: 可选的方法名称，如果不提供则使用工具名称
        """
        tool_name = method_name or tool.name  # 使用方法名称或工具名称
        tool_param = tool.to_param()  # 将工具转换为LLM函数调用格式
        tool_function = tool_param["function"]  # 获取函数定义

        # 定义要注册的异步函数
        async def tool_method(**kwargs):  # 定义异步工具方法
            logger.info(f"Executing {tool_name}: {kwargs}")  # 记录执行日志
            result = await tool.execute(**kwargs)  # 执行工具

            logger.info(f"Result of {tool_name}: {result}")  # 记录结果日志

            # 处理不同类型的结果（匹配原始逻辑）
            if hasattr(result, "model_dump"):  # 如果结果是Pydantic模型
                return json.dumps(result.model_dump())  # 转换为JSON字符串
            elif isinstance(result, dict):  # 如果结果是字典
                return json.dumps(result)  # 转换为JSON字符串
            return result  # 否则直接返回结果

        # 设置方法元数据
        tool_method.__name__ = tool_name  # 设置方法名称
        tool_method.__doc__ = self._build_docstring(tool_function)  # 设置文档字符串
        tool_method.__signature__ = self._build_signature(tool_function)  # 设置函数签名

        # 存储参数Schema（对于需要以编程方式访问它的工具很重要）
        param_props = tool_function.get("parameters", {}).get("properties", {})  # 获取参数属性
        required_params = tool_function.get("parameters", {}).get("required", [])  # 获取必需参数列表
        tool_method._parameter_schema = {  # 设置参数Schema属性
            param_name: {
                "description": param_details.get("description", ""),  # 参数描述
                "type": param_details.get("type", "any"),  # 参数类型
                "required": param_name in required_params,  # 是否必需
            }
            for param_name, param_details in param_props.items()  # 遍历所有参数
        }

        # 注册到服务器
        self.server.tool()(tool_method)  # 使用FastMCP的tool装饰器注册方法
        logger.info(f"Registered tool: {tool_name}")  # 记录注册成功日志

    def _build_docstring(self, tool_function: dict) -> str:
        """从工具函数元数据构建格式化的文档字符串

        Args:
            tool_function: 工具函数定义字典

        Returns:
            str: 格式化的文档字符串
        """
        description = tool_function.get("description", "")  # 获取工具描述
        param_props = tool_function.get("parameters", {}).get("properties", {})  # 获取参数属性
        required_params = tool_function.get("parameters", {}).get("required", [])  # 获取必需参数列表

        # 构建文档字符串（匹配原始格式）
        docstring = description  # 从描述开始
        if param_props:  # 如果有参数
            docstring += "\n\nParameters:\n"  # 添加参数标题
            for param_name, param_details in param_props.items():  # 遍历所有参数
                required_str = (
                    "(required)" if param_name in required_params else "(optional)"  # 判断是否必需
                )
                param_type = param_details.get("type", "any")  # 获取参数类型
                param_desc = param_details.get("description", "")  # 获取参数描述
                docstring += (
                    f"    {param_name} ({param_type}) {required_str}: {param_desc}\n"  # 添加参数行
                )

        return docstring  # 返回完整的文档字符串

    def _build_signature(self, tool_function: dict) -> Signature:
        """从工具函数元数据构建函数签名

        Args:
            tool_function: 工具函数定义字典

        Returns:
            Signature: Python函数签名对象
        """
        param_props = tool_function.get("parameters", {}).get("properties", {})  # 获取参数属性
        required_params = tool_function.get("parameters", {}).get("required", [])  # 获取必需参数列表

        parameters = []  # 初始化参数列表

        # 遵循原始类型映射
        for param_name, param_details in param_props.items():  # 遍历所有参数
            param_type = param_details.get("type", "")  # 获取参数类型
            default = Parameter.empty if param_name in required_params else None  # 设置默认值（必需参数无默认值）

            # 将JSON Schema类型映射到Python类型（与原始逻辑相同）
            annotation = Any  # 默认类型为Any
            if param_type == "string":  # 如果是字符串类型
                annotation = str  # 映射到str
            elif param_type == "integer":  # 如果是整数类型
                annotation = int  # 映射到int
            elif param_type == "number":  # 如果是数字类型
                annotation = float  # 映射到float
            elif param_type == "boolean":  # 如果是布尔类型
                annotation = bool  # 映射到bool
            elif param_type == "object":  # 如果是对象类型
                annotation = dict  # 映射到dict
            elif param_type == "array":  # 如果是数组类型
                annotation = list  # 映射到list

            # 创建参数（与原始结构相同）
            param = Parameter(
                name=param_name,  # 参数名称
                kind=Parameter.KEYWORD_ONLY,  # 关键字参数类型
                default=default,  # 默认值
                annotation=annotation,  # 类型注解
            )
            parameters.append(param)  # 添加到参数列表

        return Signature(parameters=parameters)  # 返回函数签名

    async def cleanup(self) -> None:
        """清理服务器资源

        清理工具占用的资源，特别是浏览器工具。
        """
        logger.info("Cleaning up resources")  # 记录清理日志
        # 遵循原始清理逻辑 - 只清理浏览器工具
        if "browser" in self.tools and hasattr(self.tools["browser"], "cleanup"):  # 如果浏览器工具存在且有cleanup方法
            await self.tools["browser"].cleanup()  # 清理浏览器工具

    def register_all_tools(self) -> None:
        """向服务器注册所有工具

        遍历所有工具并注册到MCP服务器。
        """
        for tool in self.tools.values():  # 遍历所有工具
            self.register_tool(tool)  # 注册每个工具

    def run(self, transport: str = "stdio") -> None:
        """运行MCP服务器

        Args:
            transport: 传输方式，默认为"stdio"（标准输入输出）
        """
        # 注册所有工具
        self.register_all_tools()  # 注册所有工具到服务器

        # 注册清理函数（匹配原始行为）
        atexit.register(lambda: asyncio.run(self.cleanup()))  # 在程序退出时运行清理函数

        # 启动服务器（使用与原始相同的日志）
        logger.info(f"Starting OpenManus server ({transport} mode)")  # 记录启动日志
        self.server.run(transport=transport)  # 运行服务器


def parse_args() -> argparse.Namespace:
    """解析命令行参数

    Returns:
        argparse.Namespace: 解析后的参数对象
    """
    parser = argparse.ArgumentParser(description="OpenManus MCP Server")  # 创建参数解析器
    parser.add_argument(
        "--transport",  # 传输方式参数
        choices=["stdio"],  # 可选值列表
        default="stdio",  # 默认值
        help="Communication method: stdio or http (default: stdio)",  # 帮助信息
    )
    return parser.parse_args()  # 解析并返回参数


if __name__ == "__main__":
    args = parse_args()  # 解析命令行参数

    # 创建并运行服务器（保持原始流程）
    server = MCPServer()  # 创建MCP服务器实例
    server.run(transport=args.transport)  # 运行服务器
