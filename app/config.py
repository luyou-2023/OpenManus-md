import json  # JSON解析库，用于读取MCP服务器配置
import threading  # 线程锁，用于实现单例模式的线程安全
import tomllib  # TOML文件解析库，用于读取配置文件
from pathlib import Path  # 路径操作库，用于处理文件路径
from typing import Dict, List, Optional  # 类型提示

from pydantic import BaseModel, Field  # Pydantic用于数据验证和模型定义


def get_project_root() -> Path:
    """获取项目根目录路径

    Returns:
        Path: 项目根目录的Path对象
    """
    return Path(__file__).resolve().parent.parent  # 获取当前文件所在目录的父目录的父目录（即项目根目录）


PROJECT_ROOT = get_project_root()  # 项目根目录路径
WORKSPACE_ROOT = PROJECT_ROOT / "workspace"  # 工作空间根目录路径


class LLMSettings(BaseModel):
    """LLM（大语言模型）配置设置类

    定义了与大语言模型API交互所需的所有配置参数
    """
    model: str = Field(..., description="Model name")  # 模型名称，必填字段
    base_url: str = Field(..., description="API base URL")  # API基础URL，必填字段
    api_key: str = Field(..., description="API key")  # API密钥，必填字段
    max_tokens: int = Field(4096, description="Maximum number of tokens per request")  # 每次请求的最大token数，默认4096
    max_input_tokens: Optional[int] = Field(
        None,
        description="Maximum input tokens to use across all requests (None for unlimited)",
    )  # 所有请求的最大输入token数，None表示无限制
    temperature: float = Field(1.0, description="Sampling temperature")  # 采样温度，控制输出的随机性，默认1.0
    api_type: str = Field(..., description="Azure, Openai, or Ollama")  # API类型，必填字段
    api_version: str = Field(..., description="Azure Openai version if AzureOpenai")  # Azure OpenAI的API版本号，必填字段


class ProxySettings(BaseModel):
    """代理服务器配置设置类

    用于配置HTTP/HTTPS代理服务器的连接信息
    """
    server: str = Field(None, description="Proxy server address")  # 代理服务器地址
    username: Optional[str] = Field(None, description="Proxy username")  # 代理服务器用户名，可选
    password: Optional[str] = Field(None, description="Proxy password")  # 代理服务器密码，可选


class SearchSettings(BaseModel):
    """搜索引擎配置设置类

    定义了网络搜索功能的配置参数，包括主搜索引擎、备用引擎、重试策略等
    """
    engine: str = Field(default="Google", description="Search engine the llm to use")  # 主搜索引擎，默认Google
    fallback_engines: List[str] = Field(
        default_factory=lambda: ["DuckDuckGo", "Baidu", "Bing"],
        description="Fallback search engines to try if the primary engine fails",
    )  # 备用搜索引擎列表，当主引擎失败时依次尝试
    retry_delay: int = Field(
        default=60,
        description="Seconds to wait before retrying all engines again after they all fail",
    )  # 所有引擎都失败后，重新尝试前的等待时间（秒），默认60秒
    max_retries: int = Field(
        default=3,
        description="Maximum number of times to retry all engines when all fail",
    )  # 所有引擎都失败时的最大重试次数，默认3次
    lang: str = Field(
        default="en",
        description="Language code for search results (e.g., en, zh, fr)",
    )  # 搜索结果的语言代码，默认英语
    country: str = Field(
        default="us",
        description="Country code for search results (e.g., us, cn, uk)",
    )  # 搜索结果的国家代码，默认美国


class RunflowSettings(BaseModel):
    """运行流程配置设置类

    控制多代理流程中的功能开关
    """
    use_data_analysis_agent: bool = Field(
        default=False, description="Enable data analysis agent in run flow"
    )  # 是否在运行流程中启用数据分析代理，默认False


class BrowserSettings(BaseModel):
    """浏览器配置设置类

    定义了浏览器自动化功能的配置参数，包括运行模式、安全设置、连接方式等
    """
    headless: bool = Field(False, description="Whether to run browser in headless mode")  # 是否以无头模式运行浏览器，默认False（显示浏览器窗口）
    disable_security: bool = Field(
        True, description="Disable browser security features"
    )  # 是否禁用浏览器安全特性，默认True
    extra_chromium_args: List[str] = Field(
        default_factory=list, description="Extra arguments to pass to the browser"
    )  # 传递给浏览器的额外Chromium参数列表，默认为空列表
    chrome_instance_path: Optional[str] = Field(
        None, description="Path to a Chrome instance to use"
    )  # 要使用的Chrome实例路径，可选
    wss_url: Optional[str] = Field(
        None, description="Connect to a browser instance via WebSocket"
    )  # 通过WebSocket连接到浏览器实例的URL，可选
    cdp_url: Optional[str] = Field(
        None, description="Connect to a browser instance via CDP"
    )  # 通过Chrome DevTools Protocol连接到浏览器实例的URL，可选
    proxy: Optional[ProxySettings] = Field(
        None, description="Proxy settings for the browser"
    )  # 浏览器的代理设置，可选
    max_content_length: int = Field(
        2000, description="Maximum length for content retrieval operations"
    )  # 内容检索操作的最大长度，默认2000字符


class SandboxSettings(BaseModel):
    """执行沙箱配置设置类

    定义了代码执行沙箱（Docker容器）的配置参数
    """

    use_sandbox: bool = Field(False, description="Whether to use the sandbox")  # 是否使用沙箱，默认False
    image: str = Field("python:3.12-slim", description="Base image")  # Docker基础镜像，默认python:3.12-slim
    work_dir: str = Field("/workspace", description="Container working directory")  # 容器工作目录，默认/workspace
    memory_limit: str = Field("512m", description="Memory limit")  # 内存限制，默认512MB
    cpu_limit: float = Field(1.0, description="CPU limit")  # CPU限制，默认1.0核
    timeout: int = Field(300, description="Default command timeout (seconds)")  # 默认命令超时时间（秒），默认300秒
    network_enabled: bool = Field(
        False, description="Whether network access is allowed"
    )  # 是否允许网络访问，默认False


class DaytonaSettings(BaseModel):
    """Daytona云沙箱配置设置类

    定义了Daytona云沙箱服务的配置参数
    """
    daytona_api_key: str  # Daytona API密钥，必填字段
    daytona_server_url: Optional[str] = Field(
        "https://app.daytona.io/api", description=""
    )  # Daytona服务器URL，默认https://app.daytona.io/api
    daytona_target: Optional[str] = Field("us", description="enum ['eu', 'us']")  # Daytona目标区域，可选'eu'或'us'，默认'us'
    sandbox_image_name: Optional[str] = Field("whitezxj/sandbox:0.1.0", description="")  # 沙箱镜像名称，默认whitezxj/sandbox:0.1.0
    sandbox_entrypoint: Optional[str] = Field(
        "/usr/bin/supervisord -n -c /etc/supervisor/conf.d/supervisord.conf",
        description="",
    )  # 沙箱入口点命令，默认supervisord启动命令
    # sandbox_id: Optional[str] = Field(
    #     None, description="ID of the daytona sandbox to use, if any"
    # )  # 要使用的Daytona沙箱ID，可选（已注释）
    VNC_password: Optional[str] = Field(
        "123456", description="VNC password for the vnc service in sandbox"
    )  # 沙箱中VNC服务的密码，默认123456


class MCPServerConfig(BaseModel):
    """单个MCP服务器配置类

    定义了Model Context Protocol（MCP）服务器的连接配置
    """

    type: str = Field(..., description="Server connection type (sse or stdio)")  # 服务器连接类型，必填，可选'sse'或'stdio'
    url: Optional[str] = Field(None, description="Server URL for SSE connections")  # SSE连接的服务器URL，可选
    command: Optional[str] = Field(None, description="Command for stdio connections")  # stdio连接的命令，可选
    args: List[str] = Field(
        default_factory=list, description="Arguments for stdio command"
    )  # stdio命令的参数列表，默认为空列表


class MCPSettings(BaseModel):
    """MCP（Model Context Protocol）配置设置类

    定义了MCP相关的配置，包括服务器引用和服务器配置字典
    """

    server_reference: str = Field(
        "app.mcp.server", description="Module reference for the MCP server"
    )  # MCP服务器的模块引用，默认app.mcp.server
    servers: Dict[str, MCPServerConfig] = Field(
        default_factory=dict, description="MCP server configurations"
    )  # MCP服务器配置字典，键为服务器ID，值为服务器配置对象

    @classmethod
    def load_server_config(cls) -> Dict[str, MCPServerConfig]:
        """从JSON文件加载MCP服务器配置

        Returns:
            Dict[str, MCPServerConfig]: 服务器ID到配置对象的映射字典

        Raises:
            ValueError: 如果配置文件加载失败
        """
        config_path = PROJECT_ROOT / "config" / "mcp.json"  # MCP配置文件路径

        try:
            config_file = config_path if config_path.exists() else None  # 检查配置文件是否存在
            if not config_file:  # 如果配置文件不存在，返回空字典
                return {}

            with config_file.open() as f:  # 打开配置文件
                data = json.load(f)  # 解析JSON数据
                servers = {}  # 初始化服务器配置字典

                # 遍历JSON中的mcpServers配置
                for server_id, server_config in data.get("mcpServers", {}).items():
                    servers[server_id] = MCPServerConfig(  # 创建MCPServerConfig对象
                        type=server_config["type"],  # 连接类型
                        url=server_config.get("url"),  # URL（如果存在）
                        command=server_config.get("command"),  # 命令（如果存在）
                        args=server_config.get("args", []),  # 参数列表（如果存在，否则为空列表）
                    )
                return servers  # 返回服务器配置字典
        except Exception as e:  # 捕获任何异常
            raise ValueError(f"Failed to load MCP server config: {e}")  # 抛出带详细信息的ValueError


class AppConfig(BaseModel):
    """应用程序配置类

    整合了所有子系统的配置设置，是整个应用的配置根对象
    """
    llm: Dict[str, LLMSettings]  # LLM配置字典，键为配置名称，值为LLM设置对象
    sandbox: Optional[SandboxSettings] = Field(
        None, description="Sandbox configuration"
    )  # 沙箱配置，可选
    browser_config: Optional[BrowserSettings] = Field(
        None, description="Browser configuration"
    )  # 浏览器配置，可选
    search_config: Optional[SearchSettings] = Field(
        None, description="Search configuration"
    )  # 搜索配置，可选
    mcp_config: Optional[MCPSettings] = Field(None, description="MCP configuration")  # MCP配置，可选
    run_flow_config: Optional[RunflowSettings] = Field(
        None, description="Run flow configuration"
    )  # 运行流程配置，可选
    daytona_config: Optional[DaytonaSettings] = Field(
        None, description="Daytona configuration"
    )  # Daytona配置，可选

    class Config:
        arbitrary_types_allowed = True  # 允许任意类型，用于支持复杂的配置对象


class Config:
    """配置管理单例类

    使用双重检查锁定模式实现线程安全的单例模式，负责加载和管理应用配置
    """
    _instance = None  # 单例实例
    _lock = threading.Lock()  # 线程锁，用于保证线程安全
    _initialized = False  # 初始化标志

    def __new__(cls):
        """创建单例实例（双重检查锁定模式）

        Returns:
            Config: 配置单例实例
        """
        if cls._instance is None:  # 第一次检查
            with cls._lock:  # 获取锁
                if cls._instance is None:  # 第二次检查（双重检查）
                    cls._instance = super().__new__(cls)  # 创建新实例
        return cls._instance  # 返回单例实例

    def __init__(self):
        """初始化配置对象，加载配置文件"""
        if not self._initialized:  # 检查是否已初始化
            with self._lock:  # 获取锁
                if not self._initialized:  # 双重检查
                    self._config = None  # 初始化配置对象为None
                    self._load_initial_config()  # 加载初始配置
                    self._initialized = True  # 标记为已初始化

    @staticmethod
    def _get_config_path() -> Path:
        """获取配置文件路径

        优先查找config.toml，如果不存在则查找config.example.toml

        Returns:
            Path: 配置文件路径

        Raises:
            FileNotFoundError: 如果找不到任何配置文件
        """
        root = PROJECT_ROOT  # 项目根目录
        config_path = root / "config" / "config.toml"  # 主配置文件路径
        if config_path.exists():  # 如果主配置文件存在
            return config_path  # 返回主配置文件路径
        example_path = root / "config" / "config.example.toml"  # 示例配置文件路径
        if example_path.exists():  # 如果示例配置文件存在
            return example_path  # 返回示例配置文件路径
        raise FileNotFoundError("No configuration file found in config directory")  # 抛出文件未找到异常

    def _load_config(self) -> dict:
        """加载TOML配置文件

        Returns:
            dict: 解析后的配置字典
        """
        config_path = self._get_config_path()  # 获取配置文件路径
        with config_path.open("rb") as f:  # 以二进制模式打开配置文件
            return tomllib.load(f)  # 解析TOML文件并返回字典

    def _load_initial_config(self):
        """加载并初始化应用配置

        从TOML文件读取配置，解析各个子系统的配置，并创建AppConfig对象
        """
        raw_config = self._load_config()  # 加载原始配置字典
        base_llm = raw_config.get("llm", {})  # 获取基础LLM配置
        llm_overrides = {
            k: v for k, v in raw_config.get("llm", {}).items() if isinstance(v, dict)
        }  # 提取所有LLM配置覆盖项（字典类型的值）

        # 构建默认LLM设置字典
        default_settings = {
            "model": base_llm.get("model"),  # 模型名称
            "base_url": base_llm.get("base_url"),  # API基础URL
            "api_key": base_llm.get("api_key"),  # API密钥
            "max_tokens": base_llm.get("max_tokens", 4096),  # 最大token数，默认4096
            "max_input_tokens": base_llm.get("max_input_tokens"),  # 最大输入token数
            "temperature": base_llm.get("temperature", 1.0),  # 温度参数，默认1.0
            "api_type": base_llm.get("api_type", ""),  # API类型，默认空字符串
            "api_version": base_llm.get("api_version", ""),  # API版本，默认空字符串
        }

        # 处理浏览器配置
        browser_config = raw_config.get("browser", {})  # 获取浏览器配置字典
        browser_settings = None  # 初始化浏览器设置对象

        if browser_config:  # 如果存在浏览器配置
            # 处理代理设置
            proxy_config = browser_config.get("proxy", {})  # 获取代理配置
            proxy_settings = None  # 初始化代理设置对象

            if proxy_config and proxy_config.get("server"):  # 如果存在代理配置且包含服务器地址
                proxy_settings = ProxySettings(  # 创建代理设置对象
                    **{
                        k: v
                        for k, v in proxy_config.items()
                        if k in ["server", "username", "password"] and v  # 只提取有效的代理字段
                    }
                )

            # 过滤有效的浏览器配置参数（只保留BrowserSettings类中定义的字段）
            valid_browser_params = {
                k: v
                for k, v in browser_config.items()
                if k in BrowserSettings.__annotations__ and v is not None  # 检查字段是否在类注解中且值不为None
            }

            # 如果存在代理设置，将其添加到参数中
            if proxy_settings:
                valid_browser_params["proxy"] = proxy_settings

            # 只有当存在有效参数时才创建BrowserSettings对象
            if valid_browser_params:
                browser_settings = BrowserSettings(**valid_browser_params)

        # 处理搜索配置
        search_config = raw_config.get("search", {})  # 获取搜索配置字典
        search_settings = None  # 初始化搜索设置对象
        if search_config:  # 如果存在搜索配置
            search_settings = SearchSettings(**search_config)  # 创建搜索设置对象

        # 处理沙箱配置
        sandbox_config = raw_config.get("sandbox", {})  # 获取沙箱配置字典
        if sandbox_config:  # 如果存在沙箱配置
            sandbox_settings = SandboxSettings(**sandbox_config)  # 创建沙箱设置对象
        else:  # 如果不存在沙箱配置
            sandbox_settings = SandboxSettings()  # 使用默认值创建沙箱设置对象

        # 处理Daytona配置
        daytona_config = raw_config.get("daytona", {})  # 获取Daytona配置字典
        if daytona_config:  # 如果存在Daytona配置
            daytona_settings = DaytonaSettings(**daytona_config)  # 创建Daytona设置对象
        else:  # 如果不存在Daytona配置
            daytona_settings = DaytonaSettings()  # 使用默认值创建Daytona设置对象（需要提供必填字段）

        # 处理MCP配置
        mcp_config = raw_config.get("mcp", {})  # 获取MCP配置字典
        mcp_settings = None  # 初始化MCP设置对象
        if mcp_config:  # 如果存在MCP配置
            # 从JSON文件加载服务器配置
            mcp_config["servers"] = MCPSettings.load_server_config()  # 加载服务器配置并添加到MCP配置中
            mcp_settings = MCPSettings(**mcp_config)  # 创建MCP设置对象
        else:  # 如果不存在MCP配置
            mcp_settings = MCPSettings(servers=MCPSettings.load_server_config())  # 使用默认值创建MCP设置对象，但仍加载服务器配置

        # 处理运行流程配置
        run_flow_config = raw_config.get("runflow")  # 获取运行流程配置字典
        if run_flow_config:  # 如果存在运行流程配置
            run_flow_settings = RunflowSettings(**run_flow_config)  # 创建运行流程设置对象
        else:  # 如果不存在运行流程配置
            run_flow_settings = RunflowSettings()  # 使用默认值创建运行流程设置对象
        # 构建完整的配置字典
        config_dict = {
            "llm": {
                "default": default_settings,  # 默认LLM配置
                **{
                    name: {**default_settings, **override_config}  # 合并默认设置和覆盖配置
                    for name, override_config in llm_overrides.items()  # 为每个覆盖配置创建合并后的配置
                },
            },
            "sandbox": sandbox_settings,  # 沙箱配置
            "browser_config": browser_settings,  # 浏览器配置
            "search_config": search_settings,  # 搜索配置
            "mcp_config": mcp_settings,  # MCP配置
            "run_flow_config": run_flow_settings,  # 运行流程配置
            "daytona_config": daytona_settings,  # Daytona配置
        }

        self._config = AppConfig(**config_dict)  # 创建AppConfig对象并保存到实例变量

    @property
    def llm(self) -> Dict[str, LLMSettings]:
        """获取LLM配置字典"""
        return self._config.llm

    @property
    def sandbox(self) -> SandboxSettings:
        """获取沙箱配置"""
        return self._config.sandbox

    @property
    def daytona(self) -> DaytonaSettings:
        """获取Daytona配置"""
        return self._config.daytona_config

    @property
    def browser_config(self) -> Optional[BrowserSettings]:
        """获取浏览器配置"""
        return self._config.browser_config

    @property
    def search_config(self) -> Optional[SearchSettings]:
        """获取搜索配置"""
        return self._config.search_config

    @property
    def mcp_config(self) -> MCPSettings:
        """获取MCP配置"""
        return self._config.mcp_config

    @property
    def run_flow_config(self) -> RunflowSettings:
        """获取运行流程配置"""
        return self._config.run_flow_config

    @property
    def workspace_root(self) -> Path:
        """获取工作空间根目录路径"""
        return WORKSPACE_ROOT

    @property
    def root_path(self) -> Path:
        """获取应用程序根路径"""
        return PROJECT_ROOT


config = Config()  # 创建全局配置单例实例
