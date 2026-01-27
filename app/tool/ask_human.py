from app.tool import BaseTool  # 工具基类


class AskHuman(BaseTool):
    """人工交互工具类

    添加一个工具来向人类寻求帮助。
    当代理需要人工输入或确认时，可以使用此工具。
    """

    name: str = "ask_human"  # 工具名称
    description: str = "Use this tool to ask human for help."  # 工具描述
    parameters: str = {
        "type": "object",  # 参数类型为对象
        "properties": {
            "inquire": {
                "type": "string",  # 询问内容类型为字符串
                "description": "The question you want to ask human.",  # 询问描述
            }
        },
        "required": ["inquire"],  # 必需参数：inquire
    }

    async def execute(self, inquire: str) -> str:
        """执行人工询问

        向用户显示询问信息并等待输入。

        Args:
            inquire: 要询问的问题

        Returns:
            str: 用户的回复（去除首尾空白）
        """
        return input(f"""Bot: {inquire}\n\nYou: """).strip()  # 显示询问并获取用户输入，去除首尾空白
