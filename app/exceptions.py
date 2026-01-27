class ToolError(Exception):
    """工具执行错误异常类

    当工具执行过程中遇到错误时抛出此异常
    """

    def __init__(self, message):
        """初始化工具错误异常

        Args:
            message (str): 错误消息描述
        """
        self.message = message  # 保存错误消息
        super().__init__(self.message)  # 调用父类构造函数


class OpenManusError(Exception):
    """OpenManus基础异常类

    所有OpenManus相关异常的基类，用于统一异常类型
    """


class TokenLimitExceeded(OpenManusError):
    """Token限制超出异常类

    当LLM请求的token数量超过配置的限制时抛出此异常
    继承自OpenManusError
    """
