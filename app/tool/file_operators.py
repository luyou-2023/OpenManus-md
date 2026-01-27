"""文件操作接口和实现，用于本地和沙箱环境。"""

import asyncio  # 异步IO库，用于异步子进程
from pathlib import Path  # 路径操作库
from typing import Optional, Protocol, Tuple, Union, runtime_checkable  # 类型提示和协议类型

from app.config import SandboxSettings  # 沙箱配置
from app.exceptions import ToolError  # 工具错误异常
from app.sandbox.client import SANDBOX_CLIENT  # 沙箱客户端单例


PathLike = Union[str, Path]  # 路径类型别名，可以是字符串或Path对象


@runtime_checkable
class FileOperator(Protocol):
    """文件操作接口协议

    定义在不同环境中进行文件操作的接口。
    使用Protocol类型进行结构化类型检查。
    """

    async def read_file(self, path: PathLike) -> str:
        """从文件读取内容

        Args:
            path: 文件路径

        Returns:
            str: 文件内容
        """
        ...  # 协议方法，不需要实现

    async def write_file(self, path: PathLike, content: str) -> None:
        """向文件写入内容

        Args:
            path: 文件路径
            content: 要写入的内容
        """
        ...  # 协议方法，不需要实现

    async def is_directory(self, path: PathLike) -> bool:
        """检查路径是否指向目录

        Args:
            path: 路径

        Returns:
            bool: 如果是目录返回True，否则返回False
        """
        ...  # 协议方法，不需要实现

    async def exists(self, path: PathLike) -> bool:
        """检查路径是否存在

        Args:
            path: 路径

        Returns:
            bool: 如果存在返回True，否则返回False
        """
        ...  # 协议方法，不需要实现

    async def run_command(
        self, cmd: str, timeout: Optional[float] = 120.0
    ) -> Tuple[int, str, str]:
        """运行shell命令并返回（返回码，标准输出，标准错误）

        Args:
            cmd: 要执行的命令
            timeout: 超时时间（秒），可选

        Returns:
            Tuple[int, str, str]: (返回码, 标准输出, 标准错误)
        """
        ...  # 协议方法，不需要实现


class LocalFileOperator(FileOperator):
    """本地文件系统文件操作实现类

    实现本地文件系统的文件操作接口。
    """

    encoding: str = "utf-8"  # 文件编码，默认为UTF-8

    async def read_file(self, path: PathLike) -> str:
        """从本地文件读取内容

        Args:
            path: 文件路径

        Returns:
            str: 文件内容

        Raises:
            ToolError: 如果读取失败
        """
        try:
            return Path(path).read_text(encoding=self.encoding)  # 读取文件内容
        except Exception as e:  # 捕获任何异常
            raise ToolError(f"Failed to read {path}: {str(e)}") from None  # 抛出工具错误

    async def write_file(self, path: PathLike, content: str) -> None:
        """向本地文件写入内容

        Args:
            path: 文件路径
            content: 要写入的内容

        Raises:
            ToolError: 如果写入失败
        """
        try:
            Path(path).write_text(content, encoding=self.encoding)  # 写入文件内容
        except Exception as e:  # 捕获任何异常
            raise ToolError(f"Failed to write to {path}: {str(e)}") from None  # 抛出工具错误

    async def is_directory(self, path: PathLike) -> bool:
        """检查路径是否指向目录

        Args:
            path: 路径

        Returns:
            bool: 如果是目录返回True，否则返回False
        """
        return Path(path).is_dir()  # 检查是否为目录

    async def exists(self, path: PathLike) -> bool:
        """检查路径是否存在

        Args:
            path: 路径

        Returns:
            bool: 如果存在返回True，否则返回False
        """
        return Path(path).exists()  # 检查路径是否存在

    async def run_command(
        self, cmd: str, timeout: Optional[float] = 120.0
    ) -> Tuple[int, str, str]:
        """在本地运行shell命令

        Args:
            cmd: 要执行的命令
            timeout: 超时时间（秒），可选

        Returns:
            Tuple[int, str, str]: (返回码, 标准输出, 标准错误)

        Raises:
            TimeoutError: 如果命令超时
        """
        process = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE  # 创建异步子进程
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout  # 等待进程完成，带超时
            )
            return (
                process.returncode or 0,  # 返回码，如果为None则返回0
                stdout.decode(),  # 解码标准输出
                stderr.decode(),  # 解码标准错误
            )
        except asyncio.TimeoutError as exc:  # 如果超时
            try:
                process.kill()  # 终止进程
            except ProcessLookupError:  # 如果进程不存在
                pass  # 忽略错误
            raise TimeoutError(
                f"Command '{cmd}' timed out after {timeout} seconds"  # 抛出超时错误
            ) from exc


class SandboxFileOperator(FileOperator):
    """沙箱环境文件操作实现类

    实现沙箱环境的文件操作接口。
    使用Docker沙箱进行文件操作。
    """

    def __init__(self):
        """初始化沙箱文件操作器"""
        self.sandbox_client = SANDBOX_CLIENT  # 使用全局沙箱客户端单例

    async def _ensure_sandbox_initialized(self):
        """确保沙箱已初始化

        如果沙箱未初始化，则创建新的沙箱实例。
        """
        if not self.sandbox_client.sandbox:  # 如果沙箱未初始化
            await self.sandbox_client.create(config=SandboxSettings())  # 创建沙箱

    async def read_file(self, path: PathLike) -> str:
        """从沙箱中的文件读取内容

        Args:
            path: 文件路径

        Returns:
            str: 文件内容

        Raises:
            ToolError: 如果读取失败
        """
        await self._ensure_sandbox_initialized()  # 确保沙箱已初始化
        try:
            return await self.sandbox_client.read_file(str(path))  # 从沙箱读取文件
        except Exception as e:  # 捕获任何异常
            raise ToolError(f"Failed to read {path} in sandbox: {str(e)}") from None  # 抛出工具错误

    async def write_file(self, path: PathLike, content: str) -> None:
        """向沙箱中的文件写入内容

        Args:
            path: 文件路径
            content: 要写入的内容

        Raises:
            ToolError: 如果写入失败
        """
        await self._ensure_sandbox_initialized()  # 确保沙箱已初始化
        try:
            await self.sandbox_client.write_file(str(path), content)  # 向沙箱写入文件
        except Exception as e:  # 捕获任何异常
            raise ToolError(f"Failed to write to {path} in sandbox: {str(e)}") from None  # 抛出工具错误

    async def is_directory(self, path: PathLike) -> bool:
        """检查沙箱中的路径是否指向目录

        Args:
            path: 路径

        Returns:
            bool: 如果是目录返回True，否则返回False
        """
        await self._ensure_sandbox_initialized()  # 确保沙箱已初始化
        result = await self.sandbox_client.run_command(
            f"test -d {path} && echo 'true' || echo 'false'"  # 使用test命令检查是否为目录
        )
        return result.strip() == "true"  # 返回检查结果

    async def exists(self, path: PathLike) -> bool:
        """检查沙箱中的路径是否存在

        Args:
            path: 路径

        Returns:
            bool: 如果存在返回True，否则返回False
        """
        await self._ensure_sandbox_initialized()  # 确保沙箱已初始化
        result = await self.sandbox_client.run_command(
            f"test -e {path} && echo 'true' || echo 'false'"  # 使用test命令检查路径是否存在
        )
        return result.strip() == "true"  # 返回检查结果

    async def run_command(
        self, cmd: str, timeout: Optional[float] = 120.0
    ) -> Tuple[int, str, str]:
        """在沙箱环境中运行命令

        Args:
            cmd: 要执行的命令
            timeout: 超时时间（秒），可选

        Returns:
            Tuple[int, str, str]: (返回码, 标准输出, 标准错误)

        Raises:
            TimeoutError: 如果命令超时
        """
        await self._ensure_sandbox_initialized()  # 确保沙箱已初始化
        try:
            stdout = await self.sandbox_client.run_command(
                cmd, timeout=int(timeout) if timeout else None  # 在沙箱中运行命令
            )
            return (
                0,  # 始终返回0，因为当前沙箱实现没有显式的返回码
                stdout,  # 标准输出
                "",  # 当前沙箱实现中没有标准错误捕获
            )
        except TimeoutError as exc:  # 如果超时
            raise TimeoutError(
                f"Command '{cmd}' timed out after {timeout} seconds in sandbox"  # 抛出超时错误
            ) from exc
        except Exception as exc:  # 如果其他异常
            return 1, "", f"Error executing command in sandbox: {str(exc)}"  # 返回错误信息
