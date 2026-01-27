from dataclasses import dataclass, field  # 数据类装饰器和字段
from datetime import datetime  # 日期时间库
from typing import Any, ClassVar, Dict, Optional  # 类型提示

from daytona import Daytona, DaytonaConfig, Sandbox, SandboxState  # Daytona SDK类
from pydantic import Field  # Pydantic字段定义

from app.config import config  # 全局配置
from app.daytona.sandbox import create_sandbox, start_supervisord_session  # Daytona沙箱函数
from app.tool.base import BaseTool  # 工具基类
from app.utils.files_utils import clean_path  # 路径清理工具函数
from app.utils.logger import logger  # 日志记录器


# load_dotenv()  # 加载环境变量（已注释）
daytona_settings = config.daytona  # 获取Daytona配置
daytona_config = DaytonaConfig(
    api_key=daytona_settings.daytona_api_key,  # API密钥
    server_url=daytona_settings.daytona_server_url,  # 服务器URL
    target=daytona_settings.daytona_target,  # 目标
)
daytona = Daytona(daytona_config)  # 创建Daytona客户端实例


@dataclass
class ThreadMessage:
    """线程消息数据类

    表示要添加到线程的消息。
    """

    type: str  # 消息类型
    content: Dict[str, Any]  # 消息内容字典
    is_llm_message: bool = False  # 是否为LLM消息，默认为False
    metadata: Optional[Dict[str, Any]] = None  # 元数据字典，可选
    timestamp: Optional[float] = field(
        default_factory=lambda: datetime.now().timestamp()  # 时间戳，默认为当前时间
    )

    def to_dict(self) -> Dict[str, Any]:
        """将消息转换为字典用于API调用

        Returns:
            Dict[str, Any]: 消息字典
        """
        return {
            "type": self.type,  # 消息类型
            "content": self.content,  # 消息内容
            "is_llm_message": self.is_llm_message,  # 是否为LLM消息
            "metadata": self.metadata or {},  # 元数据，如果为None则使用空字典
            "timestamp": self.timestamp,  # 时间戳
        }


class SandboxToolsBase(BaseTool):
    """沙箱工具基类

    所有沙箱工具的基础类，提供基于项目的沙箱访问。
    """

    # 类变量：跟踪沙箱URL是否已打印
    _urls_printed: ClassVar[bool] = False  # URL打印标志

    # 必需字段
    project_id: Optional[str] = None  # 项目ID，可选
    # thread_manager: Optional[ThreadManager] = None  # 线程管理器（已注释）

    # 私有字段（不属于模型Schema）
    _sandbox: Optional[Sandbox] = None  # 沙箱实例，可选
    _sandbox_id: Optional[str] = None  # 沙箱ID，可选
    _sandbox_pass: Optional[str] = None  # 沙箱密码，可选
    workspace_path: str = Field(default="/workspace", exclude=True)  # 工作空间路径，默认/workspace，排除在Schema外
    _sessions: dict[str, str] = {}  # 会话字典

    class Config:
        arbitrary_types_allowed = True  # 允许非Pydantic类型（如ThreadManager）
        underscore_attrs_are_private = True  # 下划线开头的属性为私有

    async def _ensure_sandbox(self) -> Sandbox:
        """确保我们有有效的沙箱实例，如果需要则从项目获取

        Returns:
            Sandbox: 沙箱实例

        Raises:
            Exception: 如果获取或启动沙箱失败
        """
        if self._sandbox is None:  # 如果沙箱未初始化
            # 获取或启动沙箱
            try:
                self._sandbox = create_sandbox(password=config.daytona.VNC_password)  # 创建沙箱
                # 如果尚未打印URL，则记录URL
                if not SandboxToolsBase._urls_printed:  # 如果URL未打印
                    vnc_link = self._sandbox.get_preview_link(6080)  # 获取VNC预览链接
                    website_link = self._sandbox.get_preview_link(8080)  # 获取网站预览链接

                    vnc_url = (
                        vnc_link.url if hasattr(vnc_link, "url") else str(vnc_link)  # 提取VNC URL
                    )
                    website_url = (
                        website_link.url
                        if hasattr(website_link, "url")
                        else str(website_link)  # 提取网站URL
                    )

                    print("\033[95m***")  # 打印紫色标记开始
                    print(f"VNC URL: {vnc_url}")  # 打印VNC URL
                    print(f"Website URL: {website_url}")  # 打印网站URL
                    print("***\033[0m")  # 打印标记结束
                    SandboxToolsBase._urls_printed = True  # 标记URL已打印
            except Exception as e:  # 捕获任何异常
                logger.error(f"Error retrieving or starting sandbox: {str(e)}")  # 记录错误
                raise e  # 重新抛出异常
        else:  # 如果沙箱已存在
            if (
                self._sandbox.state == SandboxState.ARCHIVED
                or self._sandbox.state == SandboxState.STOPPED
            ):  # 如果沙箱状态为归档或停止
                logger.info(f"Sandbox is in {self._sandbox.state} state. Starting...")  # 记录信息
                try:
                    daytona.start(self._sandbox)  # 启动沙箱
                    # 等待沙箱初始化
                    # sleep(5)  # 已注释：等待5秒
                    # 启动后刷新沙箱状态

                    # 重启时在会话中启动supervisord
                    start_supervisord_session(self._sandbox)  # 启动supervisord会话
                except Exception as e:  # 捕获任何异常
                    logger.error(f"Error starting sandbox: {e}")  # 记录错误
                    raise e  # 重新抛出异常
        return self._sandbox  # 返回沙箱实例

    @property
    def sandbox(self) -> Sandbox:
        """获取沙箱实例，确保它存在

        Returns:
            Sandbox: 沙箱实例

        Raises:
            RuntimeError: 如果沙箱未初始化
        """
        if self._sandbox is None:  # 如果沙箱为None
            raise RuntimeError("Sandbox not initialized. Call _ensure_sandbox() first.")  # 抛出运行时错误
        return self._sandbox  # 返回沙箱实例

    @property
    def sandbox_id(self) -> str:
        """获取沙箱ID，确保它存在

        Returns:
            str: 沙箱ID

        Raises:
            RuntimeError: 如果沙箱ID未初始化
        """
        if self._sandbox_id is None:  # 如果沙箱ID为None
            raise RuntimeError(
                "Sandbox ID not initialized. Call _ensure_sandbox() first."  # 抛出运行时错误
            )
        return self._sandbox_id  # 返回沙箱ID

    def clean_path(self, path: str) -> str:
        """清理并规范化路径，使其相对于/workspace

        Args:
            path: 原始路径

        Returns:
            str: 清理后的路径
        """
        cleaned_path = clean_path(path, self.workspace_path)  # 清理路径
        logger.debug(f"Cleaned path: {path} -> {cleaned_path}")  # 记录调试信息
        return cleaned_path  # 返回清理后的路径
