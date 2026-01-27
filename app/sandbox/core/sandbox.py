import asyncio  # 异步IO库
import io  # IO操作库，用于创建内存中的字节流
import os  # 操作系统接口库
import tarfile  # tar文件操作库
import tempfile  # 临时文件和目录库
import uuid  # UUID生成库
from typing import Dict, Optional  # 类型提示

import docker  # Docker客户端库
from docker.errors import NotFound  # Docker未找到错误
from docker.models.containers import Container  # Docker容器模型

from app.config import SandboxSettings  # 沙箱配置
from app.sandbox.core.exceptions import SandboxTimeoutError  # 沙箱超时错误
from app.sandbox.core.terminal import AsyncDockerizedTerminal  # 异步Docker终端


class DockerSandbox:
    """Docker沙箱环境类

    提供容器化执行环境，具有资源限制、
    文件操作和命令执行能力。

    Attributes:
        config: 沙箱配置
        volume_bindings: 卷映射配置
        client: Docker客户端
        container: Docker容器实例
        terminal: 容器终端接口
    """

    def __init__(
        self,
        config: Optional[SandboxSettings] = None,
        volume_bindings: Optional[Dict[str, str]] = None,
    ):
        """初始化沙箱实例

        Args:
            config: 沙箱配置。如果为None则使用默认配置
            volume_bindings: 卷映射，格式为{host_path: container_path}
        """
        self.config = config or SandboxSettings()  # 使用提供的配置或默认配置
        self.volume_bindings = volume_bindings or {}  # 使用提供的卷绑定或空字典
        self.client = docker.from_env()  # 从环境变量创建Docker客户端
        self.container: Optional[Container] = None  # Docker容器实例，初始为None
        self.terminal: Optional[AsyncDockerizedTerminal] = None  # 异步终端实例，初始为None

    async def create(self) -> "DockerSandbox":
        """创建并启动沙箱容器

        Returns:
            DockerSandbox: 当前沙箱实例

        Raises:
            docker.errors.APIError: 如果Docker API调用失败
            RuntimeError: 如果容器创建或启动失败
        """
        try:
            # 准备容器配置
            host_config = self.client.api.create_host_config(
                mem_limit=self.config.memory_limit,  # 内存限制
                cpu_period=100000,  # CPU周期（微秒）
                cpu_quota=int(100000 * self.config.cpu_limit),  # CPU配额
                network_mode="none" if not self.config.network_enabled else "bridge",  # 网络模式：如果未启用网络则为none，否则为bridge
                binds=self._prepare_volume_bindings(),  # 卷绑定配置
            )

            # 生成唯一的容器名称，使用sandbox_前缀
            container_name = f"sandbox_{uuid.uuid4().hex[:8]}"  # 使用UUID的前8个字符

            # 创建容器
            container = await asyncio.to_thread(
                self.client.api.create_container,  # 在线程中执行Docker API调用
                image=self.config.image,  # Docker镜像
                command="tail -f /dev/null",  # 保持容器运行的命令
                hostname="sandbox",  # 主机名
                working_dir=self.config.work_dir,  # 工作目录
                host_config=host_config,  # 主机配置
                name=container_name,  # 容器名称
                tty=True,  # 分配伪终端
                detach=True,  # 后台运行
            )

            self.container = self.client.containers.get(container["Id"])  # 获取容器对象

            # 启动容器
            await asyncio.to_thread(self.container.start)  # 在线程中启动容器

            # 初始化终端
            self.terminal = AsyncDockerizedTerminal(
                container["Id"],  # 容器ID
                self.config.work_dir,  # 工作目录
                env_vars={"PYTHONUNBUFFERED": "1"}  # 环境变量：确保Python输出不被缓冲
            )
            await self.terminal.init()  # 初始化终端

            return self  # 返回自身

        except Exception as e:  # 捕获任何异常
            await self.cleanup()  # 确保资源被清理
            raise RuntimeError(f"Failed to create sandbox: {e}") from e  # 抛出运行时错误

    def _prepare_volume_bindings(self) -> Dict[str, Dict[str, str]]:
        """准备卷绑定配置

        Returns:
            Dict[str, Dict[str, str]]: 卷绑定配置字典
        """
        bindings = {}  # 初始化绑定字典

        # 创建并添加工作目录映射
        work_dir = self._ensure_host_dir(self.config.work_dir)  # 确保主机目录存在
        bindings[work_dir] = {"bind": self.config.work_dir, "mode": "rw"}  # 添加工作目录绑定，读写模式

        # 添加自定义卷绑定
        for host_path, container_path in self.volume_bindings.items():  # 遍历卷绑定配置
            bindings[host_path] = {"bind": container_path, "mode": "rw"}  # 添加自定义绑定，读写模式

        return bindings  # 返回绑定配置

    @staticmethod
    def _ensure_host_dir(path: str) -> str:
        """确保主机上的目录存在

        Args:
            path: 目录路径

        Returns:
            str: 主机上的实际路径
        """
        host_path = os.path.join(
            tempfile.gettempdir(),  # 临时目录
            f"sandbox_{os.path.basename(path)}_{os.urandom(4).hex()}",  # 生成唯一目录名
        )
        os.makedirs(host_path, exist_ok=True)  # 创建目录，如果已存在则不报错
        return host_path  # 返回主机路径

    async def run_command(self, cmd: str, timeout: Optional[int] = None) -> str:
        """在沙箱中运行命令

        Args:
            cmd: 要执行的命令
            timeout: 超时时间（秒），可选

        Returns:
            str: 命令输出字符串

        Raises:
            RuntimeError: 如果沙箱未初始化或命令执行失败
            SandboxTimeoutError: 如果命令执行超时
        """
        if not self.terminal:  # 如果终端未初始化
            raise RuntimeError("Sandbox not initialized")  # 抛出运行时错误

        try:
            return await self.terminal.run_command(
                cmd, timeout=timeout or self.config.timeout  # 在终端中运行命令，使用提供的超时或配置的超时
            )
        except TimeoutError:  # 如果超时
            raise SandboxTimeoutError(
                f"Command execution timed out after {timeout or self.config.timeout} seconds"  # 抛出沙箱超时错误
            )

    async def read_file(self, path: str) -> str:
        """从容器读取文件

        Args:
            path: 文件路径

        Returns:
            str: 文件内容字符串

        Raises:
            FileNotFoundError: 如果文件不存在
            RuntimeError: 如果读取操作失败
        """
        if not self.container:  # 如果容器未初始化
            raise RuntimeError("Sandbox not initialized")  # 抛出运行时错误

        try:
            # 获取文件归档
            resolved_path = self._safe_resolve_path(path)  # 安全解析路径
            tar_stream, _ = await asyncio.to_thread(
                self.container.get_archive, resolved_path  # 在线程中获取文件归档
            )

            # 从tar流读取文件内容
            content = await self._read_from_tar(tar_stream)  # 从tar流读取内容
            return content.decode("utf-8")  # 解码为UTF-8字符串

        except NotFound:  # 如果文件未找到
            raise FileNotFoundError(f"File not found: {path}")  # 抛出文件未找到错误
        except Exception as e:  # 捕获其他异常
            raise RuntimeError(f"Failed to read file: {e}")  # 抛出运行时错误

    async def write_file(self, path: str, content: str) -> None:
        """向容器中的文件写入内容

        Args:
            path: 目标路径
            content: 文件内容

        Raises:
            RuntimeError: 如果写入操作失败
        """
        if not self.container:  # 如果容器未初始化
            raise RuntimeError("Sandbox not initialized")  # 抛出运行时错误

        try:
            resolved_path = self._safe_resolve_path(path)  # 安全解析路径
            parent_dir = os.path.dirname(resolved_path)  # 获取父目录

            # 创建父目录
            if parent_dir:  # 如果父目录存在
                await self.run_command(f"mkdir -p {parent_dir}")  # 创建父目录

            # 准备文件数据
            tar_stream = await self._create_tar_stream(
                os.path.basename(path), content.encode("utf-8")  # 创建tar流，包含文件名和UTF-8编码的内容
            )

            # 写入文件
            await asyncio.to_thread(
                self.container.put_archive, parent_dir or "/", tar_stream  # 在线程中将归档放入容器
            )

        except Exception as e:  # 捕获任何异常
            raise RuntimeError(f"Failed to write file: {e}")  # 抛出运行时错误

    def _safe_resolve_path(self, path: str) -> str:
        """安全解析容器路径，防止路径遍历攻击

        Args:
            path: 原始路径

        Returns:
            str: 解析后的绝对路径

        Raises:
            ValueError: 如果路径包含潜在的不安全模式
        """
        # 检查路径遍历尝试
        if ".." in path.split("/"):  # 如果路径中包含".."
            raise ValueError("Path contains potentially unsafe patterns")  # 抛出值错误

        resolved = (
            os.path.join(self.config.work_dir, path)  # 如果是相对路径，与工作目录连接
            if not os.path.isabs(path)  # 如果不是绝对路径
            else path  # 否则直接使用路径
        )
        return resolved  # 返回解析后的路径

    async def copy_from(self, src_path: str, dst_path: str) -> None:
        """从容器复制文件

        Args:
            src_path: 源文件路径（容器内）
            dst_path: 目标路径（主机）

        Raises:
            FileNotFoundError: 如果源文件不存在
            RuntimeError: 如果复制操作失败
        """
        try:
            # 确保目标文件的父目录存在
            parent_dir = os.path.dirname(dst_path)  # 获取父目录
            if parent_dir:  # 如果父目录存在
                os.makedirs(parent_dir, exist_ok=True)  # 创建父目录，如果已存在则不报错

            # 获取文件流
            resolved_src = self._safe_resolve_path(src_path)  # 安全解析源路径
            stream, stat = await asyncio.to_thread(
                self.container.get_archive, resolved_src  # 在线程中获取文件归档
            )

            # 创建临时目录以提取文件
            with tempfile.TemporaryDirectory() as tmp_dir:  # 创建临时目录
                # 将流写入临时文件
                tar_path = os.path.join(tmp_dir, "temp.tar")  # 临时tar文件路径
                with open(tar_path, "wb") as f:  # 打开临时文件
                    for chunk in stream:  # 遍历流块
                        f.write(chunk)  # 写入块

                # 提取文件
                with tarfile.open(tar_path) as tar:  # 打开tar文件
                    members = tar.getmembers()  # 获取tar成员列表
                    if not members:  # 如果成员列表为空
                        raise FileNotFoundError(f"Source file is empty: {src_path}")  # 抛出文件未找到错误

                    # 如果目标是目录，我们应该保留相对路径结构
                    if os.path.isdir(dst_path):  # 如果目标是目录
                        tar.extractall(dst_path)  # 提取所有文件到目录
                    else:  # 如果目标是文件
                        # 如果目标是文件，我们只提取源文件的内容
                        if len(members) > 1:  # 如果tar中有多个成员
                            raise RuntimeError(
                                f"Source path is a directory but destination is a file: {src_path}"  # 抛出运行时错误
                            )

                        with open(dst_path, "wb") as dst:  # 打开目标文件
                            src_file = tar.extractfile(members[0])  # 提取第一个成员
                            if src_file is None:  # 如果提取失败
                                raise RuntimeError(
                                    f"Failed to extract file: {src_path}"  # 抛出运行时错误
                                )
                            dst.write(src_file.read())  # 写入文件内容

        except docker.errors.NotFound:  # 如果文件未找到
            raise FileNotFoundError(f"Source file not found: {src_path}")  # 抛出文件未找到错误
        except Exception as e:  # 捕获其他异常
            raise RuntimeError(f"Failed to copy file: {e}")  # 抛出运行时错误

    async def copy_to(self, src_path: str, dst_path: str) -> None:
        """复制文件到容器

        Args:
            src_path: 源文件路径（主机）
            dst_path: 目标路径（容器）

        Raises:
            FileNotFoundError: 如果源文件不存在
            RuntimeError: 如果复制操作失败
        """
        try:
            if not os.path.exists(src_path):  # 如果源文件不存在
                raise FileNotFoundError(f"Source file not found: {src_path}")  # 抛出文件未找到错误

            # 在容器中创建目标目录
            resolved_dst = self._safe_resolve_path(dst_path)  # 安全解析目标路径
            container_dir = os.path.dirname(resolved_dst)  # 获取容器目录
            if container_dir:  # 如果目录存在
                await self.run_command(f"mkdir -p {container_dir}")  # 创建目录

            # 创建tar文件以上传
            with tempfile.TemporaryDirectory() as tmp_dir:  # 创建临时目录
                tar_path = os.path.join(tmp_dir, "temp.tar")  # 临时tar文件路径
                with tarfile.open(tar_path, "w") as tar:  # 打开tar文件
                    # 处理目录源路径
                    if os.path.isdir(src_path):  # 如果源路径是目录
                        os.path.basename(src_path.rstrip("/"))  # 获取目录名（未使用）
                        for root, _, files in os.walk(src_path):  # 遍历目录树
                            for file in files:  # 遍历文件
                                file_path = os.path.join(root, file)  # 文件完整路径
                                arcname = os.path.join(
                                    os.path.basename(dst_path),  # 目标路径的基础名
                                    os.path.relpath(file_path, src_path),  # 相对于源路径的相对路径
                                )
                                tar.add(file_path, arcname=arcname)  # 添加文件到tar
                    else:  # 如果源路径是文件
                        # 添加单个文件到tar
                        tar.add(src_path, arcname=os.path.basename(dst_path))  # 添加文件，使用目标文件名

                # 读取tar文件内容
                with open(tar_path, "rb") as f:  # 打开tar文件
                    data = f.read()  # 读取所有数据

                # 上传到容器
                await asyncio.to_thread(
                    self.container.put_archive,  # 在线程中执行put_archive
                    os.path.dirname(resolved_dst) or "/",  # 目标目录，如果为空则使用根目录
                    data,  # tar数据
                )

                # 验证文件是否成功创建
                try:
                    await self.run_command(f"test -e {resolved_dst}")  # 测试文件是否存在
                except Exception:  # 如果测试失败
                    raise RuntimeError(f"Failed to verify file creation: {dst_path}")  # 抛出运行时错误

        except FileNotFoundError:  # 如果文件未找到
            raise  # 直接重新抛出
        except Exception as e:  # 捕获其他异常
            raise RuntimeError(f"Failed to copy file: {e}")  # 抛出运行时错误

    @staticmethod
    async def _create_tar_stream(name: str, content: bytes) -> io.BytesIO:
        """创建tar文件流

        Args:
            name: 文件名
            content: 文件内容（字节）

        Returns:
            io.BytesIO: tar文件流
        """
        tar_stream = io.BytesIO()  # 创建字节流
        with tarfile.open(fileobj=tar_stream, mode="w") as tar:  # 打开tar文件
            tarinfo = tarfile.TarInfo(name=name)  # 创建tar信息对象
            tarinfo.size = len(content)  # 设置文件大小
            tar.addfile(tarinfo, io.BytesIO(content))  # 添加文件到tar
        tar_stream.seek(0)  # 将流位置重置到开头
        return tar_stream  # 返回tar流

    @staticmethod
    async def _read_from_tar(tar_stream) -> bytes:
        """从tar流读取文件内容

        Args:
            tar_stream: tar文件流

        Returns:
            bytes: 文件内容

        Raises:
            RuntimeError: 如果读取操作失败
        """
        with tempfile.NamedTemporaryFile() as tmp:  # 创建命名临时文件
            for chunk in tar_stream:  # 遍历流块
                tmp.write(chunk)  # 写入块
            tmp.seek(0)  # 将文件位置重置到开头

            with tarfile.open(fileobj=tmp) as tar:  # 打开tar文件
                member = tar.next()  # 获取下一个成员
                if not member:  # 如果没有成员
                    raise RuntimeError("Empty tar archive")  # 抛出运行时错误

                file_content = tar.extractfile(member)  # 提取文件内容
                if not file_content:  # 如果提取失败
                    raise RuntimeError("Failed to extract file content")  # 抛出运行时错误

                return file_content.read()  # 返回文件内容

    async def cleanup(self) -> None:
        """清理沙箱资源

        清理终端和容器，收集所有错误并报告。
        """
        errors = []  # 初始化错误列表
        try:
            if self.terminal:  # 如果终端存在
                try:
                    await self.terminal.close()  # 关闭终端
                except Exception as e:  # 捕获异常
                    errors.append(f"Terminal cleanup error: {e}")  # 添加错误到列表
                finally:
                    self.terminal = None  # 将终端设置为None

            if self.container:  # 如果容器存在
                try:
                    await asyncio.to_thread(self.container.stop, timeout=5)  # 在线程中停止容器，超时5秒
                except Exception as e:  # 捕获异常
                    errors.append(f"Container stop error: {e}")  # 添加错误到列表

                try:
                    await asyncio.to_thread(self.container.remove, force=True)  # 在线程中强制删除容器
                except Exception as e:  # 捕获异常
                    errors.append(f"Container remove error: {e}")  # 添加错误到列表
                finally:
                    self.container = None  # 将容器设置为None

        except Exception as e:  # 捕获一般异常
            errors.append(f"General cleanup error: {e}")  # 添加错误到列表

        if errors:  # 如果有错误
            print(f"Warning: Errors during cleanup: {', '.join(errors)}")  # 打印警告信息

    async def __aenter__(self) -> "DockerSandbox":
        """异步上下文管理器入口

        Returns:
            DockerSandbox: 创建后的沙箱实例
        """
        return await self.create()  # 创建并返回沙箱

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """异步上下文管理器退出

        Args:
            exc_type: 异常类型
            exc_val: 异常值
            exc_tb: 异常追踪
        """
        await self.cleanup()  # 清理资源
