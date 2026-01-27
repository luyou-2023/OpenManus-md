# OpenManus 详细设计文档

## 1. 设计概述

OpenManus采用分层架构设计，核心思想是将AI代理的能力通过工具系统进行扩展。系统设计遵循SOLID原则，注重可扩展性和可维护性。本文档详细描述了各个核心组件的设计细节、实现原理和关键决策。

### 1.1 设计原则

- **单一职责原则**: 每个类只负责一个明确的功能
- **开闭原则**: 对扩展开放，对修改关闭
- **依赖倒置**: 依赖抽象而非具体实现
- **接口隔离**: 使用小而专的接口
- **里氏替换**: 子类可以替换父类

### 1.2 核心设计理念

1. **工具化扩展**: 通过工具系统扩展代理能力
2. **状态驱动**: 基于状态机的执行流程
3. **异步优先**: 所有I/O操作采用异步设计
4. **类型安全**: 使用Pydantic进行数据验证
5. **资源管理**: 使用上下文管理器确保资源清理

## 2. 核心类设计

### 2.1 BaseAgent - 代理基类

**文件位置**: `app/agent/base.py`

**职责**:
- 管理代理状态（IDLE, RUNNING, FINISHED, ERROR）
- 维护对话内存（Memory）
- 提供执行循环框架
- 检测和处理卡死状态
- 管理执行步数和限制

**关键属性**:
```python
name: str                          # 代理名称
description: str                   # 代理描述
system_prompt: str                 # 系统提示词
next_step_prompt: str             # 下一步提示词
llm: LLM                          # LLM客户端实例
memory: Memory                    # 对话内存
state: AgentState                 # 当前状态
max_steps: int = 20               # 最大执行步数
current_step: int = 0             # 当前步数
duplicate_threshold: int = 3      # 卡死检测阈值
```

**关键方法**:
```python
async def run(request: str) -> str:
    """主执行循环"""
    # 1. 验证状态（必须是IDLE）
    if self.state != AgentState.IDLE:
        raise RuntimeError(...)

    # 2. 添加用户请求到内存
    if request:
        self.update_memory("user", request)

    # 3. 进入RUNNING状态（使用上下文管理器）
    async with self.state_context(AgentState.RUNNING):
        results = []
        # 4. 循环执行step()直到完成或达到最大步数
        while (self.current_step < self.max_steps and
               self.state != AgentState.FINISHED):
            self.current_step += 1
            step_result = await self.step()

            # 检查卡死状态
            if self.is_stuck():
                self.handle_stuck_state()

            results.append(f"Step {self.current_step}: {step_result}")

    # 5. 清理资源
    await SANDBOX_CLIENT.cleanup()
    return "\n".join(results)

@abstractmethod
async def step() -> str:
    """单步执行（抽象方法，子类实现）"""
    pass

def is_stuck() -> bool:
    """检测是否卡死（重复响应）"""
    # 检查最近N条assistant消息是否有重复内容
    recent_messages = self.memory.messages[-self.duplicate_threshold:]
    assistant_contents = [
        msg.content for msg in recent_messages
        if msg.role == Role.ASSISTANT and msg.content
    ]
    return len(assistant_contents) >= self.duplicate_threshold and \
           len(set(assistant_contents)) == 1
```

**状态管理**:
- 使用`@asynccontextmanager`装饰的`state_context()`方法确保状态转换安全
- 异常时自动转换到ERROR状态
- 支持状态回滚和恢复
- 状态转换日志记录

**内存管理**:
- `update_memory()`方法统一管理消息添加
- 支持不同角色消息（user、assistant、system、tool）
- `messages`属性提供便捷访问

### 2.2 ReActAgent - ReAct模式实现

**文件位置**: `app/agent/react.py`

**设计模式**: 模板方法模式

**职责**:
- 实现ReAct（Reasoning + Acting）模式
- 将执行分为思考（think）和行动（act）两个阶段
- 提供统一的执行框架

**类继承关系**:
```
BaseAgent
    └── ReActAgent
            └── ToolCallAgent
```

**执行流程**:
```python
async def step() -> str:
    """模板方法：定义think-act模式"""
    should_act = await self.think()  # 思考阶段（抽象方法）
    if not should_act:
        return "Thinking complete"
    return await self.act()  # 行动阶段（抽象方法）

@abstractmethod
async def think() -> bool:
    """思考阶段：分析当前状态，决定下一步行动"""
    pass

@abstractmethod
async def act() -> str:
    """行动阶段：执行具体操作"""
    pass
```

**扩展点**:
- `think()`: 子类实现思考逻辑，返回是否需要行动
- `act()`: 子类实现行动逻辑，返回行动结果

**设计优势**:
- 清晰的职责分离：思考与行动解耦
- 易于扩展：子类只需实现两个方法
- 统一的执行模式：所有ReAct代理遵循相同模式

### 2.3 ToolCallAgent - 工具调用代理

**文件位置**: `app/agent/toolcall.py`

**职责**:
- 集成LLM函数调用能力
- 管理工具集合
- 执行工具调用
- 处理工具结果
- 管理工具执行流程

**关键属性**:
```python
available_tools: ToolCollection      # 可用工具集合
tool_choices: ToolChoice            # 工具选择策略
special_tool_names: List[str]       # 特殊工具名称列表
tool_calls: List[ToolCall]          # 当前工具调用列表
max_observe: int = 10000            # 最大观察长度
_current_base64_image: Optional[str] # 当前图像数据
```

**关键设计**:

1. **工具选择策略**:
```python
tool_choices: TOOL_CHOICE_TYPE = ToolChoice.AUTO
# NONE: 不使用工具，LLM只能生成文本响应
# AUTO: 自动选择，LLM决定是否使用工具
# REQUIRED: 必须使用工具，LLM必须调用至少一个工具
```

2. **think()方法 - 思考阶段**:
```python
async def think() -> bool:
    """思考阶段：调用LLM并解析工具调用"""
    # 1. 添加next_step_prompt到消息
    if self.next_step_prompt:
        user_msg = Message.user_message(self.next_step_prompt)
        self.messages += [user_msg]

    try:
        # 2. 调用LLM.ask_tool()，传入工具列表
        response = await self.llm.ask_tool(
            messages=self.messages,
            system_msgs=[Message.system_message(self.system_prompt)],
            tools=self.available_tools.to_params(),  # 转换为LLM格式
            tool_choice=self.tool_choices,
        )

        # 3. 解析响应中的tool_calls和content
        self.tool_calls = response.tool_calls if response else []
        content = response.content if response else ""

        # 4. 创建assistant消息并添加到内存
        assistant_msg = Message.from_tool_calls(
            content=content,
            tool_calls=self.tool_calls
        )
        self.memory.add_message(assistant_msg)

        # 5. 返回是否有工具调用
        return bool(self.tool_calls)
    except TokenLimitExceeded:
        # Token超限处理
        self.state = AgentState.ERROR
        return False
```

3. **act()方法 - 行动阶段**:
```python
async def act() -> str:
    """行动阶段：执行工具调用"""
    # 1. 验证工具调用存在
    if self.tool_choices == ToolChoice.REQUIRED and not self.tool_calls:
        raise ValueError("Tool choice is REQUIRED but no tool calls found")

    if not self.tool_calls:
        return self.messages[-1].content or "No content"

    # 2. 遍历tool_calls并执行
    results = []
    for command in self.tool_calls:
        result = await self.execute_tool(command)

        # 3. 限制观察长度
        if self.max_observe and len(result) > self.max_observe:
            result = result[:self.max_observe] + "... (truncated)"

        # 4. 创建tool消息并添加到内存
        tool_msg = Message.tool_message(
            content=result,
            tool_call_id=command.id,
            name=command.function.name,
        )
        self.memory.add_message(tool_msg)
        results.append(result)

    return "\n\n".join(results)
```

4. **execute_tool()方法 - 工具执行**:
```python
async def execute_tool(self, command: ToolCall) -> str:
    """执行单个工具调用"""
    name = command.function.name

    # 1. 验证命令格式
    if not name or not command.function.arguments:
        return f"Error: Invalid tool call format"

    # 2. 查找工具
    if name not in self.available_tools.tool_map:
        return f"Error: Unknown tool '{name}'"

    try:
        # 3. 解析参数（JSON）
        args = json.loads(command.function.arguments or "{}")

        # 4. 执行工具
        result = await self.available_tools.execute(
            name=name,
            tool_input=args
        )

        # 5. 处理特殊工具
        await self._handle_special_tool(name=name, result=result)

        # 6. 处理图像结果
        if hasattr(result, 'base64_image') and result.base64_image:
            self._current_base64_image = result.base64_image

        # 7. 格式化观察字符串
        observation = f"Observed output of cmd `{name}` executed:\n{str(result)}"
        return observation
    except json.JSONDecodeError as e:
        return f"Error parsing arguments for {name}: {str(e)}"
    except Exception as e:
        return f"Error executing {name}: {str(e)}"
```

5. **特殊工具处理**:
```python
special_tool_names: List[str] = [Terminate().name]

async def _handle_special_tool(self, name: str, result: Any, **kwargs) -> None:
    """处理特殊工具（如终止执行）"""
    if self._is_special_tool(name):
        if self._should_finish_execution(name, result, **kwargs):
            self.state = AgentState.FINISHED

def _should_finish_execution(self, name: str, **kwargs) -> bool:
    """判断是否应该结束执行"""
    # 默认实现：Terminate工具总是结束执行
    return True

def _is_special_tool(self, name: str) -> bool:
    """检查是否是特殊工具"""
    return name in self.special_tool_names
```

6. **资源清理**:
```python
async def cleanup(self):
    """清理资源"""
    # 清理所有工具的资源
    for tool in self.available_tools.tools:
        if hasattr(tool, 'cleanup') and callable(tool.cleanup):
            try:
                if asyncio.iscoroutinefunction(tool.cleanup):
                    await tool.cleanup()
                else:
                    tool.cleanup()
            except Exception as e:
                logger.error(f"Error cleaning up tool {tool.name}: {e}")
```

### 2.4 Manus - 通用代理实现

**文件位置**: `app/agent/manus.py`

**职责**:
- 集成多种通用工具
- 支持MCP工具扩展
- 提供浏览器上下文辅助
- 管理MCP服务器连接生命周期

**关键属性**:
```python
name: str = "Manus"
description: str = "A versatile general-purpose agent..."
system_prompt: str = SYSTEM_PROMPT.format(directory=config.workspace_root)
next_step_prompt: str = NEXT_STEP_PROMPT
max_observe: int = 10000
max_steps: int = 20
mcp_clients: MCPClients                    # MCP客户端集合
available_tools: ToolCollection            # 工具集合
browser_context_helper: BrowserContextHelper # 浏览器上下文助手
connected_servers: Dict[str, str]          # 已连接服务器映射
_initialized: bool = False                 # 初始化标志
```

**工具集合**:
```python
available_tools = ToolCollection(
    PythonExecute(),      # Python代码执行（隔离进程）
    BrowserUseTool(),     # 浏览器自动化（browser_use库）
    StrReplaceEditor(),   # 文件编辑（查看、创建、替换、插入）
    AskHuman(),          # 人工交互（阻塞等待用户输入）
    Terminate(),         # 终止执行
)
```

**MCP集成流程**:
```python
@classmethod
async def create(cls, **kwargs) -> "Manus":
    """工厂方法：创建并初始化Manus实例"""
    instance = cls(**kwargs)
    await instance.initialize_mcp_servers()  # 初始化MCP连接
    instance._initialized = True
    return instance

async def initialize_mcp_servers(self) -> None:
    """初始化MCP服务器连接"""
    for server_id, server_config in config.mcp_config.servers.items():
        try:
            if server_config.type == "sse":
                # SSE连接：通过URL连接
                await self.connect_mcp_server(server_config.url, server_id)
            elif server_config.type == "stdio":
                # stdio连接：通过命令启动进程
                await self.connect_mcp_server(
                    server_config.command,
                    server_id,
                    use_stdio=True,
                    stdio_args=server_config.args,
                )
        except Exception as e:
            logger.error(f"Failed to connect to MCP server {server_id}: {e}")

async def connect_mcp_server(self, server_url: str, server_id: str = "",
                             use_stdio: bool = False, stdio_args: List[str] = None):
    """连接到MCP服务器并添加工具"""
    if use_stdio:
        await self.mcp_clients.connect_stdio(server_url, stdio_args or [], server_id)
    else:
        await self.mcp_clients.connect_sse(server_url, server_id)

    # 获取新工具并添加到集合
    new_tools = [tool for tool in self.mcp_clients.tools
                 if tool.server_id == server_id]
    self.available_tools.add_tools(*new_tools)
    self.connected_servers[server_id or server_url] = server_url
```

**浏览器上下文辅助**:
```python
async def think() -> bool:
    """思考阶段：动态调整提示词包含浏览器上下文"""
    # 确保MCP服务器已初始化
    if not self._initialized:
        await self.initialize_mcp_servers()
        self._initialized = True

    # 检查最近是否使用了浏览器工具
    original_prompt = self.next_step_prompt
    recent_messages = self.memory.messages[-3:] if self.memory.messages else []
    browser_in_use = any(
        tc.function.name == BrowserUseTool().name
        for msg in recent_messages
        if msg.tool_calls
        for tc in msg.tool_calls
    )

    # 如果使用了浏览器工具，动态调整提示词
    if browser_in_use:
        self.next_step_prompt = await self.browser_context_helper.format_next_step_prompt()

    result = await super().think()

    # 恢复原始提示词
    self.next_step_prompt = original_prompt
    return result
```

**资源清理**:
```python
async def cleanup(self):
    """清理资源"""
    # 清理浏览器
    if self.browser_context_helper:
        await self.browser_context_helper.cleanup_browser()

    # 断开MCP连接（仅在已初始化时）
    if self._initialized:
        await self.disconnect_mcp_server()
        self._initialized = False
```

### 2.5 BrowserAgent - 浏览器专用代理

**文件位置**: `app/agent/browser.py`

**职责**:
- 专门用于浏览器自动化任务
- 集成BrowserUseTool
- 管理浏览器状态和上下文

**关键特性**:
- 自动获取浏览器状态（URL、标题、标签页、滚动位置）
- 动态调整提示词包含浏览器上下文
- 自动添加浏览器截图到对话

**BrowserContextHelper设计**:
```python
class BrowserContextHelper:
    """浏览器上下文助手"""

    async def get_browser_state(self) -> Optional[dict]:
        """获取当前浏览器状态"""
        # 1. 查找浏览器工具（BrowserUseTool或SandboxBrowserTool）
        # 2. 调用get_current_state()获取状态
        # 3. 保存base64图像
        # 4. 返回状态字典

    async def format_next_step_prompt(self) -> str:
        """格式化包含浏览器状态的提示词"""
        browser_state = await self.get_browser_state()
        # 提取URL、标题、标签页、滚动信息
        # 如果有截图，添加到内存
        # 格式化提示词模板
        return NEXT_STEP_PROMPT.format(...)
```

### 2.6 MCPAgent - MCP专用代理

**文件位置**: `app/agent/mcp.py`

**职责**:
- 专门用于MCP服务器交互
- 动态刷新工具列表
- 处理工具变化通知

**关键特性**:
- 支持SSE和stdio两种连接方式
- 定期刷新工具列表（每N步）
- 检测工具添加、移除、变化
- 多媒体响应支持

**工具刷新机制**:
```python
async def _refresh_tools(self) -> Tuple[List[str], List[str]]:
    """刷新工具列表"""
    # 1. 从MCP服务器获取当前工具列表
    # 2. 比较与已存储的工具Schema
    # 3. 识别添加、移除、变化的工具
    # 4. 更新工具Schema
    # 5. 通知代理工具变化
    # 6. 返回(added_tools, removed_tools)
```

### 2.7 SandboxManus - 沙箱代理

**文件位置**: `app/agent/sandbox_agent.py`

**职责**:
- 基于Daytona沙箱的通用代理
- 集成沙箱工具（Browser、Files、Shell、Vision）
- 管理沙箱生命周期

**关键特性**:
- Daytona沙箱集成
- 沙箱工具集合（SandboxBrowserTool、SandboxFilesTool等）
- VNC和Website预览链接管理
- 沙箱创建和删除

**沙箱初始化流程**:
```python
async def initialize_sandbox_tools(self, password: str) -> None:
    """初始化沙箱工具"""
    # 1. 创建Daytona沙箱
    sandbox = create_sandbox(password=password)
    self.sandbox = sandbox

    # 2. 获取预览链接
    vnc_link = sandbox.get_preview_link(6080)
    website_link = sandbox.get_preview_link(8080)

    # 3. 创建沙箱工具实例
    sb_tools = [
        SandboxBrowserTool(sandbox),
        SandboxFilesTool(sandbox),
        SandboxShellTool(sandbox),
        SandboxVisionTool(sandbox),
    ]

    # 4. 添加到工具集合
    self.available_tools.add_tools(*sb_tools)
```

## 3. 工具系统设计

### 3.1 BaseTool - 工具基类

**文件位置**: `app/tool/base.py`

**接口定义**:
```python
class BaseTool(ABC, BaseModel):
    """工具基类"""
    name: str                    # 工具名称（唯一标识）
    description: str             # 工具描述（LLM可见）
    parameters: Optional[dict]   # 参数Schema（JSON Schema格式）

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """执行工具逻辑（抽象方法）"""
        pass

    def __call__(self, **kwargs) -> ToolResult:
        """使工具可调用"""
        return await self.execute(**kwargs)

    def to_param(self) -> Dict:
        """转换为LLM函数调用格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {},
            }
        }

    def success_response(self, output: str, **kwargs) -> ToolResult:
        """创建成功响应"""
        return ToolResult(output=output, **kwargs)

    def fail_response(self, error: str) -> ToolResult:
        """创建失败响应"""
        return ToolResult(error=error)
```

**工具结果封装**:
```python
class ToolResult(BaseModel):
    """工具执行结果"""
    output: Optional[str] = None         # 成功输出
    error: Optional[str] = None         # 错误信息
    base64_image: Optional[str] = None  # 图像数据（base64编码）
    system: Optional[str] = None        # 系统消息

    def __bool__(self) -> bool:
        """判断是否成功"""
        return self.error is None

    def __str__(self) -> str:
        """字符串表示"""
        return f"Error: {self.error}" if self.error else (self.output or "")

    def __add__(self, other: "ToolResult") -> "ToolResult":
        """合并两个结果"""
        return ToolResult(
            output=(self.output or "") + (other.output or ""),
            error=self.error or other.error,
            base64_image=self.base64_image or other.base64_image,
            system=self.system or other.system,
        )

    def replace(self, **kwargs) -> "ToolResult":
        """创建新结果，替换指定字段"""
        return ToolResult(
            output=kwargs.get("output", self.output),
            error=kwargs.get("error", self.error),
            base64_image=kwargs.get("base64_image", self.base64_image),
            system=kwargs.get("system", self.system),
        )
```

**工具失败类**:
```python
class ToolFailure(ToolResult):
    """工具执行失败"""
    def __init__(self, error: str):
        super().__init__(error=error)
```

### 3.2 ToolCollection - 工具集合

**文件位置**: `app/tool/tool_collection.py`

**职责**:
- 管理工具注册表
- 提供工具查找和执行接口
- 支持批量操作
- 转换为LLM格式

**实现**:
```python
class ToolCollection(BaseModel):
    """工具集合管理类"""
    tools: Tuple[BaseTool, ...] = Field(default_factory=tuple)
    tool_map: Dict[str, BaseTool] = Field(default_factory=dict)

    def __init__(self, *tools: BaseTool):
        """初始化工具集合"""
        self.tools = tools
        self.tool_map = {tool.name: tool for tool in tools}

    def __iter__(self):
        """支持迭代"""
        return iter(self.tools)

    def to_params(self) -> List[Dict]:
        """转换为LLM函数调用格式"""
        return [tool.to_param() for tool in self.tools]

    async def execute(self, *, name: str, tool_input: Dict) -> ToolResult:
        """执行工具"""
        tool = self.get_tool(name)
        if not tool:
            return ToolFailure(error=f"Tool {name} is invalid")
        try:
            result = await tool(**tool_input)
            return result
        except ToolError as e:
            return ToolFailure(error=str(e))
        except Exception as e:
            return ToolFailure(error=f"Unexpected error: {str(e)}")

    def get_tool(self, name: str) -> Optional[BaseTool]:
        """获取工具"""
        return self.tool_map.get(name)

    def add_tool(self, tool: BaseTool) -> None:
        """添加单个工具"""
        if tool.name in self.tool_map:
            logger.warning(f"Tool {tool.name} already exists, overwriting")
        # 更新工具列表和映射
        self.tools = (*self.tools, tool)
        self.tool_map[tool.name] = tool

    def add_tools(self, *tools: BaseTool) -> None:
        """批量添加工具"""
        for tool in tools:
            self.add_tool(tool)

    async def execute_all(self, tool_inputs: Dict[str, Dict]) -> Dict[str, ToolResult]:
        """批量执行工具"""
        results = {}
        for name, inputs in tool_inputs.items():
            results[name] = await self.execute(name=name, tool_input=inputs)
        return results
```

### 3.3 工具示例

#### 3.3.1 PythonExecute - Python代码执行

**文件位置**: `app/tool/python_execute.py`

**设计要点**:
1. **进程隔离**: 使用multiprocessing在独立进程中执行
2. **超时控制**: 支持超时设置，防止无限执行
3. **输出捕获**: 捕获stdout和stderr
4. **错误处理**: 捕获执行错误并返回

**实现**:
```python
class PythonExecute(BaseTool):
    name = "python_execute"
    description = "Execute Python code in an isolated process"
    parameters = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute"}
        },
        "required": ["code"]
    }

    @staticmethod
    def _run_code(code: str, result_dict: dict):
        """在独立进程中运行代码"""
        import sys
        from io import StringIO

        # 重定向stdout
        old_stdout = sys.stdout
        sys.stdout = captured_output = StringIO()

        try:
            exec(code, {"__builtins__": __builtins__})
            result_dict["output"] = captured_output.getvalue()
            result_dict["success"] = True
        except Exception as e:
            result_dict["error"] = str(e)
            result_dict["success"] = False
        finally:
            sys.stdout = old_stdout

    async def execute(self, code: str, **kwargs) -> ToolResult:
        """执行Python代码"""
        from multiprocessing import Manager, Process

        # 使用Manager共享结果
        manager = Manager()
        result_dict = manager.dict()

        # 创建进程
        process = Process(target=self._run_code, args=(code, result_dict))
        process.start()
        process.join(timeout=30)  # 30秒超时

        if process.is_alive():
            process.terminate()
            process.join()
            return self.fail_response("Code execution timed out")

        if result_dict.get("success"):
            return self.success_response(result_dict.get("output", ""))
        else:
            return self.fail_response(result_dict.get("error", "Unknown error"))
```

#### 3.3.2 BrowserUseTool - 浏览器自动化

**文件位置**: `app/tool/browser_use_tool.py`

**设计要点**:
1. **浏览器管理**: 使用browser_use库管理浏览器实例
2. **状态维护**: 保持浏览器会话状态
3. **并发控制**: 使用锁保护浏览器操作
4. **多操作支持**: 导航、点击、输入、滚动、提取等

**关键方法**:
```python
async def _ensure_browser_initialized(self) -> BrowserContext:
    """确保浏览器已初始化"""
    if self.browser is None:
        # 创建浏览器实例（支持代理配置）
        browser_config = BrowserConfig(**config_kwargs)
        self.browser = BrowserUseBrowser(browser_config)

    if self.context is None:
        # 创建浏览器上下文
        context_config = BrowserContextConfig()
        self.context = await self.browser.new_context(context_config)
        self.dom_service = DomService(await self.context.get_current_page())

    return self.context

async def execute(self, action: str, **kwargs) -> ToolResult:
    """执行浏览器操作"""
    async with self.lock:  # 并发控制
        context = await self._ensure_browser_initialized()

        # 根据action执行不同操作
        if action == "go_to_url":
            page = await context.get_current_page()
            await page.goto(kwargs["url"])
            return ToolResult(output=f"Navigated to {kwargs['url']}")
        elif action == "click_element":
            element = await context.get_dom_element_by_index(kwargs["index"])
            await context._click_element_node(element)
            return ToolResult(output=f"Clicked element at index {kwargs['index']}")
        # ... 其他操作
```

#### 3.3.3 StrReplaceEditor - 文件编辑器

**文件位置**: `app/tool/str_replace_editor.py`

**设计要点**:
1. **文件操作**: 支持查看、创建、替换、插入
2. **路径验证**: 防止路径遍历攻击
3. **历史管理**: 支持撤销操作
4. **沙箱支持**: 支持本地和沙箱环境

**关键方法**:
```python
def validate_path(self, path: str, command: str) -> None:
    """验证路径安全性"""
    # 1. 检查绝对路径
    if not os.path.isabs(path):
        raise ToolError("Path must be absolute")

    # 2. 检查路径遍历
    if ".." in path.split("/"):
        raise ToolError("Path contains potentially unsafe patterns")

    # 3. 检查文件存在性（非create命令）
    if command != "create" and not os.path.exists(path):
        raise ToolError(f"File not found: {path}")

async def execute(self, command: str, **kwargs) -> ToolResult:
    """执行编辑命令"""
    path = kwargs.get("file_path")
    self.validate_path(path, command)

    operator = self._get_operator()  # 获取文件操作器（本地或沙箱）

    if command == "view":
        return await self.view(path, **kwargs)
    elif command == "create":
        return await self.create(path, **kwargs)
    elif command == "str_replace":
        return await self.str_replace(path, **kwargs)
    # ... 其他命令
```

#### 3.3.4 SandboxToolsBase - 沙箱工具基类

**文件位置**: `app/daytona/tool_base.py`

**设计要点**:
1. **沙箱生命周期**: 自动管理沙箱创建和启动
2. **路径清理**: 规范化路径为相对路径
3. **状态检查**: 检查沙箱状态并自动恢复

**关键方法**:
```python
async def _ensure_sandbox(self) -> Sandbox:
    """确保沙箱存在且运行"""
    if self._sandbox is None:
        # 创建新沙箱
        self._sandbox = create_sandbox(password=config.daytona.VNC_password)
    else:
        # 检查沙箱状态
        if self._sandbox.state in [SandboxState.ARCHIVED, SandboxState.STOPPED]:
            # 启动沙箱
            daytona.start(self._sandbox)
            start_supervisord_session(self._sandbox)
    return self._sandbox

def clean_path(self, path: str) -> str:
    """清理路径为相对于/workspace的路径"""
    return clean_path(path, self.workspace_path)
```

## 4. LLM客户端设计

### 4.1 LLM类设计

**文件位置**: `app/llm.py`

**职责**:
- 封装不同LLM提供商的API
- 提供统一的调用接口
- Token计数和管理
- 支持流式和非流式响应
- 多模态支持（图像输入）

**关键属性**:
```python
model: str                           # 模型名称
api_type: str                       # API类型（openai/azure/aws）
client: Union[AsyncOpenAI, AsyncAzureOpenAI, BedrockClient]  # 客户端实例
tokenizer: Optional[Any]            # Tokenizer实例
total_input_tokens: int = 0         # 总输入Token数
total_completion_tokens: int = 0    # 总输出Token数
max_input_tokens: Optional[int]     # 最大输入Token限制
```

**关键方法**:

1. **ask() - 普通对话**:
```python
async def ask(
    messages: List[Union[dict, Message]],
    system_msgs: Optional[List[Message]] = None,
    stream: bool = True,
    temperature: Optional[float] = None,
    **kwargs,
) -> str:
    """普通对话接口"""
    # 1. 格式化消息（支持图像）
    formatted_messages = self.format_messages(messages, supports_images=True)
    if system_msgs:
        formatted_messages = self.format_messages(system_msgs) + formatted_messages

    # 2. 计算Token数量
    input_tokens = self.count_message_tokens(formatted_messages)

    # 3. 检查Token限制
    if not self.check_token_limit(input_tokens):
        raise TokenLimitExceeded(...)

    # 4. 调用API（流式或非流式）
    if stream:
        response_text = ""
        async for chunk in self.client.chat.completions.create(
            model=self.model,
            messages=formatted_messages,
            stream=True,
            temperature=temperature or self.temperature,
            **kwargs
        ):
            if chunk.choices[0].delta.content:
                response_text += chunk.choices[0].delta.content
        # 估算Token（流式响应无法获取准确值）
        self.update_token_count(input_tokens, estimated_completion_tokens)
    else:
        response = await self.client.chat.completions.create(...)
        response_text = response.choices[0].message.content
        self.update_token_count(
            response.usage.prompt_tokens,
            response.usage.completion_tokens
        )

    # 5. 返回响应
    return response_text
```

2. **ask_tool() - 工具调用**:
```python
async def ask_tool(
    messages: List[Union[dict, Message]],
    tools: Optional[List[dict]] = None,
    tool_choice: TOOL_CHOICE_TYPE = ToolChoice.AUTO,
    **kwargs,
) -> ChatCompletionMessage:
    """工具调用接口（必须非流式）"""
    # 1. 格式化消息
    formatted_messages = self.format_messages(messages, supports_images=True)

    # 2. 计算Token（包括工具描述）
    input_tokens = self.count_message_tokens(formatted_messages)
    if tools:
        for tool in tools:
            input_tokens += self.count_tokens(str(tool))

    # 3. 检查Token限制
    if not self.check_token_limit(input_tokens):
        raise TokenLimitExceeded(...)

    # 4. 调用API（必须非流式）
    params = {
        "model": self.model,
        "messages": formatted_messages,
        "tools": tools,
        "tool_choice": tool_choice.value if isinstance(tool_choice, ToolChoice) else tool_choice,
        "stream": False,  # 工具调用必须非流式
        **kwargs
    }

    response = await self.client.chat.completions.create(**params)

    # 5. 更新Token计数
    self.update_token_count(
        response.usage.prompt_tokens,
        response.usage.completion_tokens
    )

    # 6. 返回消息对象（包含tool_calls）
    return response.choices[0].message
```

3. **format_messages() - 消息格式化**:
```python
def format_messages(
    self,
    messages: List[Union[dict, Message]],
    supports_images: bool = False
) -> List[dict]:
    """格式化消息为API格式"""
    formatted = []
    for msg in messages:
        if isinstance(msg, Message):
            msg_dict = msg.to_dict()
        else:
            msg_dict = msg

        # 处理图像内容
        if supports_images and msg_dict.get("base64_image"):
            content = [
                {"type": "text", "text": msg_dict.get("content", "")},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{msg_dict['base64_image']}"
                    }
                }
            ]
            msg_dict["content"] = content

        formatted.append(msg_dict)
    return formatted
```

4. **Token管理 - TokenCounter类**:
```python
class TokenCounter:
    """Token计数器"""

    def __init__(self, model: str):
        """初始化计数器"""
        self.model = model
        # 根据模型选择tokenizer
        if "gpt-4" in model or "gpt-3.5" in model:
            self.tokenizer = tiktoken.encoding_for_model(model)
        else:
            self.tokenizer = None

    def count_text(self, text: str) -> int:
        """计算文本Token数"""
        if self.tokenizer:
            return len(self.tokenizer.encode(text))
        # 估算：1 token ≈ 4 characters
        return len(text) // 4

    def count_image(self, image_item: dict) -> int:
        """计算图像Token数"""
        detail = image_item.get("detail", "auto")
        if detail == "low":
            return 85  # 低细节固定85 tokens

        # 高细节：基于尺寸计算
        # 每个512x512 tile = 170 tokens
        # base tokens = 85
        width = image_item.get("width", 0)
        height = image_item.get("height", 0)
        tiles = ((width + 511) // 512) * ((height + 511) // 512)
        return 85 + 170 * tiles

    def count_message_tokens(self, messages: List[dict]) -> int:
        """计算消息列表的总Token数"""
        tokens = 3  # 每条消息的格式token
        for msg in messages:
            tokens += 3  # 角色token
            content = msg.get("content", "")
            if isinstance(content, list):
                # 多模态内容
                for item in content:
                    if item.get("type") == "text":
                        tokens += self.count_text(item.get("text", ""))
                    elif item.get("type") == "image_url":
                        tokens += self.count_image(item.get("image_url", {}))
            else:
                tokens += self.count_text(str(content))

            # 工具调用token
            if msg.get("tool_calls"):
                tokens += len(msg["tool_calls"]) * 5

        return tokens
```

### 4.2 多提供商支持

**设计模式**: 策略模式

**实现**:
```python
def __init__(self, model: str, api_type: str = "openai", **kwargs):
    """初始化LLM客户端"""
    self.model = model
    self.api_type = api_type

    # 根据API类型选择客户端
    if api_type == "azure":
        self.client = AsyncAzureOpenAI(
            api_key=kwargs.get("api_key"),
            api_version=kwargs.get("api_version"),
            azure_endpoint=kwargs.get("azure_endpoint"),
        )
    elif api_type == "aws":
        # AWS Bedrock客户端
        self.client = BedrockClient(
            model_id=model,
            region=kwargs.get("region"),
            credentials=kwargs.get("credentials"),
        )
    else:
        # 默认OpenAI
        self.client = AsyncOpenAI(
            api_key=kwargs.get("api_key"),
            base_url=kwargs.get("base_url"),
        )

    # 初始化Token计数器
    self.token_counter = TokenCounter(model)
```

### 4.3 Token限制检查

```python
def check_token_limit(self, input_tokens: int) -> bool:
    """检查Token是否超过限制"""
    if self.max_input_tokens is None:
        return True
    return input_tokens <= self.max_input_tokens

def get_limit_error_message(self, input_tokens: int) -> str:
    """获取Token超限错误消息"""
    return f"Token limit exceeded: {input_tokens} > {self.max_input_tokens}"
```

### 4.4 重试机制

```python
from tenacity import retry, stop_after_attempt, wait_random_exponential, retry_if_exception_type

@retry(
    wait=wait_random_exponential(min=1, max=60),  # 指数退避：1-60秒
    stop=stop_after_attempt(6),                   # 最多重试6次
    retry=retry_if_exception_type((OpenAIError, Exception)),  # 重试条件
    reraise=True,  # 重新抛出异常
)
async def ask(self, ...):
    """带重试的ask方法"""
    # API调用逻辑
```

## 5. 配置管理设计

### 5.1 Config单例

**文件位置**: `app/config.py`

**设计模式**: 单例模式（双重检查锁定）

**实现**:
```python
class Config:
    """配置管理单例类"""
    _instance = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls):
        """单例实现：双重检查锁定"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化配置（仅执行一次）"""
        if not Config._initialized:
            self._load_initial_config()
            Config._initialized = True
```

**配置加载流程**:
```python
def _load_initial_config(self):
    """加载初始配置"""
    # 1. 加载TOML文件
    config_path = PROJECT_ROOT / "config" / "config.toml"
    raw_config = self._load_config(config_path)

    # 2. 解析LLM配置（支持多个配置）
    base_llm = raw_config.get("llm", {})
    llm_overrides = {}
    for key, value in raw_config.items():
        if key.startswith("llm_"):
            llm_name = key[4:]  # 移除"llm_"前缀
            llm_overrides[llm_name] = value

    # 构建默认LLM设置
    default_settings = LLMSettings(**base_llm)

    # 构建所有LLM配置
    llm_configs = {"default": default_settings}
    for name, override in llm_overrides.items():
        llm_configs[name] = LLMSettings(**{**base_llm, **override})

    # 3. 解析浏览器配置
    browser_config = raw_config.get("browser", {})
    browser_settings = None
    if browser_config:
        proxy_settings = None
        if browser_config.get("proxy"):
            proxy_settings = ProxySettings(**browser_config["proxy"])
        browser_settings = BrowserSettings(
            headless=browser_config.get("headless", False),
            proxy=proxy_settings,
            **{k: v for k, v in browser_config.items() if k != "proxy"}
        )

    # 4. 解析沙箱配置
    sandbox_config = raw_config.get("sandbox", {})
    sandbox_settings = SandboxSettings(**sandbox_config) if sandbox_config else SandboxSettings()

    # 5. 解析搜索配置
    search_config = raw_config.get("search", {})
    search_settings = SearchSettings(**search_config) if search_config else SearchSettings()

    # 6. 解析MCP配置
    mcp_config_path = PROJECT_ROOT / "config" / "mcp.json"
    mcp_settings = self._load_mcp_config(mcp_config_path) if mcp_config_path.exists() else MCPSettings()

    # 7. 解析其他配置...
    runflow_settings = RunflowSettings(**raw_config.get("runflow", {}))
    daytona_settings = DaytonaSettings(**raw_config.get("daytona", {}))

    # 8. 创建AppConfig对象
    self._config = AppConfig(
        llm=llm_configs,
        browser_config=browser_settings,
        sandbox=sandbox_settings,
        search_config=search_settings,
        mcp_config=mcp_settings,
        run_flow_config=runflow_settings,
        daytona=daytona_settings,
    )
```

**配置访问属性**:
```python
@property
def llm_config(self) -> Dict[str, LLMSettings]:
    """获取LLM配置"""
    return self._config.llm

@property
def browser_config(self) -> Optional[BrowserSettings]:
    """获取浏览器配置"""
    return self._config.browser_config

@property
def sandbox_config(self) -> SandboxSettings:
    """获取沙箱配置"""
    return self._config.sandbox

@property
def mcp_config(self) -> MCPSettings:
    """获取MCP配置"""
    return self._config.mcp_config

@property
def workspace_root(self) -> str:
    """获取工作空间根目录"""
    return WORKSPACE_ROOT
```

### 5.2 配置层次结构

```
AppConfig (app/config.py)
├── llm: Dict[str, LLMSettings]
│   ├── "default": LLMSettings
│   │   ├── model: str
│   │   ├── api_type: str (openai/azure/aws)
│   │   ├── api_key: Optional[str]
│   │   ├── temperature: float
│   │   ├── max_tokens: Optional[int]
│   │   └── ... (其他LLM参数)
│   └── "vision": LLMSettings (覆盖default)
│
├── browser_config: Optional[BrowserSettings]
│   ├── headless: bool
│   ├── proxy: Optional[ProxySettings]
│   ├── disable_security: bool
│   └── ... (其他浏览器参数)
│
├── sandbox: SandboxSettings
│   ├── use_sandbox: bool
│   ├── image: str (Docker镜像)
│   ├── memory_limit: str
│   ├── cpu_limit: float
│   ├── timeout: int
│   └── work_dir: str
│
├── search_config: SearchSettings
│   ├── preferred_engine: str
│   ├── fallback_engines: List[str]
│   ├── lang: str
│   ├── country: str
│   └── retry_config: RetryConfig
│
├── mcp_config: MCPSettings
│   └── servers: Dict[str, MCPServerConfig]
│       └── server_id: MCPServerConfig
│           ├── type: str (sse/stdio)
│           ├── url: Optional[str]
│           ├── command: Optional[str]
│           └── args: Optional[List[str]]
│
├── run_flow_config: RunflowSettings
│   └── ... (流程配置)
│
└── daytona: DaytonaSettings
    ├── daytona_api_key: str
    ├── daytona_server_url: str
    ├── daytona_target: str
    └── VNC_password: str
```

### 5.3 配置验证

**Pydantic模型验证**:
- 所有配置类继承自`BaseModel`
- 自动类型验证和转换
- 默认值处理
- 可选字段支持

**配置示例**:
```toml
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
username = "user"
password = "pass"

[sandbox]
use_sandbox = true
image = "python:3.11"
memory_limit = "2g"
cpu_limit = 1.0
timeout = 60
work_dir = "/workspace"
```

## 6. 内存管理设计

### 6.1 Memory类

**文件位置**: `app/schema.py`

**职责**:
- 存储对话历史
- 管理消息数量限制
- 提供消息查询接口
- 支持消息列表转换

**实现**:
```python
class Memory(BaseModel):
    """对话内存管理类"""
    messages: List[Message] = Field(default_factory=list)
    max_messages: int = Field(default=100)

    def add_message(self, message: Message) -> None:
        """添加消息到内存"""
        self.messages.append(message)
        # 如果超过限制，保留最近的N条
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]

    def add_messages(self, messages: List[Message]) -> None:
        """批量添加消息"""
        for msg in messages:
            self.add_message(msg)

    def clear(self) -> None:
        """清空内存"""
        self.messages.clear()

    def get_recent_messages(self, n: int = 10) -> List[Message]:
        """获取最近N条消息"""
        return self.messages[-n:] if len(self.messages) > n else self.messages

    def to_dict_list(self) -> List[dict]:
        """转换为字典列表"""
        return [msg.to_dict() for msg in self.messages]
```

### 6.2 Message类

**文件位置**: `app/schema.py`

**消息类型**:
- `SYSTEM`: 系统消息（Role.SYSTEM）
- `USER`: 用户消息（Role.USER）
- `ASSISTANT`: 助手消息（Role.ASSISTANT）
- `TOOL`: 工具消息（Role.TOOL）

**关键属性**:
```python
class Message(BaseModel):
    """消息模型"""
    role: Role                                    # 消息角色
    content: Optional[str] = None                 # 文本内容
    tool_calls: Optional[List[ToolCall]] = None  # 工具调用列表（assistant消息）
    name: Optional[str] = None                   # 工具名称（tool消息）
    tool_call_id: Optional[str] = None           # 工具调用ID（tool消息）
    base64_image: Optional[str] = None          # Base64编码的图像（user消息）
```

**类方法（便捷创建）**:
```python
@classmethod
def user_message(cls, content: str, base64_image: Optional[str] = None) -> "Message":
    """创建用户消息"""
    return cls(role=Role.USER, content=content, base64_image=base64_image)

@classmethod
def system_message(cls, content: str) -> "Message":
    """创建系统消息"""
    return cls(role=Role.SYSTEM, content=content)

@classmethod
def assistant_message(cls, content: str = "", tool_calls: Optional[List[ToolCall]] = None) -> "Message":
    """创建助手消息"""
    return cls(role=Role.ASSISTANT, content=content, tool_calls=tool_calls)

@classmethod
def tool_message(cls, content: str, tool_call_id: str, name: str) -> "Message":
    """创建工具消息"""
    return cls(role=Role.TOOL, content=content, tool_call_id=tool_call_id, name=name)

@classmethod
def from_tool_calls(cls, content: str = "", tool_calls: Optional[List[ToolCall]] = None) -> "Message":
    """从工具调用创建助手消息"""
    return cls.assistant_message(content=content, tool_calls=tool_calls)
```

**特殊操作**:
```python
def __add__(self, other: Union["Message", List["Message"]]) -> List["Message"]:
    """支持消息列表拼接"""
    if isinstance(other, Message):
        return [self, other]
    return [self] + other

def __radd__(self, other: List["Message"]) -> List["Message"]:
    """支持列表+消息拼接"""
    return other + [self]

def to_dict(self) -> dict:
    """转换为字典"""
    result = {"role": self.role.value}
    if self.content:
        result["content"] = self.content
    if self.tool_calls:
        result["tool_calls"] = [tc.model_dump() for tc in self.tool_calls]
    if self.name:
        result["name"] = self.name
    if self.tool_call_id:
        result["tool_call_id"] = self.tool_call_id
    return result
```

### 6.3 ToolCall和Function类

**文件位置**: `app/schema.py`

**ToolCall模型**:
```python
class ToolCall(BaseModel):
    """工具调用模型"""
    id: str                    # 工具调用ID
    type: str = "function"     # 类型（固定为"function"）
    function: Function        # 函数信息

class Function(BaseModel):
    """函数信息模型"""
    name: str                  # 函数名称（工具名称）
    arguments: str             # 参数字符串（JSON格式）
```

## 7. 流程管理设计

### 7.1 BaseFlow

**文件位置**: `app/flow/base.py`

**职责**:
- 管理多个代理
- 定义流程执行接口
- 提供代理访问接口

**设计**:
```python
class BaseFlow(BaseModel, ABC):
    """流程基类"""
    agents: Dict[str, BaseAgent] = Field(default_factory=dict)
    tools: Optional[List[BaseTool]] = Field(default=None)
    primary_agent_key: Optional[str] = None

    def __init__(self, agents: Union[BaseAgent, List[BaseAgent], Dict[str, BaseAgent]],
                 primary_agent_key: Optional[str] = None, **kwargs):
        """初始化流程"""
        # 处理不同类型的agents输入
        if isinstance(agents, BaseAgent):
            agents_dict = {agents.name: agents}
        elif isinstance(agents, list):
            agents_dict = {agent.name: agent for agent in agents}
        else:
            agents_dict = agents

        self.agents = agents_dict

        # 设置主代理
        if primary_agent_key:
            self.primary_agent_key = primary_agent_key
        elif self.agents:
            self.primary_agent_key = list(self.agents.keys())[0]

        super().__init__(**kwargs)

    @property
    def primary_agent(self) -> Optional[BaseAgent]:
        """获取主代理"""
        return self.agents.get(self.primary_agent_key) if self.primary_agent_key else None

    def get_agent(self, key: str) -> Optional[BaseAgent]:
        """获取指定代理"""
        return self.agents.get(key)

    def add_agent(self, agent: BaseAgent) -> None:
        """添加代理"""
        self.agents[agent.name] = agent

    @abstractmethod
    async def execute(self, input_text: str) -> str:
        """执行流程（抽象方法）"""
        pass
```

### 7.2 PlanningFlow

**文件位置**: `app/flow/planning.py`

**设计模式**: 规划-执行模式

**关键属性**:
```python
llm: LLM                                    # LLM客户端
planning_tool: PlanningTool                 # 规划工具
executor_keys: List[str]                    # 执行代理键列表
active_plan_id: Optional[str] = None        # 当前活动计划ID
current_step_index: int = 0                 # 当前步骤索引
```

**执行流程**:
```python
async def execute(self, input_text: str) -> str:
    """执行规划流程"""
    # 1. 检查主代理
    if not self.primary_agent:
        raise ValueError("Primary agent is required")

    # 2. 创建初始计划
    if input_text:
        await self._create_initial_plan(input_text)

    # 3. 循环执行计划步骤
    while True:
        try:
            # 3.1 获取当前步骤信息
            step_index, step_info = await self._get_current_step_info()
            if step_index is None:
                break  # 没有更多步骤

            self.current_step_index = step_index

            # 3.2 选择执行代理
            executor = self.get_executor(step_info.get("type"))

            # 3.3 执行步骤
            await self._execute_step(executor, step_info)

            # 3.4 检查代理是否完成
            if executor.state == AgentState.FINISHED:
                break

            # 3.5 标记步骤完成
            await self._mark_step_completed()

        except Exception as e:
            logger.error(f"Error executing step: {e}")
            break

    # 4. 完成计划
    return await self._finalize_plan()
```

**创建初始计划**:
```python
async def _create_initial_plan(self, input_text: str) -> None:
    """创建初始计划"""
    # 1. 构建规划提示词（包含可用代理描述）
    agent_descriptions = "\n".join([
        f"- {name}: {agent.description}"
        for name, agent in self.agents.items()
    ])

    system_msg = Message.system_message(
        f"You are a planning assistant. Available agents:\n{agent_descriptions}"
    )
    user_msg = Message.user_message(input_text)

    # 2. 调用LLM创建计划
    try:
        response = await self.llm.ask_tool(
            messages=[system_msg, user_msg],
            tools=[self.planning_tool.to_param()],
            tool_choice=ToolChoice.REQUIRED,
        )

        # 3. 执行规划工具的create命令
        if response.tool_calls:
            tool_call = response.tool_calls[0]
            args = json.loads(tool_call.function.arguments)
            result = await self.planning_tool.execute("create", **args)
            self.active_plan_id = args.get("plan_id")
    except Exception as e:
        logger.error(f"Failed to create plan: {e}")
        # 创建默认计划作为后备
        await self._create_default_plan(input_text)
```

**获取当前步骤**:
```python
async def _get_current_step_info(self) -> Tuple[Optional[int], Optional[dict]]:
    """获取当前步骤信息"""
    # 1. 从规划工具获取计划数据
    plan_data = self.planning_tool.plans.get(self.active_plan_id)
    if not plan_data:
        return None, None

    # 2. 查找第一个未完成的步骤
    steps = plan_data.get("steps", [])
    step_statuses = plan_data.get("step_statuses", [])

    for i, status in enumerate(step_statuses):
        if status != "completed":
            # 3. 提取步骤类型（如[CODE], [BROWSER]）
            step_text = steps[i] if i < len(steps) else ""
            step_type = self._extract_step_type(step_text)

            # 4. 标记步骤为进行中
            try:
                await self.planning_tool.execute(
                    "update_status",
                    plan_id=self.active_plan_id,
                    step_index=i,
                    status="in_progress",
                )
            except Exception:
                # 直接更新状态（后备方案）
                step_statuses[i] = "in_progress"

            return i, {"text": step_text, "type": step_type}

    return None, None
```

**执行步骤**:
```python
async def _execute_step(self, executor: BaseAgent, step_info: dict) -> None:
    """执行计划步骤"""
    # 1. 构建步骤提示词
    plan_text = await self._get_plan_text()
    step_prompt = f"""
Current plan status:
{plan_text}

Current task:
{step_info['text']}

Please execute this step.
"""

    # 2. 执行代理
    try:
        await executor.run(step_prompt)
    except Exception as e:
        logger.error(f"Error executing step: {e}")
        raise
```

**计划数据结构**:
```python
plan = {
    "plan_id": "plan_1234567890",           # 计划ID
    "title": "任务标题",                     # 计划标题
    "steps": ["步骤1", "步骤2", "步骤3"],    # 步骤列表
    "step_statuses": [                     # 步骤状态列表
        "completed",                        # 已完成
        "in_progress",                      # 进行中
        "not_started"                      # 未开始
    ],
    "step_notes": ["", "执行中...", ""]     # 步骤备注
}
```

**步骤状态枚举**:
```python
class PlanStepStatus(str, Enum):
    """计划步骤状态"""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
```

### 7.3 FlowFactory

**文件位置**: `app/flow/flow_factory.py`

**职责**:
- 创建不同类型的流程实例
- 管理流程类型注册

**实现**:
```python
class FlowType(str, Enum):
    """流程类型枚举"""
    PLANNING = "planning"

class FlowFactory:
    """流程工厂"""

    @staticmethod
    def create_flow(
        flow_type: FlowType,
        agents: Union[BaseAgent, List[BaseAgent], Dict[str, BaseAgent]],
        **kwargs
    ) -> BaseFlow:
        """创建流程实例"""
        if flow_type == FlowType.PLANNING:
            from app.flow.planning import PlanningFlow
            return PlanningFlow(agents=agents, **kwargs)
        else:
            raise ValueError(f"Unknown flow type: {flow_type}")
```

## 8. 错误处理设计

### 8.1 异常层次

**文件位置**: `app/exceptions.py`

```
Exception
├── OpenManusError (基类)
│   └── TokenLimitExceeded (Token超限错误)
└── ToolError (工具错误)
```

**异常定义**:
```python
class OpenManusError(Exception):
    """OpenManus基础异常类"""
    pass

class TokenLimitExceeded(OpenManusError):
    """Token限制超出异常"""
    def __init__(self, message: str, input_tokens: int, max_tokens: int):
        self.input_tokens = input_tokens
        self.max_tokens = max_tokens
        super().__init__(message)

class ToolError(Exception):
    """工具执行错误"""
    def __init__(self, message: str, tool_name: Optional[str] = None):
        self.tool_name = tool_name
        super().__init__(message)
```

**沙箱异常** (`app/sandbox/core/exceptions.py`):
```python
class SandboxError(Exception):
    """沙箱基础异常"""
    pass

class SandboxTimeoutError(SandboxError):
    """沙箱超时错误"""
    pass

class SandboxResourceError(SandboxError):
    """沙箱资源错误"""
    pass
```

### 8.2 错误处理策略

1. **Token限制错误**:
   - 不重试，直接抛出`TokenLimitExceeded`
   - 设置代理状态为ERROR
   - 记录详细错误信息（输入Token数、最大Token数）

2. **工具执行错误**:
   - 返回`ToolFailure`，不中断执行流程
   - 记录错误日志
   - 继续执行下一个工具调用

3. **网络错误**:
   - 使用tenacity重试（指数退避）
   - 最多重试6次
   - 重试间隔：1-60秒随机指数增长

4. **验证错误**:
   - 记录日志
   - 抛出异常，中断执行
   - 提供清晰的错误消息

5. **沙箱错误**:
   - 捕获`SandboxTimeoutError`，返回超时错误
   - 捕获`SandboxResourceError`，记录资源错误
   - 确保资源清理

### 8.3 重试机制

**LLM调用重试**:
```python
from tenacity import (
    retry,
    stop_after_attempt,
    wait_random_exponential,
    retry_if_exception_type,
)

@retry(
    wait=wait_random_exponential(min=1, max=60),  # 指数退避：1-60秒
    stop=stop_after_attempt(6),                      # 最多重试6次
    retry=retry_if_exception_type((OpenAIError, Exception)),  # 重试条件
    reraise=True,  # 重新抛出最后一个异常
)
async def ask(self, messages, **kwargs) -> str:
    """带重试的ask方法"""
    try:
        # API调用逻辑
        response = await self.client.chat.completions.create(...)
        return response.choices[0].message.content
    except TokenLimitExceeded:
        # Token超限不重试
        raise
    except OpenAIError as e:
        # 其他OpenAI错误重试
        logger.warning(f"OpenAI API error: {e}, retrying...")
        raise
```

**工具执行错误处理**:
```python
async def execute_tool(self, command: ToolCall) -> str:
    """执行工具，捕获所有错误"""
    try:
        # 执行工具
        result = await self.available_tools.execute(...)
        return str(result)
    except json.JSONDecodeError as e:
        # JSON解析错误：返回错误消息
        return f"Error parsing arguments: {str(e)}"
    except ToolError as e:
        # 工具错误：返回错误消息
        return f"Tool error: {str(e)}"
    except Exception as e:
        # 其他异常：记录日志并返回错误消息
        logger.error(f"Unexpected error executing tool: {e}")
        return f"Unexpected error: {str(e)}"
```

### 8.4 错误恢复机制

**状态恢复**:
- 使用`state_context`确保状态一致性
- 异常时自动转换到ERROR状态
- 支持状态回滚

**资源清理**:
- `finally`块确保资源清理
- `cleanup()`方法统一清理接口
- 上下文管理器自动清理

**优雅降级**:
- 工具执行失败不影响其他工具
- 计划步骤失败可跳过
- 提供默认后备方案

## 9. 扩展性设计

### 9.1 添加新工具

**步骤**:
1. 在`app/tool/`目录创建新文件
2. 继承`BaseTool`
3. 实现`execute()`方法
4. 定义`name`、`description`、`parameters`
5. 在`app/tool/__init__.py`导出
6. 在代理的`available_tools`中注册

**示例**:
```python
# app/tool/my_tool.py
from app.tool.base import BaseTool, ToolResult

class MyTool(BaseTool):
    """我的工具"""
    name = "my_tool"
    description = "我的工具描述，LLM可以看到这个描述"
    parameters = {
        "type": "object",
        "properties": {
            "param1": {
                "type": "string",
                "description": "参数1的描述"
            },
            "param2": {
                "type": "integer",
                "description": "参数2的描述",
                "default": 0
            }
        },
        "required": ["param1"]
    }

    async def execute(self, param1: str, param2: int = 0, **kwargs) -> ToolResult:
        """执行工具逻辑"""
        try:
            # 实现工具逻辑
            result = f"Processed {param1} with {param2}"
            return self.success_response(result)
        except Exception as e:
            return self.fail_response(f"Error: {str(e)}")
```

**在代理中注册**:
```python
from app.tool import MyTool, ToolCollection

class MyAgent(ToolCallAgent):
    available_tools = ToolCollection(MyTool(), ...)
```

### 9.2 添加新代理

**步骤**:
1. 在`app/agent/`目录创建新文件
2. 继承`ToolCallAgent`、`ReActAgent`或`BaseAgent`
3. 配置`system_prompt`和`next_step_prompt`
4. 定义工具集合
5. 可选：覆盖`think()`或`act()`方法
6. 可选：实现`cleanup()`方法

**示例**:
```python
# app/agent/my_agent.py
from app.agent.toolcall import ToolCallAgent
from app.tool import ToolCollection, MyTool, Terminate

class MyAgent(ToolCallAgent):
    """我的代理"""
    name = "my_agent"
    description = "我的代理描述"
    system_prompt = "You are a helpful assistant..."
    next_step_prompt = "What should I do next?"
    max_steps = 20
    max_observe = 10000

    available_tools = ToolCollection(
        MyTool(),
        Terminate(),
    )
    special_tool_names = [Terminate().name]

    # 可选：覆盖think()方法
    async def think(self) -> bool:
        # 自定义思考逻辑
        return await super().think()

    # 可选：覆盖cleanup()方法
    async def cleanup(self):
        # 清理资源
        await super().cleanup()
```

### 9.3 添加新流程

**步骤**:
1. 在`app/flow/`目录创建新文件
2. 继承`BaseFlow`
3. 实现`execute()`方法
4. 在`FlowFactory`中注册

**示例**:
```python
# app/flow/my_flow.py
from app.flow.base import BaseFlow

class MyFlow(BaseFlow):
    """我的流程"""

    async def execute(self, input_text: str) -> str:
        """执行流程"""
        # 1. 准备阶段
        # 2. 执行阶段
        # 3. 完成阶段
        return "流程结果"

# 在FlowFactory中注册
# app/flow/flow_factory.py
class FlowType(str, Enum):
    PLANNING = "planning"
    MY_FLOW = "my_flow"  # 新增

def create_flow(flow_type: FlowType, ...):
    if flow_type == FlowType.MY_FLOW:
        from app.flow.my_flow import MyFlow
        return MyFlow(agents=agents, **kwargs)
```

### 9.4 添加新沙箱工具

**步骤**:
1. 在`app/tool/sandbox/`目录创建新文件
2. 继承`SandboxToolsBase`
3. 实现工具逻辑（使用`self.sandbox`访问沙箱）
4. 在`SandboxManus`中注册

**示例**:
```python
# app/tool/sandbox/sb_my_tool.py
from app.daytona.tool_base import SandboxToolsBase
from app.tool.base import ToolResult

class SandboxMyTool(SandboxToolsBase):
    """我的沙箱工具"""
    name = "sandbox_my_tool"
    description = "我的沙箱工具描述"
    parameters = {...}

    def __init__(self, sandbox=None, **data):
        super().__init__(**data)
        if sandbox is not None:
            self._sandbox = sandbox

    async def execute(self, **kwargs) -> ToolResult:
        """执行工具"""
        await self._ensure_sandbox()  # 确保沙箱存在
        # 使用self.sandbox访问沙箱API
        result = self.sandbox.fs.some_operation(...)
        return self.success_response(str(result))
```

### 9.5 添加新的LLM提供商

**步骤**:
1. 在`app/llm.py`中添加新的客户端初始化逻辑
2. 实现统一的API接口适配
3. 更新配置类支持新提供商

**示例**:
```python
# app/llm.py
if self.api_type == "custom":
    from custom_llm import CustomLLMClient
    self.client = CustomLLMClient(
        api_key=kwargs.get("api_key"),
        endpoint=kwargs.get("endpoint"),
    )
```

## 10. 性能优化设计

### 10.1 异步设计

**异步I/O**:
- 所有网络请求使用`async/await`
- 文件操作使用异步版本
- 数据库操作（如有）使用异步驱动

**并发执行**:
- 工具执行支持并发（通过`asyncio.gather`）
- MCP工具调用可并发
- 网络搜索结果并发获取

**示例**:
```python
# 并发执行多个工具
results = await asyncio.gather(
    tool1.execute(...),
    tool2.execute(...),
    tool3.execute(...),
)
```

### 10.2 Token优化

**流式响应**:
- `ask()`方法默认使用流式响应
- 减少用户感知延迟
- 实时显示生成内容

**Token计数**:
- 实时计算Token数量
- 提前检查Token限制
- 避免API调用失败

**消息截断**:
- `max_messages`限制历史消息数量
- 保留最近N条消息
- 减少Token消耗

**消息压缩**:
- 长消息自动截断
- 工具结果长度限制（`max_observe`）
- 图像压缩（沙箱视觉工具）

### 10.3 资源管理

**上下文管理器**:
- `state_context`: 状态转换管理
- `__aenter__`/`__aexit__`: 资源自动清理
- `with`语句确保资源释放

**及时清理**:
- `cleanup()`方法统一清理接口
- `finally`块确保清理执行
- 代理结束时自动清理

**沙箱复用**:
- `SandboxManager`管理沙箱生命周期
- 空闲超时自动清理
- 并发控制避免冲突

**连接复用**:
- MCP连接复用
- LLM客户端单例
- 浏览器会话保持

### 10.4 缓存机制

**LLM客户端缓存**:
- 基于配置键的单例模式
- 避免重复创建客户端
- 减少资源消耗

**配置缓存**:
- 单例模式缓存配置
- 避免重复加载TOML文件
- 线程安全访问

### 10.5 并发控制

**锁机制**:
- `asyncio.Lock`保护共享资源
- 浏览器操作锁（`BrowserUseTool.lock`）
- 沙箱操作锁（每个沙箱独立锁）

**全局锁**:
- 配置加载全局锁
- 沙箱管理器全局锁
- 避免竞态条件

## 11. 安全性设计

### 11.1 代码执行隔离

**Docker沙箱**:
- 容器隔离：每个执行环境独立
- 资源限制：
  - CPU限制：`cpu_quota`和`cpu_period`
  - 内存限制：`mem_limit`
  - 超时控制：`timeout`
- 网络访问控制：
  - 默认禁用网络（`network_mode="none"`）
  - 可配置启用网络（`network_enabled=True`）

**Daytona沙箱**:
- 云沙箱隔离
- 独立的文件系统
- 进程隔离
- VNC访问控制（密码保护）

**进程隔离** (PythonExecute):
- `multiprocessing`独立进程
- 超时终止机制
- 输出重定向

### 11.2 输入验证

**Pydantic模型验证**:
- 所有配置使用Pydantic验证
- 类型自动转换和验证
- 默认值处理

**JSON Schema验证**:
- 工具参数使用JSON Schema验证
- LLM函数调用参数验证
- 类型和格式检查

**路径验证**:
```python
def _safe_resolve_path(self, path: str) -> str:
    """安全解析路径，防止路径遍历"""
    # 检查路径遍历尝试
    if ".." in path.split("/"):
        raise ValueError("Path contains potentially unsafe patterns")

    # 规范化路径
    resolved = os.path.join(self.config.work_dir, path) if not os.path.isabs(path) else path
    return resolved
```

**命令验证**:
```python
def _sanitize_command(self, command: str) -> str:
    """清理命令，防止危险操作"""
    risky_commands = [
        "rm -rf /",
        "rm -rf /*",
        "mkfs",
        "dd if=/dev/zero",
        ":(){:|:&};:",  # Fork bomb
        "chmod -R 777 /",
    ]

    for risky in risky_commands:
        if risky in command.lower():
            raise ValueError(f"Command contains potentially dangerous operation: {risky}")

    return command
```

### 11.3 错误信息过滤

**敏感信息保护**:
- API密钥不记录到日志
- 错误消息不包含内部路径
- 用户输入验证和清理

**错误信息标准化**:
- 统一的错误格式
- 避免泄露系统信息
- 用户友好的错误消息

### 11.4 访问控制

**API密钥管理**:
- 环境变量优先
- 配置文件支持
- 不在代码中硬编码

**文件访问限制**:
- 限制在指定目录（`workspace_root`）
- 路径验证防止越界
- 沙箱文件系统隔离

**网络访问控制**:
- 沙箱默认无网络
- 浏览器代理配置
- MCP连接验证

### 11.5 数据安全

**内存管理**:
- 对话历史限制
- 敏感数据不持久化
- 及时清理内存

**传输安全**:
- HTTPS API调用
- Base64编码图像传输
- 安全的MCP连接

## 12. 测试设计

### 12.1 单元测试

**工具测试** (`tests/tool/`):
- 工具执行测试
- 参数验证测试
- 错误处理测试
- 工具结果格式化测试

**LLM客户端测试** (`tests/llm/`):
- API调用测试
- Token计数测试
- 多提供商测试
- 流式响应测试

**配置加载测试** (`tests/config/`):
- TOML解析测试
- 配置验证测试
- 默认值测试
- 多配置测试

**代理测试** (`tests/agent/`):
- 状态管理测试
- 内存管理测试
- 卡死检测测试
- 执行循环测试

### 12.2 集成测试

**代理执行流程测试**:
- 完整执行流程测试
- 工具调用链测试
- 错误恢复测试
- 资源清理测试

**多代理协作测试**:
- PlanningFlow测试
- 代理切换测试
- 状态同步测试

**端到端测试**:
- 完整任务执行测试
- 多工具组合测试
- 真实场景测试

### 12.3 模拟测试

**Mock LLM响应**:
```python
from unittest.mock import AsyncMock, patch

@patch('app.llm.LLM.ask_tool')
async def test_agent_tool_call(mock_ask_tool):
    # Mock LLM响应
    mock_response = AsyncMock()
    mock_response.tool_calls = [ToolCall(...)]
    mock_ask_tool.return_value = mock_response

    # 测试代理工具调用
    agent = ToolCallAgent(...)
    result = await agent.think()
    assert result == True
```

**Mock工具执行**:
```python
@patch('app.tool.python_execute.PythonExecute.execute')
async def test_tool_execution(mock_execute):
    mock_execute.return_value = ToolResult(output="Success")

    tool = PythonExecute()
    result = await tool.execute(code="print('hello')")
    assert result.output == "Success"
```

**Mock网络请求**:
```python
from unittest.mock import patch
import aiohttp

@patch('aiohttp.ClientSession.get')
async def test_web_search(mock_get):
    mock_response = AsyncMock()
    mock_response.text = "<html>...</html>"
    mock_get.return_value.__aenter__.return_value = mock_response

    tool = WebSearch()
    result = await tool.execute(query="test")
    assert result.output is not None
```

### 12.4 沙箱测试

**文件位置**: `tests/sandbox/`

**测试内容**:
- 沙箱创建和删除测试
- 命令执行测试
- 文件操作测试
- 资源限制测试
- 超时处理测试

**测试工具**:
- `test_sandbox.py`: Docker沙箱基本功能测试
- `test_sandbox_manager.py`: 沙箱管理器测试
- `test_client.py`: 沙箱客户端测试
- `test_docker_terminal.py`: 终端功能测试

## 13. 沙箱系统设计

### 13.1 Docker沙箱设计

**文件位置**: `app/sandbox/core/sandbox.py`

**DockerSandbox类**:
- **容器管理**: 创建、启动、停止、删除Docker容器
- **资源限制**: CPU、内存、超时
- **文件操作**: 读写、复制（容器↔主机）
- **命令执行**: 通过异步终端执行命令

**关键方法**:
```python
async def create(self) -> "DockerSandbox":
    """创建并启动沙箱容器"""
    # 1. 准备主机配置（资源限制、卷绑定）
    # 2. 创建容器
    # 3. 启动容器
    # 4. 初始化异步终端
    return self

async def run_command(self, cmd: str, timeout: Optional[int] = None) -> str:
    """在沙箱中执行命令"""
    # 通过异步终端执行
    return await self.terminal.run_command(cmd, timeout)

async def read_file(self, path: str) -> str:
    """从容器读取文件"""
    # 1. 安全解析路径
    # 2. 获取文件归档（tar流）
    # 3. 从tar流提取文件内容
    return content

async def write_file(self, path: str, content: str) -> None:
    """向容器写入文件"""
    # 1. 创建父目录
    # 2. 创建tar流
    # 3. 上传到容器
```

### 13.2 沙箱管理器设计

**文件位置**: `app/sandbox/core/manager.py`

**SandboxManager类**:
- **生命周期管理**: 创建、获取、删除沙箱
- **并发控制**: 每个沙箱独立锁
- **自动清理**: 空闲超时清理
- **资源统计**: 监控沙箱使用情况

**关键方法**:
```python
async def create_sandbox(
    self,
    config: Optional[SandboxSettings] = None,
    volume_bindings: Optional[Dict[str, str]] = None,
) -> str:
    """创建新沙箱"""
    # 1. 检查最大数量限制
    # 2. 确保Docker镜像存在
    # 3. 创建DockerSandbox实例
    # 4. 调用create()方法
    # 5. 注册到管理器
    return sandbox_id

async def get_sandbox(self, sandbox_id: str) -> DockerSandbox:
    """获取沙箱实例（带并发控制）"""
    async with self.sandbox_operation(sandbox_id) as sandbox:
        return sandbox

@asynccontextmanager
async def sandbox_operation(self, sandbox_id: str):
    """沙箱操作上下文管理器"""
    # 1. 获取或创建锁
    # 2. 更新最后使用时间
    # 3. 标记为活动操作
    # 4. yield沙箱实例
    # 5. 清理活动标记
```

**自动清理机制**:
```python
async def _cleanup_idle_sandboxes(self) -> None:
    """清理空闲沙箱"""
    current_time = asyncio.get_event_loop().time()
    to_cleanup = []

    # 查找空闲超时的沙箱
    for sandbox_id, last_used in self._last_used.items():
        if (sandbox_id not in self._active_operations and
            current_time - last_used > self.idle_timeout):
            to_cleanup.append(sandbox_id)

    # 并发清理
    for sandbox_id in to_cleanup:
        await self.delete_sandbox(sandbox_id)
```

### 13.3 异步终端设计

**文件位置**: `app/sandbox/core/terminal.py`

**AsyncDockerizedTerminal类**:
- **交互式会话**: 基于Docker exec的交互式终端
- **命令执行**: 支持超时控制
- **输出解析**: 清理提示符和命令回显

**DockerSession类**:
- **Socket通信**: 通过Docker API socket通信
- **命令发送**: 发送命令到容器stdin
- **输出读取**: 从容器stdout/stderr读取
- **提示符检测**: 检测命令完成（通过提示符）

**关键方法**:
```python
async def run_command(self, cmd: str, timeout: Optional[int] = None) -> str:
    """执行命令"""
    # 1. 清理命令（防止注入）
    sanitized_command = self._sanitize_command(cmd)

    # 2. 发送命令（追加echo $?用于检测完成）
    full_command = f"{sanitized_command}\necho $?\n"
    self.socket.sendall(full_command.encode())

    # 3. 读取输出直到提示符
    output = await self._read_until_prompt(timeout)

    # 4. 清理输出（移除命令回显和提示符）
    cleaned_output = self._clean_output(output)

    return cleaned_output
```

### 13.4 Daytona沙箱设计

**文件位置**: `app/daytona/`

**沙箱操作** (`app/daytona/sandbox.py`):
- `create_sandbox()`: 创建Daytona沙箱
- `delete_sandbox()`: 删除沙箱
- `start_supervisord_session()`: 启动supervisord会话

**工具基类** (`app/daytona/tool_base.py`):
- `SandboxToolsBase`: 所有Daytona工具的基础类
- 沙箱生命周期管理
- 路径清理和验证
- 预览链接管理

## 14. MCP系统设计

### 14.1 MCP服务器设计

**文件位置**: `app/mcp/server.py`

**MCPServer类**:
- 基于FastMCP框架
- 动态注册本地工具
- 自动生成工具签名和文档

**工具注册流程**:
```python
def register_tool(self, tool: BaseTool, method_name: Optional[str] = None):
    """注册工具到MCP服务器"""
    # 1. 转换为OpenAI函数格式
    tool_param = tool.to_param()

    # 2. 创建异步包装函数
    async def tool_method(**kwargs):
        result = await tool.execute(**kwargs)
        # 格式化结果为JSON或字符串
        return json.dumps(result.to_dict()) if isinstance(result, ToolResult) else str(result)

    # 3. 动态设置函数属性
    tool_method.__name__ = method_name or tool.name
    tool_method.__doc__ = self._build_docstring(tool_param)
    tool_method.__signature__ = self._build_signature(tool_param)

    # 4. 注册到FastMCP服务器
    self.server.tool()(tool_method)
```

### 14.2 MCP客户端设计

**文件位置**: `app/tool/mcp.py`

**MCPClients类**:
- 管理多个MCP服务器连接
- 支持SSE和stdio传输
- 工具发现和注册
- 连接生命周期管理

**连接类型**:
1. **SSE连接**: 通过HTTP URL连接
2. **stdio连接**: 通过命令启动进程，stdin/stdout通信

**工具发现**:
```python
async def list_tools(self) -> ListToolsResponse:
    """列出所有MCP服务器的工具"""
    all_tools = []
    for session in self.sessions.values():
        response = await session.list_tools()
        all_tools.extend(response.tools)
    return ListToolsResponse(tools=all_tools)
```

## 15. 日志系统设计

### 15.1 Logger设计

**文件位置**: `app/logger.py`

**基于Loguru**:
- 统一的日志接口
- 支持文件和控制台输出
- 动态日志级别配置
- 日志文件自动轮转

**关键功能**:
```python
def define_log_level(level: str = "INFO", file_level: Optional[str] = None):
    """定义日志级别"""
    # 1. 配置stderr输出
    logger.remove()  # 移除默认handler
    logger.add(sys.stderr, level=level)

    # 2. 配置文件输出
    if file_level:
        log_dir = PROJECT_ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"openmanus_{datetime.now().strftime('%Y%m%d')}.log"
        logger.add(log_file, level=file_level, rotation="10 MB")
```

**日志使用**:
```python
from app.logger import logger

logger.debug("Debug message")
logger.info("Info message")
logger.warning("Warning message")
logger.error("Error message")
logger.exception("Exception with traceback")
```

## 16. 总结

本文档详细描述了OpenManus系统的设计细节，包括：

1. **核心类设计**: 代理层次结构、工具系统、LLM客户端
2. **工具系统**: 工具基类、工具集合、具体工具实现
3. **LLM集成**: 多提供商支持、Token管理、流式响应
4. **配置管理**: 单例模式、配置层次、验证机制
5. **内存管理**: 消息模型、内存类、状态管理
6. **流程管理**: 规划流程、流程工厂
7. **错误处理**: 异常层次、重试机制、错误恢复
8. **扩展性**: 添加工具、代理、流程的指南
9. **性能优化**: 异步设计、Token优化、资源管理
10. **安全性**: 代码隔离、输入验证、访问控制
11. **测试设计**: 单元测试、集成测试、模拟测试
12. **沙箱系统**: Docker沙箱、沙箱管理器、异步终端
13. **MCP系统**: MCP服务器、客户端、工具发现
14. **日志系统**: Loguru集成、日志配置

系统设计遵循SOLID原则，注重可扩展性、可维护性和安全性。通过工具系统扩展代理能力，通过流程系统支持多代理协作，通过沙箱系统确保安全执行。
