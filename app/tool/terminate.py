from app.tool.base import BaseTool  # 工具基类


_TERMINATE_DESCRIPTION = """Terminate the interaction when the request is met OR if the assistant cannot proceed further with the task.
When you have finished all the tasks, call this tool to end the work."""  # 终止工具的描述文本


class Terminate(BaseTool):
    """终止工具类

    用于终止代理的执行。当任务完成或无法继续时，代理可以调用此工具来结束工作。
    """
    name: str = "terminate"  # 工具名称
    description: str = _TERMINATE_DESCRIPTION  # 工具描述
    parameters: dict = {
        "type": "object",  # 参数类型为对象
        "properties": {
            "status": {
                "type": "string",  # 状态类型为字符串
                "description": "The finish status of the interaction.",  # 状态描述
                "enum": ["success", "failure"],  # 状态枚举值：成功或失败
            }
        },
        "required": ["status"],  # 必需参数：status
    }

    async def execute(self, status: str) -> str:
        """完成当前执行

        Args:
            status: 完成状态（"success"或"failure"）

        Returns:
            str: 完成消息
        """
        return f"The interaction has been completed with status: {status}"  # 返回完成消息
