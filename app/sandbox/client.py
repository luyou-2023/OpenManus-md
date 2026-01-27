from abc import ABC, abstractmethod  # 抽象基类和抽象方法装饰器
from typing import Dict, Optional, Protocol  # 类型提示和协议类型

from app.config import SandboxSettings  # 沙箱配置
from app.sandbox.core.sandbox import DockerSandbox  # Docker沙箱实现


class SandboxFileOperations(Protocol):
    """沙箱文件操作协议

    定义了沙箱文件操作的接口，使用Protocol类型进行结构化类型检查。
    """

    async def copy_from(self, container_path: str, local_path: str) -> None:
        """从容器复制文件到本地

        Args:
            container_path: 容器中的文件路径
            local_path: 本地目标路径
        """
        ...  # 协议方法，不需要实现

    async def copy_to(self, local_path: str, container_path: str) -> None:
        """从本地复制文件到容器

        Args:
            local_path: 本地源文件路径
            container_path: 容器中的目标路径
        """
        ...  # 协议方法，不需要实现

    async def read_file(self, path: str) -> str:
        """从容器读取文件内容

        Args:
            path: 容器中的文件路径

        Returns:
            str: 文件内容
        """
        ...  # 协议方法，不需要实现

    async def write_file(self, path: str, content: str) -> None:
        """向容器中的文件写入内容

        Args:
            path: 容器中的文件路径
            content: 要写入的内容
        """
        ...  # 协议方法，不需要实现


class BaseSandboxClient(ABC):
    """沙箱客户端基类接口

    定义了沙箱客户端的基本接口，所有沙箱客户端实现都必须实现这些方法。
    """

    @abstractmethod
    async def create(
        self,
        config: Optional[SandboxSettings] = None,
        volume_bindings: Optional[Dict[str, str]] = None,
    ) -> None:
        """创建沙箱

        Args:
            config: 沙箱配置，可选
            volume_bindings: 卷绑定映射，可选
        """

    @abstractmethod
    async def run_command(self, command: str, timeout: Optional[int] = None) -> str:
        """执行命令

        Args:
            command: 要执行的命令
            timeout: 执行超时时间（秒），可选

        Returns:
            str: 命令输出
        """

    @abstractmethod
    async def copy_from(self, container_path: str, local_path: str) -> None:
        """从容器复制文件

        Args:
            container_path: 容器中的文件路径
            local_path: 本地目标路径
        """

    @abstractmethod
    async def copy_to(self, local_path: str, container_path: str) -> None:
        """复制文件到容器

        Args:
            local_path: 本地源文件路径
            container_path: 容器中的目标路径
        """

    @abstractmethod
    async def read_file(self, path: str) -> str:
        """读取文件

        Args:
            path: 容器中的文件路径

        Returns:
            str: 文件内容
        """

    @abstractmethod
    async def write_file(self, path: str, content: str) -> None:
        """写入文件

        Args:
            path: 容器中的文件路径
            content: 文件内容
        """

    @abstractmethod
    async def cleanup(self) -> None:
        """清理资源

        释放沙箱占用的资源，如停止容器、删除卷等。
        """


class LocalSandboxClient(BaseSandboxClient):
    """本地沙箱客户端实现类

    基于Docker的本地沙箱客户端实现。
    提供代码执行的隔离环境。
    """

    def __init__(self):
        """初始化本地沙箱客户端"""
        self.sandbox: Optional[DockerSandbox] = None  # Docker沙箱实例，初始为None

    async def create(
        self,
        config: Optional[SandboxSettings] = None,
        volume_bindings: Optional[Dict[str, str]] = None,
    ) -> None:
        """创建沙箱

        Args:
            config: 沙箱配置，可选
            volume_bindings: 卷绑定映射，可选

        Raises:
            RuntimeError: 如果沙箱创建失败
        """
        self.sandbox = DockerSandbox(config, volume_bindings)  # 创建Docker沙箱实例
        await self.sandbox.create()  # 异步创建沙箱（启动容器）

    async def run_command(self, command: str, timeout: Optional[int] = None) -> str:
        """在沙箱中运行命令

        Args:
            command: 要执行的命令
            timeout: 执行超时时间（秒），可选

        Returns:
            str: 命令输出

        Raises:
            RuntimeError: 如果沙箱未初始化
        """
        if not self.sandbox:  # 如果沙箱未初始化
            raise RuntimeError("Sandbox not initialized")  # 抛出运行时错误
        return await self.sandbox.run_command(command, timeout)  # 在沙箱中执行命令

    async def copy_from(self, container_path: str, local_path: str) -> None:
        """从容器复制文件到本地

        Args:
            container_path: 容器中的文件路径
            local_path: 本地目标路径

        Raises:
            RuntimeError: 如果沙箱未初始化
        """
        if not self.sandbox:  # 如果沙箱未初始化
            raise RuntimeError("Sandbox not initialized")  # 抛出运行时错误
        await self.sandbox.copy_from(container_path, local_path)  # 从容器复制文件

    async def copy_to(self, local_path: str, container_path: str) -> None:
        """从本地复制文件到容器

        Args:
            local_path: 本地源文件路径
            container_path: 容器中的目标路径

        Raises:
            RuntimeError: 如果沙箱未初始化
        """
        if not self.sandbox:  # 如果沙箱未初始化
            raise RuntimeError("Sandbox not initialized")  # 抛出运行时错误
        await self.sandbox.copy_to(local_path, container_path)  # 复制文件到容器

    async def read_file(self, path: str) -> str:
        """从容器读取文件

        Args:
            path: 容器中的文件路径

        Returns:
            str: 文件内容

        Raises:
            RuntimeError: 如果沙箱未初始化
        """
        if not self.sandbox:  # 如果沙箱未初始化
            raise RuntimeError("Sandbox not initialized")  # 抛出运行时错误
        return await self.sandbox.read_file(path)  # 从容器读取文件

    async def write_file(self, path: str, content: str) -> None:
        """向容器写入文件

        Args:
            path: 容器中的文件路径
            content: 文件内容

        Raises:
            RuntimeError: 如果沙箱未初始化
        """
        if not self.sandbox:  # 如果沙箱未初始化
            raise RuntimeError("Sandbox not initialized")  # 抛出运行时错误
        await self.sandbox.write_file(path, content)  # 向容器写入文件

    async def cleanup(self) -> None:
        """清理资源

        停止并删除Docker容器，释放资源。
        """
        if self.sandbox:  # 如果沙箱存在
            await self.sandbox.cleanup()  # 清理沙箱资源
            self.sandbox = None  # 将沙箱实例设置为None


def create_sandbox_client() -> LocalSandboxClient:
    """创建沙箱客户端

    工厂函数，用于创建沙箱客户端实例。

    Returns:
        LocalSandboxClient: 沙箱客户端实例
    """
    return LocalSandboxClient()  # 创建并返回本地沙箱客户端实例


SANDBOX_CLIENT = create_sandbox_client()  # 创建全局沙箱客户端单例
