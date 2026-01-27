import math  # 数学库，用于图像token计算中的向上取整
from typing import Dict, List, Optional, Union  # 类型提示

import tiktoken  # Token计数库，用于计算文本token数量
from openai import (
    APIError,  # OpenAI API错误
    AsyncAzureOpenAI,  # Azure OpenAI异步客户端
    AsyncOpenAI,  # OpenAI异步客户端
    AuthenticationError,  # 认证错误
    OpenAIError,  # OpenAI基础错误类
    RateLimitError,  # 速率限制错误
)
from openai.types.chat import ChatCompletion, ChatCompletionMessage  # OpenAI聊天完成类型
from tenacity import (
    retry,  # 重试装饰器
    retry_if_exception_type,  # 按异常类型重试
    stop_after_attempt,  # 停止重试条件
    wait_random_exponential,  # 指数退避等待策略
)

from app.bedrock import BedrockClient  # AWS Bedrock客户端
from app.config import LLMSettings, config  # LLM配置和全局配置
from app.exceptions import TokenLimitExceeded  # Token限制超出异常
from app.logger import logger  # 日志记录器
from app.schema import (
    ROLE_VALUES,  # 角色值元组
    TOOL_CHOICE_TYPE,  # 工具选择类型
    TOOL_CHOICE_VALUES,  # 工具选择值元组
    Message,  # 消息模型
    ToolChoice,  # 工具选择枚举
)


REASONING_MODELS = ["o1", "o3-mini"]  # 推理模型列表，这些模型使用max_completion_tokens而不是max_tokens
MULTIMODAL_MODELS = [
    "gpt-4-vision-preview",  # GPT-4视觉预览版
    "gpt-4o",  # GPT-4o
    "gpt-4o-mini",  # GPT-4o迷你版
    "claude-3-opus-20240229",  # Claude 3 Opus
    "claude-3-sonnet-20240229",  # Claude 3 Sonnet
    "claude-3-haiku-20240307",  # Claude 3 Haiku
]  # 多模态模型列表，这些模型支持图像输入


class TokenCounter:
    """Token计数器类

    用于计算消息、文本和图像的token数量。
    实现了OpenAI的token计数规则，包括图像token的计算。
    """
    # Token常量
    BASE_MESSAGE_TOKENS = 4  # 每条消息的基础token数
    FORMAT_TOKENS = 2  # 消息格式的token数
    LOW_DETAIL_IMAGE_TOKENS = 85  # 低细节图像的固定token数
    HIGH_DETAIL_TILE_TOKENS = 170  # 高细节图像每个512x512瓦片的token数

    # 图像处理常量
    MAX_SIZE = 2048  # 图像最大尺寸（像素）
    HIGH_DETAIL_TARGET_SHORT_SIDE = 768  # 高细节图像目标短边长度（像素）
    TILE_SIZE = 512  # 图像瓦片大小（像素）

    def __init__(self, tokenizer):
        """初始化Token计数器

        Args:
            tokenizer: tiktoken编码器实例
        """
        self.tokenizer = tokenizer  # 保存tokenizer实例

    def count_text(self, text: str) -> int:
        """计算文本字符串的token数量

        Args:
            text: 要计算的文本字符串

        Returns:
            int: token数量，如果文本为空则返回0
        """
        return 0 if not text else len(self.tokenizer.encode(text))  # 如果文本为空返回0，否则编码并计算长度

    def count_image(self, image_item: dict) -> int:
        """根据细节级别和尺寸计算图像的token数量

        对于"low"细节：固定85 tokens
        对于"high"细节：
        1. 缩放到适合2048x2048正方形
        2. 将短边缩放到768px
        3. 计算512px瓦片数量（每个170 tokens）
        4. 加上85 tokens

        Args:
            image_item: 图像项字典，包含detail和可选的dimensions

        Returns:
            int: 图像的token数量
        """
        detail = image_item.get("detail", "medium")  # 获取细节级别，默认为"medium"

        # 对于低细节，始终返回固定token数
        if detail == "low":  # 如果是低细节
            return self.LOW_DETAIL_IMAGE_TOKENS  # 返回固定token数

        # 对于中等细节（OpenAI的默认值），使用高细节计算方法
        # OpenAI没有为medium指定单独的计算方法

        # 对于高细节，如果提供了尺寸则基于尺寸计算
        if detail == "high" or detail == "medium":  # 如果是高细节或中等细节
            # 如果image_item中提供了尺寸
            if "dimensions" in image_item:  # 如果包含尺寸信息
                width, height = image_item["dimensions"]  # 提取宽度和高度
                return self._calculate_high_detail_tokens(width, height)  # 调用高细节计算方法

        return (
            self._calculate_high_detail_tokens(1024, 1024) if detail == "high" else 1024  # 如果没有尺寸信息，使用默认值
        )

    def _calculate_high_detail_tokens(self, width: int, height: int) -> int:
        """基于尺寸计算高细节图像的token数量

        按照OpenAI的规则计算：
        1. 缩放到适合MAX_SIZE x MAX_SIZE正方形
        2. 将短边缩放到HIGH_DETAIL_TARGET_SHORT_SIDE
        3. 计算512px瓦片数量
        4. 计算最终token数

        Args:
            width: 图像宽度（像素）
            height: 图像高度（像素）

        Returns:
            int: 图像的token数量
        """
        # 步骤1：缩放到适合MAX_SIZE x MAX_SIZE正方形
        if width > self.MAX_SIZE or height > self.MAX_SIZE:  # 如果任一维度超过最大尺寸
            scale = self.MAX_SIZE / max(width, height)  # 计算缩放比例
            width = int(width * scale)  # 缩放宽度
            height = int(height * scale)  # 缩放高度

        # 步骤2：缩放使短边为HIGH_DETAIL_TARGET_SHORT_SIDE
        scale = self.HIGH_DETAIL_TARGET_SHORT_SIDE / min(width, height)  # 计算缩放比例
        scaled_width = int(width * scale)  # 缩放后的宽度
        scaled_height = int(height * scale)  # 缩放后的高度

        # 步骤3：计算512px瓦片数量
        tiles_x = math.ceil(scaled_width / self.TILE_SIZE)  # X方向的瓦片数（向上取整）
        tiles_y = math.ceil(scaled_height / self.TILE_SIZE)  # Y方向的瓦片数（向上取整）
        total_tiles = tiles_x * tiles_y  # 总瓦片数

        # 步骤4：计算最终token数量
        return (
            total_tiles * self.HIGH_DETAIL_TILE_TOKENS  # 瓦片数乘以每个瓦片的token数
        ) + self.LOW_DETAIL_IMAGE_TOKENS  # 加上基础token数

    def count_content(self, content: Union[str, List[Union[str, dict]]]) -> int:
        """计算消息内容的token数量

        Args:
            content: 消息内容，可以是字符串或包含文本和图像的列表

        Returns:
            int: token数量，如果内容为空则返回0
        """
        if not content:  # 如果内容为空
            return 0  # 返回0

        if isinstance(content, str):  # 如果内容是字符串
            return self.count_text(content)  # 直接计算文本token

        token_count = 0  # 初始化token计数
        for item in content:  # 遍历内容列表
            if isinstance(item, str):  # 如果是字符串项
                token_count += self.count_text(item)  # 计算文本token并累加
            elif isinstance(item, dict):  # 如果是字典项
                if "text" in item:  # 如果包含文本
                    token_count += self.count_text(item["text"])  # 计算文本token并累加
                elif "image_url" in item:  # 如果包含图像URL
                    token_count += self.count_image(item)  # 计算图像token并累加
        return token_count  # 返回总token数

    def count_tool_calls(self, tool_calls: List[dict]) -> int:
        """计算工具调用的token数量

        Args:
            tool_calls: 工具调用列表

        Returns:
            int: token数量
        """
        token_count = 0  # 初始化token计数
        for tool_call in tool_calls:  # 遍历工具调用列表
            if "function" in tool_call:  # 如果包含function字段
                function = tool_call["function"]  # 获取function对象
                token_count += self.count_text(function.get("name", ""))  # 计算工具名称token并累加
                token_count += self.count_text(function.get("arguments", ""))  # 计算工具参数token并累加
        return token_count  # 返回总token数

    def count_message_tokens(self, messages: List[dict]) -> int:
        """计算消息列表的总token数量

        按照OpenAI的规则计算：
        - 基础格式token
        - 每条消息的基础token
        - 角色token
        - 内容token
        - 工具调用token
        - 名称和tool_call_id token

        Args:
            messages: 消息字典列表

        Returns:
            int: 总token数量
        """
        total_tokens = self.FORMAT_TOKENS  # 基础格式token

        for message in messages:  # 遍历每条消息
            tokens = self.BASE_MESSAGE_TOKENS  # 每条消息的基础token

            # 添加角色token
            tokens += self.count_text(message.get("role", ""))  # 计算角色token并累加

            # 添加内容token
            if "content" in message:  # 如果消息包含内容
                tokens += self.count_content(message["content"])  # 计算内容token并累加

            # 添加工具调用token
            if "tool_calls" in message:  # 如果消息包含工具调用
                tokens += self.count_tool_calls(message["tool_calls"])  # 计算工具调用token并累加

            # 添加名称和tool_call_id token
            tokens += self.count_text(message.get("name", ""))  # 计算名称token并累加
            tokens += self.count_text(message.get("tool_call_id", ""))  # 计算tool_call_id token并累加

            total_tokens += tokens  # 将消息token累加到总数

        return total_tokens  # 返回总token数


class LLM:
    """LLM客户端类

    封装不同LLM提供商的API，提供统一的调用接口。
    使用单例模式，每个配置名称对应一个实例。
    支持OpenAI、Azure OpenAI、AWS Bedrock等。
    """
    _instances: Dict[str, "LLM"] = {}  # 类字典，存储不同配置名称的LLM实例（单例模式）

    def __new__(
        cls, config_name: str = "default", llm_config: Optional[LLMSettings] = None
    ):
        """创建LLM实例（单例模式）

        Args:
            config_name: 配置名称，默认为"default"
            llm_config: 可选的LLM配置，如果不提供则从全局配置读取

        Returns:
            LLM: LLM实例（单例）
        """
        if config_name not in cls._instances:  # 如果该配置名称的实例不存在
            instance = super().__new__(cls)  # 创建新实例
            instance.__init__(config_name, llm_config)  # 初始化实例
            cls._instances[config_name] = instance  # 将实例保存到类字典
        return cls._instances[config_name]  # 返回已存在的实例

    def __init__(
        self, config_name: str = "default", llm_config: Optional[LLMSettings] = None
    ):
        """初始化LLM客户端

        Args:
            config_name: 配置名称，默认为"default"
            llm_config: 可选的LLM配置，如果不提供则从全局配置读取
        """
        if not hasattr(self, "client"):  # 只有在未初始化时才初始化（避免重复初始化）
            llm_config = llm_config or config.llm  # 如果没有提供配置，使用全局配置
            llm_config = llm_config.get(config_name, llm_config["default"])  # 获取指定配置名称的配置，如果不存在则使用default
            self.model = llm_config.model  # 模型名称
            self.max_tokens = llm_config.max_tokens  # 最大token数
            self.temperature = llm_config.temperature  # 温度参数
            self.api_type = llm_config.api_type  # API类型（azure、aws、openai等）
            self.api_key = llm_config.api_key  # API密钥
            self.api_version = llm_config.api_version  # API版本（Azure需要）
            self.base_url = llm_config.base_url  # API基础URL

            # 添加token计数相关属性
            self.total_input_tokens = 0  # 累计输入token数
            self.total_completion_tokens = 0  # 累计完成token数
            self.max_input_tokens = (
                llm_config.max_input_tokens  # 最大输入token数限制
                if hasattr(llm_config, "max_input_tokens")  # 如果配置中有此属性
                else None  # 否则为None（无限制）
            )

            # 初始化tokenizer
            try:
                self.tokenizer = tiktoken.encoding_for_model(self.model)  # 尝试根据模型名称获取编码器
            except KeyError:  # 如果模型不在tiktoken的预设中
                # 如果模型不在tiktoken的预设中，使用cl100k_base作为默认编码器
                self.tokenizer = tiktoken.get_encoding("cl100k_base")  # 使用默认编码器

            if self.api_type == "azure":  # 如果是Azure OpenAI
                self.client = AsyncAzureOpenAI(  # 创建Azure OpenAI客户端
                    base_url=self.base_url,  # 基础URL
                    api_key=self.api_key,  # API密钥
                    api_version=self.api_version,  # API版本
                )
            elif self.api_type == "aws":  # 如果是AWS Bedrock
                self.client = BedrockClient()  # 创建Bedrock客户端
            else:  # 默认使用OpenAI
                self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)  # 创建OpenAI客户端

            self.token_counter = TokenCounter(self.tokenizer)  # 创建Token计数器实例

    def count_tokens(self, text: str) -> int:
        """计算文本中的token数量

        Args:
            text: 要计算的文本字符串

        Returns:
            int: token数量，如果文本为空则返回0
        """
        if not text:  # 如果文本为空
            return 0  # 返回0
        return len(self.tokenizer.encode(text))  # 编码文本并返回长度

    def count_message_tokens(self, messages: List[dict]) -> int:
        """计算消息列表的token数量

        Args:
            messages: 消息字典列表

        Returns:
            int: token数量
        """
        return self.token_counter.count_message_tokens(messages)  # 委托给TokenCounter计算

    def update_token_count(self, input_tokens: int, completion_tokens: int = 0) -> None:
        """更新token计数

        累加输入和完成的token数，并记录日志。

        Args:
            input_tokens: 本次请求的输入token数
            completion_tokens: 本次请求的完成token数，默认为0
        """
        # 只有在设置了max_input_tokens时才跟踪token
        self.total_input_tokens += input_tokens  # 累加输入token数
        self.total_completion_tokens += completion_tokens  # 累加完成token数
        logger.info(
            f"Token usage: Input={input_tokens}, Completion={completion_tokens}, "
            f"Cumulative Input={self.total_input_tokens}, Cumulative Completion={self.total_completion_tokens}, "
            f"Total={input_tokens + completion_tokens}, Cumulative Total={self.total_input_tokens + self.total_completion_tokens}"  # 记录详细的token使用信息
        )

    def check_token_limit(self, input_tokens: int) -> bool:
        """检查token限制是否超出

        Args:
            input_tokens: 要检查的输入token数

        Returns:
            bool: 如果未超出限制返回True，否则返回False。如果未设置max_input_tokens则始终返回True
        """
        if self.max_input_tokens is not None:  # 如果设置了最大输入token数
            return (self.total_input_tokens + input_tokens) <= self.max_input_tokens  # 检查累加后是否超出限制
        # 如果未设置max_input_tokens，始终返回True
        return True  # 无限制，返回True

    def get_limit_error_message(self, input_tokens: int) -> str:
        """生成token限制超出的错误消息

        Args:
            input_tokens: 需要的输入token数

        Returns:
            str: 错误消息字符串
        """
        if (
            self.max_input_tokens is not None  # 如果设置了最大输入token数
            and (self.total_input_tokens + input_tokens) > self.max_input_tokens  # 且累加后超出限制
        ):
            return f"Request may exceed input token limit (Current: {self.total_input_tokens}, Needed: {input_tokens}, Max: {self.max_input_tokens})"  # 返回详细错误消息

        return "Token limit exceeded"  # 返回通用错误消息

    @staticmethod
    def format_messages(
        messages: List[Union[dict, Message]], supports_images: bool = False
    ) -> List[dict]:
        """格式化消息：将消息转换为OpenAI消息格式

        静态方法，用于将Message对象或字典转换为OpenAI API所需的格式。
        支持多模态消息（图像）的处理。

        Args:
            messages: 消息列表，可以是dict或Message对象
            supports_images: 标志，指示目标模型是否支持图像输入

        Returns:
            List[dict]: 格式化后的消息列表，符合OpenAI格式

        Raises:
            ValueError: 如果消息无效或缺少必需字段
            TypeError: 如果提供了不支持的消息类型

        Examples:
            >>> msgs = [
            ...     Message.system_message("You are a helpful assistant"),
            ...     {"role": "user", "content": "Hello"},
            ...     Message.user_message("How are you?")
            ... ]
            >>> formatted = LLM.format_messages(msgs)
        """
        formatted_messages = []  # 初始化格式化消息列表

        for message in messages:  # 遍历所有消息
            # 将Message对象转换为字典
            if isinstance(message, Message):  # 如果是Message对象
                message = message.to_dict()  # 转换为字典

            if isinstance(message, dict):  # 如果消息是字典
                # 如果消息是字典，确保它包含必需字段
                if "role" not in message:  # 如果缺少role字段
                    raise ValueError("Message dict must contain 'role' field")  # 抛出值错误

                # 如果存在base64图像且模型支持图像，则处理图像
                if supports_images and message.get("base64_image"):  # 如果支持图像且消息包含图像
                    # 初始化或将content转换为适当格式
                    if not message.get("content"):  # 如果content不存在
                        message["content"] = []  # 初始化为空列表
                    elif isinstance(message["content"], str):  # 如果content是字符串
                        message["content"] = [
                            {"type": "text", "text": message["content"]}  # 转换为文本对象列表
                        ]
                    elif isinstance(message["content"], list):  # 如果content是列表
                        # 将字符串项转换为适当的文本对象
                        message["content"] = [
                            (
                                {"type": "text", "text": item}  # 如果是字符串，转换为文本对象
                                if isinstance(item, str)  # 检查是否为字符串
                                else item  # 否则保持原样
                            )
                            for item in message["content"]  # 遍历列表项
                        ]

                    # 将图像添加到content
                    message["content"].append(  # 追加图像对象
                        {
                            "type": "image_url",  # 图像类型
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{message['base64_image']}"  # Base64数据URL
                            },
                        }
                    )

                    # 删除base64_image字段
                    del message["base64_image"]  # 删除原始base64_image字段
                # 如果模型不支持图像但消息有base64_image，优雅处理
                elif not supports_images and message.get("base64_image"):  # 如果不支持图像但消息包含图像
                    # 只删除base64_image字段，保留文本内容
                    del message["base64_image"]  # 删除图像字段

                if "content" in message or "tool_calls" in message:  # 如果消息包含内容或工具调用
                    formatted_messages.append(message)  # 添加到格式化消息列表
                # else: 不包含该消息
            else:  # 如果消息类型不支持
                raise TypeError(f"Unsupported message type: {type(message)}")  # 抛出类型错误

        # 验证所有消息都有必需字段
        for msg in formatted_messages:  # 遍历格式化后的消息
            if msg["role"] not in ROLE_VALUES:  # 如果角色不在有效值中
                raise ValueError(f"Invalid role: {msg['role']}")  # 抛出值错误

        return formatted_messages  # 返回格式化后的消息列表

    @retry(
        wait=wait_random_exponential(min=1, max=60),
        stop=stop_after_attempt(6),
        retry=retry_if_exception_type(
            (OpenAIError, Exception, ValueError)
        ),  # Don't retry TokenLimitExceeded
    )
    async def ask(
        self,
        messages: List[Union[dict, Message]],
        system_msgs: Optional[List[Union[dict, Message]]] = None,
        stream: bool = True,
        temperature: Optional[float] = None,
    ) -> str:
        """
        Send a prompt to the LLM and get the response.

        Args:
            messages: List of conversation messages
            system_msgs: Optional system messages to prepend
            stream (bool): Whether to stream the response
            temperature (float): Sampling temperature for the response

        Returns:
            str: The generated response

        Raises:
            TokenLimitExceeded: If token limits are exceeded
            ValueError: If messages are invalid or response is empty
            OpenAIError: If API call fails after retries
            Exception: For unexpected errors
        """
        try:
            # 检查模型是否支持图像
            supports_images = self.model in MULTIMODAL_MODELS  # 检查模型是否在多模态模型列表中

            # 使用图像支持检查格式化系统和用户消息
            if system_msgs:  # 如果提供了系统消息
                system_msgs = self.format_messages(system_msgs, supports_images)  # 格式化系统消息
                messages = system_msgs + self.format_messages(messages, supports_images)  # 合并系统消息和用户消息
            else:  # 如果没有系统消息
                messages = self.format_messages(messages, supports_images)  # 只格式化用户消息

            # 计算输入token数量
            input_tokens = self.count_message_tokens(messages)  # 计算消息列表的token数

            # 检查token限制是否超出
            if not self.check_token_limit(input_tokens):  # 如果超出限制
                error_message = self.get_limit_error_message(input_tokens)  # 获取错误消息
                # 抛出一个特殊异常，不会被重试
                raise TokenLimitExceeded(error_message)  # 抛出Token限制超出异常

            params = {
                "model": self.model,  # 模型名称
                "messages": messages,  # 消息列表
            }

            if self.model in REASONING_MODELS:  # 如果是推理模型
                params["max_completion_tokens"] = self.max_tokens  # 使用max_completion_tokens参数
            else:  # 如果是普通模型
                params["max_tokens"] = self.max_tokens  # 使用max_tokens参数
                params["temperature"] = (
                    temperature if temperature is not None else self.temperature  # 如果提供了temperature则使用，否则使用默认值
                )

            if not stream:  # 如果不是流式请求
                # 非流式请求
                response = await self.client.chat.completions.create(
                    **params, stream=False  # 创建非流式完成请求
                )

                if not response.choices or not response.choices[0].message.content:  # 如果响应无效或为空
                    raise ValueError("Empty or invalid response from LLM")  # 抛出值错误

                # 更新token计数
                self.update_token_count(
                    response.usage.prompt_tokens, response.usage.completion_tokens  # 传入输入和完成token数
                )

                return response.choices[0].message.content  # 返回响应内容

            # 流式请求，对于流式请求，在发出请求前更新估计的token计数
            self.update_token_count(input_tokens)  # 更新输入token计数（流式响应无法立即获取完成token数）

            response = await self.client.chat.completions.create(**params, stream=True)  # 创建流式完成请求

            collected_messages = []  # 初始化收集的消息列表
            completion_text = ""  # 初始化完成文本
            async for chunk in response:  # 遍历流式响应块
                chunk_message = chunk.choices[0].delta.content or ""  # 获取块内容，如果为空则使用空字符串
                collected_messages.append(chunk_message)  # 添加到收集列表
                completion_text += chunk_message  # 累加到完成文本
                print(chunk_message, end="", flush=True)  # 实时打印块内容

            print()  # 流式输出后的换行
            full_response = "".join(collected_messages).strip()  # 连接所有消息并去除首尾空白
            if not full_response:  # 如果完整响应为空
                raise ValueError("Empty response from streaming LLM")  # 抛出值错误

            # 估计流式响应的完成token数
            completion_tokens = self.count_tokens(completion_text)  # 计算完成文本的token数
            logger.info(
                f"Estimated completion tokens for streaming response: {completion_tokens}"  # 记录估计的完成token数
            )
            self.total_completion_tokens += completion_tokens  # 累加完成token数

            return full_response  # 返回完整响应

        except TokenLimitExceeded:  # 捕获Token限制超出异常
            # 重新抛出token限制错误，不记录日志（避免重复日志）
            raise  # 直接重新抛出
        except ValueError:  # 捕获值错误
            logger.exception(f"Validation error")  # 记录异常日志（包含堆栈跟踪）
            raise  # 重新抛出异常
        except OpenAIError as oe:  # 捕获OpenAI错误
            logger.exception(f"OpenAI API error")  # 记录异常日志
            if isinstance(oe, AuthenticationError):  # 如果是认证错误
                logger.error("Authentication failed. Check API key.")  # 记录认证失败错误
            elif isinstance(oe, RateLimitError):  # 如果是速率限制错误
                logger.error("Rate limit exceeded. Consider increasing retry attempts.")  # 记录速率限制错误
            elif isinstance(oe, APIError):  # 如果是API错误
                logger.error(f"API error: {oe}")  # 记录API错误
            raise  # 重新抛出异常
        except Exception:  # 捕获其他异常
            logger.exception(f"Unexpected error in ask")  # 记录意外错误日志
            raise  # 重新抛出异常

    @retry(
        wait=wait_random_exponential(min=1, max=60),
        stop=stop_after_attempt(6),
        retry=retry_if_exception_type(
            (OpenAIError, Exception, ValueError)
        ),  # Don't retry TokenLimitExceeded
    )
    async def ask_with_images(
        self,
        messages: List[Union[dict, Message]],
        images: List[Union[str, dict]],
        system_msgs: Optional[List[Union[dict, Message]]] = None,
        stream: bool = False,
        temperature: Optional[float] = None,
    ) -> str:
        """
        Send a prompt with images to the LLM and get the response.

        Args:
            messages: List of conversation messages
            images: List of image URLs or image data dictionaries
            system_msgs: Optional system messages to prepend
            stream (bool): Whether to stream the response
            temperature (float): Sampling temperature for the response

        Returns:
            str: The generated response

        Raises:
            TokenLimitExceeded: If token limits are exceeded
            ValueError: If messages are invalid or response is empty
            OpenAIError: If API call fails after retries
            Exception: For unexpected errors
        """
        try:
            # 对于ask_with_images，我们总是将supports_images设置为True，因为
            # 此方法应该只在使用支持图像的模型时调用
            if self.model not in MULTIMODAL_MODELS:  # 如果模型不在多模态模型列表中
                raise ValueError(
                    f"Model {self.model} does not support images. Use a model from {MULTIMODAL_MODELS}"  # 抛出值错误
                )

            # 使用图像支持格式化消息
            formatted_messages = self.format_messages(messages, supports_images=True)  # 格式化消息，启用图像支持

            # 确保最后一条消息来自用户，以便附加图像
            if not formatted_messages or formatted_messages[-1]["role"] != "user":  # 如果消息列表为空或最后一条不是用户消息
                raise ValueError(
                    "The last message must be from the user to attach images"  # 抛出值错误
                )

            # 处理最后一条用户消息以包含图像
            last_message = formatted_messages[-1]  # 获取最后一条消息

            # 如果需要，将content转换为多模态格式
            content = last_message["content"]  # 获取消息内容
            multimodal_content = (
                [{"type": "text", "text": content}]  # 如果是字符串，转换为文本对象列表
                if isinstance(content, str)  # 检查是否为字符串
                else content  # 如果已经是列表，直接使用
                if isinstance(content, list)  # 检查是否为列表
                else []  # 否则使用空列表
            )

            # 将图像添加到content
            for image in images:  # 遍历所有图像
                if isinstance(image, str):  # 如果图像是字符串（URL）
                    multimodal_content.append(  # 添加到多模态内容
                        {"type": "image_url", "image_url": {"url": image}}  # 创建图像URL对象
                    )
                elif isinstance(image, dict) and "url" in image:  # 如果图像是包含url的字典
                    multimodal_content.append({"type": "image_url", "image_url": image})  # 添加图像对象
                elif isinstance(image, dict) and "image_url" in image:  # 如果图像是包含image_url的字典
                    multimodal_content.append(image)  # 直接添加
                else:  # 其他格式不支持
                    raise ValueError(f"Unsupported image format: {image}")  # 抛出值错误

            # 使用多模态内容更新消息
            last_message["content"] = multimodal_content  # 更新消息内容

            # 如果提供了系统消息，则添加
            if system_msgs:  # 如果提供了系统消息
                all_messages = (
                    self.format_messages(system_msgs, supports_images=True)  # 格式化系统消息
                    + formatted_messages  # 加上格式化后的用户消息
                )
            else:  # 如果没有系统消息
                all_messages = formatted_messages  # 直接使用格式化后的消息

            # 计算token并检查限制
            input_tokens = self.count_message_tokens(all_messages)  # 计算输入token数
            if not self.check_token_limit(input_tokens):  # 如果超出限制
                raise TokenLimitExceeded(self.get_limit_error_message(input_tokens))  # 抛出Token限制超出异常

            # 设置API参数
            params = {
                "model": self.model,  # 模型名称
                "messages": all_messages,  # 所有消息
                "stream": stream,  # 流式标志
            }

            # 添加模型特定参数
            if self.model in REASONING_MODELS:  # 如果是推理模型
                params["max_completion_tokens"] = self.max_tokens  # 使用max_completion_tokens
            else:  # 如果是普通模型
                params["max_tokens"] = self.max_tokens  # 使用max_tokens
                params["temperature"] = (
                    temperature if temperature is not None else self.temperature  # 温度参数
                )

            # 处理非流式请求
            if not stream:  # 如果不是流式请求
                response = await self.client.chat.completions.create(**params)  # 创建完成请求

                if not response.choices or not response.choices[0].message.content:  # 如果响应无效
                    raise ValueError("Empty or invalid response from LLM")  # 抛出值错误

                self.update_token_count(response.usage.prompt_tokens)  # 更新token计数（只更新输入token）
                return response.choices[0].message.content  # 返回响应内容

            # 处理流式请求
            self.update_token_count(input_tokens)  # 更新输入token计数
            response = await self.client.chat.completions.create(**params)  # 创建流式完成请求

            collected_messages = []  # 初始化收集的消息列表
            async for chunk in response:  # 遍历流式响应块
                chunk_message = chunk.choices[0].delta.content or ""  # 获取块内容
                collected_messages.append(chunk_message)  # 添加到收集列表
                print(chunk_message, end="", flush=True)  # 实时打印

            print()  # 流式输出后的换行
            full_response = "".join(collected_messages).strip()  # 连接所有消息

            if not full_response:  # 如果响应为空
                raise ValueError("Empty response from streaming LLM")  # 抛出值错误

            return full_response  # 返回完整响应

        except TokenLimitExceeded:  # 捕获Token限制超出异常
            raise  # 直接重新抛出
        except ValueError as ve:  # 捕获值错误
            logger.error(f"Validation error in ask_with_images: {ve}")  # 记录验证错误
            raise  # 重新抛出
        except OpenAIError as oe:  # 捕获OpenAI错误
            logger.error(f"OpenAI API error: {oe}")  # 记录API错误
            if isinstance(oe, AuthenticationError):  # 如果是认证错误
                logger.error("Authentication failed. Check API key.")  # 记录认证失败
            elif isinstance(oe, RateLimitError):  # 如果是速率限制错误
                logger.error("Rate limit exceeded. Consider increasing retry attempts.")  # 记录速率限制错误
            elif isinstance(oe, APIError):  # 如果是API错误
                logger.error(f"API error: {oe}")  # 记录API错误
            raise  # 重新抛出
        except Exception as e:  # 捕获其他异常
            logger.error(f"Unexpected error in ask_with_images: {e}")  # 记录意外错误
            raise  # 重新抛出

    @retry(
        wait=wait_random_exponential(min=1, max=60),
        stop=stop_after_attempt(6),
        retry=retry_if_exception_type(
            (OpenAIError, Exception, ValueError)
        ),  # Don't retry TokenLimitExceeded
    )
    async def ask_tool(
        self,
        messages: List[Union[dict, Message]],
        system_msgs: Optional[List[Union[dict, Message]]] = None,
        timeout: int = 300,
        tools: Optional[List[dict]] = None,
        tool_choice: TOOL_CHOICE_TYPE = ToolChoice.AUTO,  # type: ignore
        temperature: Optional[float] = None,
        **kwargs,
    ) -> ChatCompletionMessage | None:
        """
        Ask LLM using functions/tools and return the response.

        Args:
            messages: List of conversation messages
            system_msgs: Optional system messages to prepend
            timeout: Request timeout in seconds
            tools: List of tools to use
            tool_choice: Tool choice strategy
            temperature: Sampling temperature for the response
            **kwargs: Additional completion arguments

        Returns:
            ChatCompletionMessage: The model's response

        Raises:
            TokenLimitExceeded: If token limits are exceeded
            ValueError: If tools, tool_choice, or messages are invalid
            OpenAIError: If API call fails after retries
            Exception: For unexpected errors
        """
        try:
            # 验证tool_choice
            if tool_choice not in TOOL_CHOICE_VALUES:  # 如果工具选择不在有效值中
                raise ValueError(f"Invalid tool_choice: {tool_choice}")  # 抛出值错误

            # 检查模型是否支持图像
            supports_images = self.model in MULTIMODAL_MODELS  # 检查模型是否在多模态模型列表中

            # 格式化消息
            if system_msgs:  # 如果提供了系统消息
                system_msgs = self.format_messages(system_msgs, supports_images)  # 格式化系统消息
                messages = system_msgs + self.format_messages(messages, supports_images)  # 合并系统消息和用户消息
            else:  # 如果没有系统消息
                messages = self.format_messages(messages, supports_images)  # 只格式化用户消息

            # 计算输入token数量
            input_tokens = self.count_message_tokens(messages)  # 计算消息的token数

            # 如果有工具，计算工具描述的token数量
            tools_tokens = 0  # 初始化工具token计数
            if tools:  # 如果提供了工具
                for tool in tools:  # 遍历所有工具
                    tools_tokens += self.count_tokens(str(tool))  # 计算工具描述的token数并累加

            input_tokens += tools_tokens  # 将工具token数加到输入token数中

            # 检查token限制是否超出
            if not self.check_token_limit(input_tokens):  # 如果超出限制
                error_message = self.get_limit_error_message(input_tokens)  # 获取错误消息
                # 抛出一个特殊异常，不会被重试
                raise TokenLimitExceeded(error_message)  # 抛出Token限制超出异常

            # 如果提供了工具，验证工具格式
            if tools:  # 如果提供了工具
                for tool in tools:  # 遍历所有工具
                    if not isinstance(tool, dict) or "type" not in tool:  # 如果工具不是字典或缺少type字段
                        raise ValueError("Each tool must be a dict with 'type' field")  # 抛出值错误

            # 设置完成请求参数
            params = {
                "model": self.model,  # 模型名称
                "messages": messages,  # 消息列表
                "tools": tools,  # 工具列表
                "tool_choice": tool_choice,  # 工具选择策略
                "timeout": timeout,  # 超时时间
                **kwargs,  # 其他参数
            }

            if self.model in REASONING_MODELS:  # 如果是推理模型
                params["max_completion_tokens"] = self.max_tokens  # 使用max_completion_tokens
            else:  # 如果是普通模型
                params["max_tokens"] = self.max_tokens  # 使用max_tokens
                params["temperature"] = (
                    temperature if temperature is not None else self.temperature  # 温度参数
                )

            params["stream"] = False  # 工具请求始终使用非流式
            response: ChatCompletion = await self.client.chat.completions.create(
                **params  # 创建完成请求
            )

            # 检查响应是否有效
            if not response.choices or not response.choices[0].message:  # 如果响应无效
                print(response)  # 打印响应（用于调试）
                # raise ValueError("Invalid or empty response from LLM")  # 已注释：不抛出异常
                return None  # 返回None

            # 更新token计数
            self.update_token_count(
                response.usage.prompt_tokens, response.usage.completion_tokens  # 传入输入和完成token数
            )

            return response.choices[0].message  # 返回消息对象

        except TokenLimitExceeded:  # 捕获Token限制超出异常
            # 重新抛出token限制错误，不记录日志
            raise  # 直接重新抛出
        except ValueError as ve:  # 捕获值错误
            logger.error(f"Validation error in ask_tool: {ve}")  # 记录验证错误
            raise  # 重新抛出
        except OpenAIError as oe:  # 捕获OpenAI错误
            logger.error(f"OpenAI API error: {oe}")  # 记录API错误
            if isinstance(oe, AuthenticationError):  # 如果是认证错误
                logger.error("Authentication failed. Check API key.")  # 记录认证失败
            elif isinstance(oe, RateLimitError):  # 如果是速率限制错误
                logger.error("Rate limit exceeded. Consider increasing retry attempts.")  # 记录速率限制错误
            elif isinstance(oe, APIError):  # 如果是API错误
                logger.error(f"API error: {oe}")  # 记录API错误
            raise  # 重新抛出
        except Exception as e:  # 捕获其他异常
            logger.error(f"Unexpected error in ask_tool: {e}")  # 记录意外错误
            raise  # 重新抛出
