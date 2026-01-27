"""沙箱系统的异常类模块

此模块定义了在整个沙箱系统中使用的自定义异常，
以结构化的方式处理各种错误条件。
"""


class SandboxError(Exception):
    """沙箱相关错误的基础异常类

    所有沙箱相关异常的基类。
    """


class SandboxTimeoutError(SandboxError):
    """沙箱超时错误异常类

    当沙箱操作超时时抛出。
    """


class SandboxResourceError(SandboxError):
    """沙箱资源错误异常类

    当发生资源相关错误时抛出。
    """
