# OpenManus 源码阅读指南

本文档为开发者提供OpenManus源码的阅读指南，帮助理解代码结构和关键实现细节。

## 1. 项目结构

```
OpenManus/
├── app/                          # 核心应用代码
│   ├── agent/                    # 代理实现
│   │   ├── base.py              # 代理基类
│   │   ├── react.py             # ReAct模式实现
│   │   ├── toolcall.py          # 工具调用代理
│   │   ├── manus.py             # Manus通用代理
│   │   └── ...
│   ├── tool/                     # 工具实现
│   │   ├── base.py              # 工具基类
│   │   ├── tool_collection.py   # 工具集合
│   │   ├── python_execute.py   # Python执行工具
│   │   ├── browser_use_tool.py  # 浏览器工具
│   │   └── ...
│   ├── llm.py                    # LLM客户端
│   ├── config.py                 # 配置管理
│   ├── schema.py                 # 数据模型
│   ├── logger.py                 # 日志系统
│   ├── exceptions.py             # 异常定义
│   ├── flow/                     # 流程管理
│   ├── sandbox/                  # 沙箱实现
│   ├── mcp/                      # MCP协议实现
│   └── prompt/                   # 提示词模板
├── main.py                       # 主入口
├── run_flow.py                   # 流程运行入口
├── run_mcp.py                    # MCP运行入口
├── config/                       # 配置文件
└── tests/                        # 测试代码
```

## 2. 阅读路径建议

### 2.1 入门路径（理解基本流程）

**第一步：入口文件**
- `main.py` - 了解程序如何启动
- 关注：参数解析、代理创建、执行流程

**第二步：核心代理**
- `app/agent/base.py` - 理解代理基类
  - 重点：`run()`方法（执行循环）、`step()`方法（单步执行）
  - 状态管理：`state_context()`、`is_stuck()`

- `app/agent/react.py` - 理解ReAct模式
  - 重点：`think()`和`act()`的分离

- `app/agent/toolcall.py` - 理解工具调用机制
  - 重点：`think()`（调用LLM）、`act()`（执行工具）
  - 工具执行流程：`execute_tool()`

**第三步：工具系统**
- `app/tool/base.py` - 理解工具接口
  - 重点：`BaseTool`类、`ToolResult`类

- `app/tool/tool_collection.py` - 理解工具管理
  - 重点：工具注册、查找、执行

**第四步：LLM集成**
- `app/llm.py` - 理解LLM客户端
  - 重点：`ask()`、`ask_tool()`方法
  - Token计数：`TokenCounter`类

### 2.2 进阶路径（深入理解）

**第一步：配置系统**
- `app/config.py` - 理解配置加载和管理
  - 重点：单例模式、配置解析、多配置支持

**第二步：具体代理实现**
- `app/agent/manus.py` - 理解Manus代理
  - 重点：MCP集成、浏览器上下文、工具集合配置

**第三步：工具实现**
- `app/tool/python_execute.py` - Python执行工具
- `app/tool/browser_use_tool.py` - 浏览器工具
- `app/tool/str_replace_editor.py` - 文件编辑工具

**第四步：流程管理**
- `app/flow/base.py` - 流程基类
- `app/flow/planning.py` - 规划流程实现
- `app/flow/flow_factory.py` - 流程工厂

**第五步：基础设施**
- `app/sandbox/client.py` - 沙箱客户端
- `app/mcp/server.py` - MCP服务器
- `app/agent/browser.py` - 浏览器辅助

## 3. 关键代码解析

### 3.1 代理执行循环（BaseAgent.run）

**文件位置**: `app/agent/base.py`

**方法签名**: `async def run(self, request: Optional[str] = None) -> str`

**功能说明**:
这是代理的主执行循环，负责管理整个执行流程。它确保代理从正确的状态开始，管理执行步骤，检测卡死状态，并在完成后清理资源。

**代码解析**:
```python
async def run(self, request: Optional[str] = None) -> str:
    # 1. 状态验证：确保代理处于IDLE状态才能开始执行
    #    如果代理已经在运行或已完成，抛出异常防止重复执行
    if self.state != AgentState.IDLE:
        raise RuntimeError(f"Cannot run agent from state: {self.state}")

    # 2. 添加用户请求到内存
    #    如果提供了请求文本，将其作为用户消息添加到对话内存中
    if request:
        self.update_memory("user", request)

    # 3. 初始化结果列表，用于收集每步的执行结果
    results: List[str] = []

    # 4. 使用状态上下文管理器进入RUNNING状态
    #    状态上下文确保状态转换的原子性和异常安全
    async with self.state_context(AgentState.RUNNING):
        # 5. 主执行循环：持续执行直到达到最大步数或完成状态
        while (
            self.current_step < self.max_steps and  # 未超过最大步数限制
            self.state != AgentState.FINISHED       # 未达到完成状态
        ):
            # 5.1 增加步数计数器
            self.current_step += 1

            # 5.2 执行单步操作（抽象方法，由子类实现）
            #     子类会实现具体的思考-行动逻辑
            step_result = await self.step()

            # 5.3 卡死检测：检查代理是否陷入重复响应循环
            #     通过比较最近N条消息的内容来判断
            if self.is_stuck():
                # 如果检测到卡死，调用处理函数（可能终止或重置）
                self.handle_stuck_state()

            # 5.4 记录步骤结果
            results.append(f"Step {self.current_step}: {step_result}")

    # 6. 清理沙箱资源（确保Docker容器等资源被释放）
    await SANDBOX_CLIENT.cleanup()

    # 7. 返回所有步骤的结果，用换行符连接
    return "\n".join(results)
```

**关键设计点**:
1. **状态管理**: 使用`state_context`上下文管理器确保状态转换的原子性
2. **异常安全**: 如果发生异常，状态上下文会自动回滚到之前的状态
3. **资源清理**: 无论成功还是失败，都会清理沙箱资源
4. **卡死检测**: 防止代理陷入无限循环，提高系统稳定性
5. **步数限制**: 通过`max_steps`防止无限执行

**相关方法**:
- `step()`: 抽象方法，子类必须实现
- `is_stuck()`: 检测是否卡死（检查最近N条消息是否重复）
- `handle_stuck_state()`: 处理卡死状态（默认终止执行）
- `state_context()`: 状态上下文管理器（使用`@asynccontextmanager`装饰）

### 3.2 工具调用流程（ToolCallAgent.think）

**文件位置**: `app/agent/toolcall.py`

**方法签名**: `async def think(self) -> bool`

**功能说明**:
这是ReAct模式中的"思考"阶段。代理调用LLM，传入当前对话历史和可用工具列表，让LLM决定是否需要调用工具以及调用哪些工具。

**代码解析**:
```python
async def think(self) -> bool:
    # 1. 动态提示词注入
    #    如果设置了next_step_prompt（如浏览器上下文、计划步骤等），
    #    将其作为用户消息添加到对话中，引导LLM的下一步行动
    if self.next_step_prompt:
        user_msg = Message.user_message(self.next_step_prompt)
        self.messages += [user_msg]  # 添加到消息列表

    try:
        # 2. 调用LLM的工具调用接口
        #    ask_tool()是专门用于工具调用的方法，必须非流式调用
        response = await self.llm.ask_tool(
            messages=self.messages,                    # 当前对话历史
            system_msgs=[Message.system_message(self.system_prompt)],  # 系统提示词
            tools=self.available_tools.to_params(),   # 可用工具列表（JSON Schema格式）
            tool_choice=self.tool_choices,             # 工具选择策略（AUTO/NONE/REQUIRED）
        )

        # 3. 解析LLM响应
        #    tool_calls: LLM决定调用的工具列表（可能为空）
        #    content: LLM生成的文本内容（可能为空，如果只调用工具）
        self.tool_calls = response.tool_calls if response else []
        content = response.content if response else ""

        # 4. 创建助手消息并添加到内存
        #    这个消息包含LLM的回复和工具调用决策
        assistant_msg = Message.from_tool_calls(
            content=content,           # 文本内容
            tool_calls=self.tool_calls # 工具调用列表
        )
        self.memory.add_message(assistant_msg)

        # 5. 返回是否有工具调用
        #    True表示需要执行工具（进入act阶段）
        #    False表示只需要文本回复（不需要act阶段）
        return bool(self.tool_calls)

    except TokenLimitExceeded as e:
        # Token超限异常：设置代理状态为ERROR并返回False
        # 这会导致代理停止执行，因为无法继续调用LLM
        self.state = AgentState.ERROR
        logger.error(f"Token limit exceeded: {e}")
        return False
    except Exception as e:
        # 其他异常：记录错误并返回False
        logger.error(f"Error in think(): {e}")
        return False
```

**关键设计点**:
1. **动态提示词**: `next_step_prompt`允许代理根据上下文动态调整提示词
2. **工具选择策略**: `tool_choice`控制LLM是否必须使用工具
   - `AUTO`: LLM自主决定
   - `REQUIRED`: 必须使用工具
   - `NONE`: 不使用工具
3. **消息格式**: 使用`Message.from_tool_calls()`创建包含工具调用的消息
4. **错误处理**: Token超限时设置ERROR状态，其他错误记录日志

**相关方法**:
- `act()`: 执行阶段，实际调用工具
- `llm.ask_tool()`: LLM工具调用接口
- `available_tools.to_params()`: 将工具集合转换为LLM函数调用格式

### 3.3 工具执行（ToolCallAgent.act）

**文件位置**: `app/agent/toolcall.py`

**方法签名**: `async def act(self) -> str`

**功能说明**:
这是ReAct模式中的"行动"阶段。代理执行在think阶段决定的工具调用，将工具执行结果添加到对话历史中，供下一轮思考使用。

**代码解析**:
```python
async def act(self) -> str:
    # 1. 验证工具调用存在
    #    如果tool_choice是REQUIRED但没有工具调用，抛出异常
    if self.tool_choices == ToolChoice.REQUIRED and not self.tool_calls:
        raise ValueError("Tool choice is REQUIRED but no tool calls found")

    # 2. 如果没有工具调用，返回最后一条消息的内容
    #    这种情况发生在LLM只生成文本回复时
    if not self.tool_calls:
        return self.messages[-1].content or "No content"

    # 3. 初始化结果列表
    results = []

    # 4. 遍历并执行每个工具调用
    #    LLM可能同时决定调用多个工具（并行或顺序执行）
    for command in self.tool_calls:
        # 4.1 执行单个工具调用
        #     execute_tool()会查找工具、解析参数、执行并处理结果
        result = await self.execute_tool(command)

        # 4.2 限制观察长度
        #     防止工具输出过长导致Token超限
        #     如果设置了max_observe，截断结果并添加省略标记
        if self.max_observe and len(result) > self.max_observe:
            result = result[:self.max_observe] + "... (truncated)"

        # 4.3 创建工具消息
        #     工具消息必须包含tool_call_id，用于关联assistant消息中的工具调用
        tool_msg = Message.tool_message(
            content=result,                    # 工具执行结果
            tool_call_id=command.id,           # 工具调用ID（关联assistant消息）
            name=command.function.name,        # 工具名称（用于调试和日志）
        )

        # 4.4 将工具消息添加到内存
        #     这样下一轮think()时，LLM可以看到工具执行结果
        self.memory.add_message(tool_msg)

        # 4.5 收集结果用于返回
        results.append(result)

    # 5. 返回所有工具执行结果，用双换行符分隔
    #    这会被添加到step()的返回结果中
    return "\n\n".join(results)
```

**关键设计点**:
1. **工具调用验证**: 如果要求必须使用工具但没有调用，抛出异常
2. **结果截断**: `max_observe`防止工具输出过长
3. **消息关联**: 使用`tool_call_id`关联工具消息和assistant消息
4. **顺序执行**: 工具按顺序执行（可改为并发执行以提高性能）

**相关方法**:
- `execute_tool()`: 执行单个工具调用的核心方法
- `_handle_special_tool()`: 处理特殊工具（如Terminate）
- `Message.tool_message()`: 创建工具消息的便捷方法

### 3.4 工具查找和执行（ToolCallAgent.execute_tool）

**文件位置**: `app/agent/toolcall.py`

**方法签名**: `async def execute_tool(self, command: ToolCall) -> str`

**功能说明**:
这是执行单个工具调用的核心方法。它负责查找工具、解析参数、执行工具、处理特殊工具，并格式化返回结果。

**代码解析**:
```python
async def execute_tool(self, command: ToolCall) -> str:
    # 1. 提取工具名称
    #    command是LLM返回的ToolCall对象，包含工具名称和参数
    name = command.function.name

    # 2. 验证命令格式
    #    确保工具名称和参数都存在
    if not name or not command.function.arguments:
        return f"Error: Invalid tool call format"

    # 3. 查找工具
    #    从available_tools的tool_map字典中查找工具实例
    #    如果工具不存在，返回错误消息
    if name not in self.available_tools.tool_map:
        return f"Error: Unknown tool '{name}'"

    try:
        # 4. 解析参数
        #    LLM返回的参数是JSON字符串，需要解析为Python字典
        #    如果解析失败，会抛出JSONDecodeError异常
        args = json.loads(command.function.arguments or "{}")

        # 5. 执行工具
        #    通过ToolCollection.execute()执行工具
        #    这会调用工具的execute()方法，传入解析后的参数
        result = await self.available_tools.execute(
            name=name,        # 工具名称
            tool_input=args   # 参数字典
        )

        # 6. 处理特殊工具
        #    某些工具（如Terminate）需要特殊处理
        #    例如Terminate工具会设置代理状态为FINISHED
        await self._handle_special_tool(name=name, result=result)

        # 7. 处理图像结果
        #    如果工具返回了base64图像（如浏览器截图），保存到_current_base64_image
        #    这样可以在下一轮LLM调用时包含图像
        if hasattr(result, 'base64_image') and result.base64_image:
            self._current_base64_image = result.base64_image

        # 8. 格式化观察字符串
        #    将工具执行结果格式化为观察消息
        #    格式：Observed output of cmd `工具名` executed:\n结果
        observation = f"Observed output of cmd `{name}` executed:\n{str(result)}"
        return observation

    except json.JSONDecodeError as e:
        # JSON解析错误：参数格式不正确
        return f"Error parsing arguments for {name}: {str(e)}"
    except Exception as e:
        # 其他异常：工具执行失败
        logger.error(f"Error executing tool {name}: {e}")
        return f"Error executing {name}: {str(e)}"
```

**关键设计点**:
1. **工具查找**: 使用字典查找，O(1)时间复杂度
2. **参数验证**: 检查参数格式和工具存在性
3. **错误处理**: 捕获所有异常，返回友好的错误消息
4. **特殊工具**: 通过`_handle_special_tool()`处理终止等特殊逻辑
5. **图像支持**: 支持工具返回base64图像，用于多模态LLM输入

**相关方法**:
- `_handle_special_tool()`: 处理特殊工具（如Terminate）
- `_should_finish_execution()`: 判断是否应该结束执行
- `available_tools.execute()`: ToolCollection的工具执行方法

### 3.5 LLM工具调用（LLM.ask_tool）

**文件位置**: `app/llm.py`

**方法签名**: `async def ask_tool(self, messages, tools, tool_choice, **kwargs) -> ChatCompletionMessage`

**功能说明**:
这是LLM客户端的工具调用接口。它负责格式化消息、计算Token、调用LLM API、处理工具调用响应。工具调用必须使用非流式模式，因为需要获取完整的工具调用信息。

**代码解析**:
```python
async def ask_tool(
    self,
    messages: List[Union[dict, Message]],      # 对话消息列表
    tools: Optional[List[dict]] = None,        # 工具定义列表（JSON Schema格式）
    tool_choice: TOOL_CHOICE_TYPE = ToolChoice.AUTO,  # 工具选择策略
    **kwargs,
) -> ChatCompletionMessage:
    # 1. 格式化消息
    #    将Message对象转换为API格式的字典
    #    supports_images=True表示支持图像输入（多模态）
    formatted_messages = self.format_messages(messages, supports_images=True)

    # 2. 计算Token数量
    #    包括消息内容的Token和工具描述的Token
    input_tokens = self.count_message_tokens(formatted_messages)

    # 2.1 添加工具描述的Token
    #     每个工具的name、description、parameters都会消耗Token
    if tools:
        for tool in tools:
            # 将工具定义转换为字符串并计算Token
            input_tokens += self.count_tokens(str(tool))

    # 3. 检查Token限制
    #    如果超过最大Token限制，抛出TokenLimitExceeded异常
    #    这会导致代理停止执行
    if not self.check_token_limit(input_tokens):
        raise TokenLimitExceeded(
            message=self.get_limit_error_message(input_tokens),
            input_tokens=input_tokens,
            max_tokens=self.max_input_tokens,
        )

    # 4. 准备API调用参数
    params = {
        "model": self.model,                    # 模型名称（如gpt-4）
        "messages": formatted_messages,         # 格式化后的消息列表
        "tools": tools,                         # 工具定义列表
        "tool_choice": tool_choice.value if isinstance(tool_choice, ToolChoice) else tool_choice,  # 工具选择策略
        "stream": False,                        # 必须非流式（工具调用需要完整响应）
        **kwargs                                # 其他参数（temperature等）
    }

    # 5. 调用LLM API
    #    使用重试装饰器自动重试失败的请求
    #    支持OpenAI、Azure OpenAI、AWS Bedrock等多种提供商
    response = await self.client.chat.completions.create(**params)

    # 6. 更新Token计数
    #    记录本次调用的Token使用量，用于统计和监控
    self.update_token_count(
        response.usage.prompt_tokens,      # 输入Token数
        response.usage.completion_tokens   # 输出Token数
    )

    # 7. 返回消息对象
    #    消息对象包含content（文本内容）和tool_calls（工具调用列表）
    return response.choices[0].message
```

**关键设计点**:
1. **非流式调用**: 工具调用必须非流式，因为需要获取完整的`tool_calls`信息
2. **Token计算**: 包括消息和工具描述的Token，确保不超过限制
3. **多模态支持**: `supports_images=True`支持图像输入
4. **重试机制**: 使用`@retry`装饰器自动重试失败的请求
5. **多提供商支持**: 统一接口支持OpenAI、Azure、AWS等

**相关方法**:
- `format_messages()`: 格式化消息，支持图像
- `count_message_tokens()`: 计算消息Token数
- `count_tokens()`: 计算文本Token数
- `check_token_limit()`: 检查Token限制
- `update_token_count()`: 更新Token计数

### 3.6 配置加载（Config._load_initial_config）

**文件位置**: `app/config.py`

**方法签名**: `def _load_initial_config(self) -> None`

**功能说明**:
这是配置系统的核心方法，负责加载和解析TOML配置文件，构建完整的配置对象。它支持多LLM配置、配置覆盖、默认值处理等功能。

**代码解析**:
```python
def _load_initial_config(self):
    # 1. 加载TOML配置文件
    #    从config/config.toml读取原始配置数据
    #    使用tomllib（Python 3.11+）或tomli（兼容库）解析
    raw_config = self._load_config()

    # 2. 解析LLM配置
    #    2.1 获取基础LLM配置（所有LLM配置的默认值）
    base_llm = raw_config.get("llm", {})

    #    2.2 提取覆盖配置（以"llm_"开头的键）
    #        例如：llm_vision, llm_fast等
    llm_overrides = {}
    for key, value in raw_config.items():
        if key.startswith("llm_"):
            llm_name = key[4:]  # 移除"llm_"前缀，得到配置名称
            llm_overrides[llm_name] = value

    #    2.3 构建默认LLM设置
    #        使用Pydantic模型验证和转换配置
    default_settings = LLMSettings(**base_llm)

    #    2.4 构建所有LLM配置字典
    #        默认配置 + 覆盖配置
    llm_configs = {"default": default_settings}
    for name, override in llm_overrides.items():
        # 合并默认配置和覆盖配置
        llm_configs[name] = LLMSettings(**{**base_llm, **override})

    # 3. 解析浏览器配置
    browser_config = raw_config.get("browser", {})
    browser_settings = None
    if browser_config:
        # 3.1 处理代理设置（可选）
        proxy_settings = None
        if browser_config.get("proxy"):
            proxy_settings = ProxySettings(**browser_config["proxy"])

        # 3.2 构建浏览器设置对象
        browser_settings = BrowserSettings(
            headless=browser_config.get("headless", False),
            proxy=proxy_settings,
            disable_security=browser_config.get("disable_security", False),
            # ... 其他浏览器配置项
        )

    # 4. 解析沙箱配置
    sandbox_config = raw_config.get("sandbox", {})
    sandbox_settings = SandboxSettings(**sandbox_config) if sandbox_config else SandboxSettings()

    # 5. 解析搜索配置
    search_config = raw_config.get("search", {})
    search_settings = SearchSettings(**search_config) if search_config else SearchSettings()

    # 6. 解析MCP配置
    #    从config/mcp.json加载MCP服务器配置
    mcp_config_path = PROJECT_ROOT / "config" / "mcp.json"
    mcp_settings = self._load_mcp_config(mcp_config_path) if mcp_config_path.exists() else MCPSettings()

    # 7. 解析其他配置...
    runflow_settings = RunflowSettings(**raw_config.get("runflow", {}))
    daytona_settings = DaytonaSettings(**raw_config.get("daytona", {}))

    # 8. 构建完整配置对象
    #    使用Pydantic模型验证所有配置
    self._config = AppConfig(
        llm=llm_configs,              # 多LLM配置字典
        browser_config=browser_settings,  # 浏览器配置
        sandbox=sandbox_settings,      # 沙箱配置
        search_config=search_settings,  # 搜索配置
        mcp_config=mcp_settings,       # MCP配置
        run_flow_config=runflow_settings,  # 流程配置
        daytona=daytona_settings,      # Daytona配置
    )
```

**关键设计点**:
1. **单例模式**: 使用双重检查锁定确保只有一个Config实例
2. **配置合并**: 支持默认配置+覆盖配置的合并机制
3. **多LLM配置**: 支持多个LLM配置（default、vision、fast等）
4. **Pydantic验证**: 所有配置使用Pydantic模型自动验证和转换
5. **默认值处理**: 配置项缺失时使用合理的默认值
6. **文件分离**: MCP配置单独存储在JSON文件中

**配置示例**:
```toml
# config/config.toml
[llm]
model = "gpt-4"
api_type = "openai"
temperature = 0.7

[llm_vision]
model = "gpt-4-vision-preview"
temperature = 0.5

[browser]
headless = false
disable_security = true

[browser.proxy]
server = "http://proxy.example.com:8080"
```

**相关方法**:
- `_load_config()`: 加载TOML文件
- `_load_mcp_config()`: 加载MCP JSON配置
- `__getattr__()`: 提供配置访问接口（如`config.llm_config`）

## 4. 关键设计模式

### 4.1 单例模式
- **Config类**: 双重检查锁定
- **LLM类**: 类字典缓存

### 4.2 工厂模式
- **FlowFactory**: 创建流程
- **Manus.create()**: 创建代理实例

### 4.3 模板方法模式
- **BaseAgent.run()**: 定义执行框架
- **ReActAgent.step()**: 定义think-act模式

### 4.4 策略模式
- **ToolChoice**: 工具选择策略
- **不同代理**: 不同执行策略

## 5. 调试技巧

### 5.1 日志查看
- 日志文件：`logs/`目录
- 日志级别：通过`define_log_level()`调整
- 关键日志点：
  - 代理状态变化
  - 工具调用
  - LLM请求/响应
  - 错误信息

### 5.2 断点设置建议
1. **代理执行循环**: `BaseAgent.run()`入口
2. **工具调用**: `ToolCallAgent.think()`和`act()`
3. **LLM调用**: `LLM.ask_tool()`入口和返回
4. **工具执行**: `ToolCallAgent.execute_tool()`
5. **配置加载**: `Config._load_initial_config()`

### 5.3 常见问题排查

**问题1：代理卡死**
- 检查：`is_stuck()`逻辑
- 查看：最近消息是否有重复
- 解决：调整`duplicate_threshold`

**问题2：Token超限**
- 检查：`check_token_limit()`
- 查看：Token计数日志
- 解决：减少消息历史或增加限制

**问题3：工具执行失败**
- 检查：工具是否注册
- 查看：参数解析是否正确
- 解决：检查工具参数Schema

**问题4：MCP连接失败**
- 检查：`mcp.json`配置
- 查看：MCP服务器日志
- 解决：验证服务器URL/命令

## 6. 代码修改指南

### 6.1 添加新工具

**步骤**:
1. 在`app/tool/`创建新文件
2. 继承`BaseTool`并实现`execute()`
3. 定义`name`、`description`、`parameters`
4. 在`app/tool/__init__.py`导出
5. 在代理的`available_tools`中添加

**示例**:
```python
# app/tool/my_tool.py
from app.tool.base import BaseTool, ToolResult

class MyTool(BaseTool):
    name = "my_tool"
    description = "我的工具"
    parameters = {...}

    async def execute(self, param: str) -> ToolResult:
        # 实现逻辑
        return self.success_response("结果")
```

### 6.2 添加新代理

**步骤**:
1. 在`app/agent/`创建新文件
2. 继承`ToolCallAgent`或`ReActAgent`
3. 配置提示词和工具
4. 可选：覆盖`think()`或`act()`

**示例**:
```python
# app/agent/my_agent.py
from app.agent.toolcall import ToolCallAgent
from app.tool import ToolCollection, MyTool

class MyAgent(ToolCallAgent):
    name = "MyAgent"
    system_prompt = "..."
    available_tools = ToolCollection(MyTool())
```

### 6.3 修改配置结构

**步骤**:
1. 在`app/config.py`添加新的Settings类
2. 在`AppConfig`中添加字段
3. 在`_load_initial_config()`中解析
4. 更新`config.example.toml`

## 7. 测试阅读

### 7.1 单元测试
- 位置：`tests/`目录
- 重点：工具测试、LLM测试

### 7.2 集成测试
- 位置：`tests/`目录
- 重点：代理执行流程测试

## 8. 相关资源

### 8.1 外部依赖
- **OpenAI SDK**: LLM API调用
- **Playwright**: 浏览器自动化
- **Docker**: 沙箱隔离
- **Pydantic**: 数据验证
- **Loguru**: 日志系统

### 8.2 参考文档
- **架构文档**: `ARCHITECTURE.md`
- **设计文档**: `DESIGN.md`
- **README**: `README.md`

## 9. 代码质量检查

### 9.1 代码风格
- 遵循PEP 8
- 使用类型提示
- 添加文档字符串

### 9.2 测试覆盖
- 单元测试覆盖率
- 集成测试覆盖主要流程

### 9.3 性能考虑
- 异步操作
- 资源清理
- Token优化

## 10. 贡献指南

### 10.1 提交前检查
1. 运行测试：`pytest`
2. 代码格式化：`black`
3. 类型检查：`mypy`
4. 文档更新

### 10.2 提交信息
- 清晰描述变更
- 关联Issue（如有）
- 遵循提交规范
