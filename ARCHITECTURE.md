# OpenManus 架构文档

## 1. 概述

OpenManus 是一个开源的通用AI代理框架，旨在构建能够使用多种工具完成复杂任务的智能代理系统。系统采用分层架构设计，支持多种代理类型、工具集成和执行环境。本文档描述了OpenManus的整体架构设计。

## 2. 系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户接口层                                │
│  main.py, run_flow.py, run_mcp.py, sandbox_main.py            │
└──────────────────────────┬──────────────────────────────────────┘
                          │
┌──────────────────────────▼──────────────────────────────────────┐
│                      代理层 (Agent Layer)                      │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              BaseAgent (抽象基类)                         │  │
│  │  - 状态管理 (IDLE/RUNNING/FINISHED/ERROR)                │  │
│  │  - 内存管理 (Memory)                                     │  │
│  │  - 执行循环框架                                           │  │
│  └──────────────────┬───────────────────────────────────────┘  │
│                     │                                          │
│  ┌──────────────────▼───────────────────────────────────────┐  │
│  │          ReActAgent (ReAct模式实现)                       │  │
│  │  - think() 思考阶段                                       │  │
│  │  - act()  行动阶段                                       │  │
│  └──────────────────┬───────────────────────────────────────┘  │
│                     │                                          │
│  ┌──────────────────▼───────────────────────────────────────┐  │
│  │        ToolCallAgent (工具调用代理)                       │  │
│  │  - LLM函数调用集成                                        │  │
│  │  - 工具集合管理                                           │  │
│  │  - 工具执行流程                                           │  │
│  └──────┬──────────────┬──────────────┬──────────────┬───────┘  │
│         │              │              │              │          │
│  ┌──────▼──────┐ ┌─────▼─────┐ ┌─────▼─────┐ ┌─────▼──────┐  │
│  │   Manus     │ │ Browser   │ │   MCP      │ │ Sandbox    │  │
│  │  (通用代理)  │ │  Agent    │ │  Agent     │ │  Manus     │  │
│  └─────────────┘ └───────────┘ └───────────┘ └────────────┘  │
│  ┌──────────────┐ ┌───────────┐ ┌───────────┐ ┌────────────┐  │
│  │ DataAnalysis│ │   SWE     │ │           │ │            │  │
│  │  (数据分析)  │ │  Agent    │ │           │ │            │  │
│  └──────────────┘ └───────────┘ └───────────┘ └────────────┘  │
└──────────────────────────┬──────────────────────────────────────┘
                          │
┌──────────────────────────▼──────────────────────────────────────┐
│                      工具层 (Tool Layer)                         │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              BaseTool (工具基类)                          │  │
│  │  - 工具接口定义                                           │  │
│  │  - ToolResult封装                                        │  │
│  └──────────────────┬───────────────────────────────────────┘  │
│                     │                                          │
│  ┌──────────────────▼───────────────────────────────────────┐  │
│  │        ToolCollection (工具集合管理)                      │  │
│  │  - 工具注册和查找                                         │  │
│  │  - 批量执行支持                                           │  │
│  └──────────────────┬───────────────────────────────────────┘  │
│                     │                                          │
│  ┌──────────────────▼───────────────────────────────────────┐  │
│  │                    具体工具实现                            │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │  │
│  │  │PythonExecute │  │BrowserUseTool│  │StrReplaceEdit│  │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │  │
│  │  │  WebSearch   │  │   AskHuman   │  │  Terminate   │  │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │  │
│  │  │ MCPClientTool│  │CreateChatComp│  │     Bash     │  │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  │  │
│  │                                                           │  │
│  │              沙箱工具 (Sandbox Tools)                      │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │  │
│  │  │SandboxBrowser│  │SandboxFiles  │  │SandboxShell  │  │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  │  │
│  │  ┌──────────────┐                                        │  │
│  │  │SandboxVision │                                        │  │
│  │  └──────────────┘                                        │  │
│  └───────────────────────────────────────────────────────────┘  │
└──────────────────────────┬──────────────────────────────────────┘
                          │
┌──────────────────────────▼──────────────────────────────────────┐
│                   基础设施层 (Infrastructure)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │  LLM Client  │  │   Sandbox    │  │  Browser     │        │
│  │  - OpenAI    │  │  - Docker    │  │  - Playwright│        │
│  │  - Azure     │  │  - Daytona   │  │  - browser_use│       │
│  │  - Bedrock   │  │  - Manager   │  │              │        │
│  └──────────────┘  └──────────────┘  └──────────────┘        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │   Config     │  │    Logger     │  │     MCP      │        │
│  │  - Singleton │  │  - Loguru    │  │  - Server    │        │
│  │  - TOML      │  │  - File/Stderr│  │  - Client     │        │
│  └──────────────┘  └──────────────┘  └──────────────┘        │
│  ┌──────────────┐  ┌──────────────┐                          │
│  │    Schema    │  │     Flow     │                          │
│  │  - Message   │  │  - Planning  │                          │
│  │  - Memory    │  │  - Factory   │                          │
│  └──────────────┘  └──────────────┘                          │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 核心组件

#### 2.2.1 代理层 (Agent Layer)

**BaseAgent** (`app/agent/base.py`)
- **职责**: 所有代理的抽象基类，提供基础框架
- **核心功能**:
  - 状态管理：IDLE → RUNNING → FINISHED/ERROR
  - 内存管理：使用`Memory`类存储对话历史
  - 执行循环：`run()`方法实现主循环
  - 卡死检测：`is_stuck()`检测重复响应
  - 资源清理：`cleanup()`方法确保资源释放
- **关键方法**:
  - `run(request)`: 主执行循环
  - `step()`: 单步执行（抽象方法）
  - `update_memory()`: 更新对话内存
  - `state_context()`: 状态转换上下文管理器

**ReActAgent** (`app/agent/react.py`)
- **职责**: 实现ReAct（Reasoning + Acting）模式
- **设计模式**: 模板方法模式
- **执行流程**: `think()` → `act()`
- **扩展点**: 子类实现`think()`和`act()`方法

**ToolCallAgent** (`app/agent/toolcall.py`)
- **职责**: 基于LLM函数调用的代理实现
- **核心功能**:
  - LLM工具调用集成：`ask_tool()`方法
  - 工具集合管理：`available_tools`
  - 工具执行：`execute_tool()`方法
  - 特殊工具处理：`Terminate`等
- **工具选择策略**: NONE/AUTO/REQUIRED
- **关键方法**:
  - `think()`: 调用LLM并解析工具调用
  - `act()`: 执行工具调用
  - `execute_tool()`: 查找并执行单个工具

**Manus** (`app/agent/manus.py`)
- **职责**: 通用代理实现，集成多种工具
- **工具集合**:
  - `PythonExecute`: Python代码执行
  - `BrowserUseTool`: 浏览器自动化
  - `StrReplaceEditor`: 文件编辑
  - `AskHuman`: 人工交互
  - `Terminate`: 终止执行
- **MCP集成**: 动态连接MCP服务器并添加工具
- **浏览器上下文**: `BrowserContextHelper`提供浏览器状态

**BrowserAgent** (`app/agent/browser.py`)
- **职责**: 专门用于浏览器自动化的代理
- **特点**:
  - 集成`BrowserUseTool`
  - `BrowserContextHelper`管理浏览器状态
  - 动态调整提示词包含浏览器上下文
  - 自动获取浏览器截图和状态

**MCPAgent** (`app/agent/mcp.py`)
- **职责**: 专门用于MCP服务器交互的代理
- **特点**:
  - 支持SSE和stdio两种连接方式
  - 动态刷新工具列表
  - 处理工具变化通知
  - 多媒体响应支持

**SandboxManus** (`app/agent/sandbox_agent.py`)
- **职责**: 基于Daytona沙箱的通用代理
- **特点**:
  - 集成Daytona沙箱环境
  - 使用沙箱工具（Browser、Files、Shell、Vision）
  - 支持MCP工具扩展
  - 管理沙箱生命周期

**DataAnalysis** (`app/agent/data_analysis.py`)
- **职责**: 数据分析专用代理
- **工具集合**:
  - `NormalPythonExecute`: Python执行
  - `VisualizationPrepare`: 可视化准备
  - `DataVisualization`: 数据可视化
  - `Terminate`: 终止执行

**SWEAgent** (`app/agent/swe.py`)
- **职责**: 软件工程代理（SWE = Software Engineering）
- **工具集合**:
  - `Bash`: Shell命令执行
  - `StrReplaceEditor`: 文件编辑
  - `Terminate`: 终止执行

#### 2.2.2 工具层 (Tool Layer)

**BaseTool** (`app/tool/base.py`)
- **职责**: 所有工具的抽象基类
- **接口定义**:
  - `name`: 工具名称
  - `description`: 工具描述
  - `parameters`: JSON Schema格式的参数定义
  - `execute()`: 执行方法（抽象）
- **工具结果**: `ToolResult`封装执行结果
  - `output`: 成功输出
  - `error`: 错误信息
  - `base64_image`: 图像数据
  - `system`: 系统消息

**ToolCollection** (`app/tool/tool_collection.py`)
- **职责**: 工具集合管理
- **功能**:
  - 工具注册：`add_tool()`、`add_tools()`
  - 工具查找：`get_tool()`
  - 工具执行：`execute()`
  - 批量转换：`to_params()`转换为LLM格式

**本地工具实现**:
- `PythonExecute`: 在隔离进程中执行Python代码
- `BrowserUseTool`: 基于browser_use库的浏览器自动化
- `StrReplaceEditor`: 文件查看、编辑、创建
- `WebSearch`: 多搜索引擎支持（Google、Baidu、DuckDuckGo、Bing）
- `AskHuman`: 人工交互工具
- `Terminate`: 终止执行工具
- `Bash`: 持久化Shell会话
- `CreateChatCompletion`: 结构化响应生成
- `MCPClientTool`: MCP客户端工具包装

**沙箱工具实现** (`app/tool/sandbox/`):
- `SandboxBrowserTool`: 沙箱环境中的浏览器自动化
- `SandboxFilesTool`: 沙箱文件系统操作
- `SandboxShellTool`: 沙箱Shell命令执行（基于tmux会话）
- `SandboxVisionTool`: 沙箱图像读取和处理

#### 2.2.3 基础设施层 (Infrastructure Layer)

**LLM** (`app/llm.py`)
- **职责**: 大语言模型客户端封装
- **支持的提供商**:
  - OpenAI: 标准OpenAI API
  - Azure OpenAI: Azure部署的OpenAI
  - AWS Bedrock: AWS Bedrock服务
- **核心功能**:
  - 统一API接口：`ask()`、`ask_tool()`、`ask_with_images()`
  - Token计数：`TokenCounter`类精确计算Token
  - 流式和非流式响应
  - 多模态支持：图像输入
  - 重试机制：指数退避策略
  - Token限制检查：防止超限

**Config** (`app/config.py`)
- **职责**: 配置管理单例
- **设计模式**: 单例模式（双重检查锁定）
- **配置来源**: TOML文件（`config.toml`）
- **配置层次**:
  - LLM配置：支持多个LLM配置（default、vision等）
  - 浏览器配置：代理、无头模式等
  - 沙箱配置：Docker镜像、资源限制
  - 搜索配置：搜索引擎、重试策略
  - MCP配置：服务器连接信息
  - Daytona配置：Daytona服务器配置
  - 流程配置：多代理设置

**Sandbox** (`app/sandbox/`)
- **Docker沙箱** (`app/sandbox/core/sandbox.py`):
  - `DockerSandbox`: Docker容器沙箱实现
  - 资源限制：CPU、内存、超时
  - 文件操作：读写、复制
  - 命令执行：通过异步终端
- **沙箱管理器** (`app/sandbox/core/manager.py`):
  - `SandboxManager`: 管理多个沙箱实例
  - 并发控制：每个沙箱独立锁
  - 自动清理：空闲超时清理
  - 资源统计：监控沙箱使用情况
- **异步终端** (`app/sandbox/core/terminal.py`):
  - `AsyncDockerizedTerminal`: Docker容器异步终端
  - `DockerSession`: 交互式会话管理
  - 命令执行：支持超时控制

**Daytona沙箱** (`app/daytona/`)
- **沙箱工具基类** (`app/daytona/tool_base.py`):
  - `SandboxToolsBase`: 所有Daytona工具的基础类
  - 沙箱生命周期管理
  - 路径清理和验证
- **沙箱操作** (`app/daytona/sandbox.py`):
  - `create_sandbox()`: 创建Daytona沙箱
  - `delete_sandbox()`: 删除沙箱
  - `start_supervisord_session()`: 启动supervisord会话

**Browser** (`app/agent/browser.py`)
- **BrowserContextHelper**: 浏览器上下文助手
  - 获取浏览器状态
  - 格式化提示词
  - 管理浏览器截图
- **BrowserUseTool**: 基于browser_use库的浏览器工具
  - 页面导航
  - 元素交互
  - 内容提取

**MCP** (`app/mcp/`)
- **MCP服务器** (`app/mcp/server.py`):
  - `MCPServer`: 基于FastMCP的服务器实现
  - 工具注册：动态注册本地工具
  - 签名生成：自动生成工具签名
- **MCP客户端** (`app/tool/mcp.py`):
  - `MCPClients`: MCP客户端集合
  - 连接管理：SSE和stdio连接
  - 工具发现：动态获取远程工具

**Flow** (`app/flow/`)
- **BaseFlow** (`app/flow/base.py`):
  - 多代理管理
  - 主代理标识
- **PlanningFlow** (`app/flow/planning.py`):
  - 规划-执行模式
  - 步骤管理：创建、执行、完成
  - 代理选择：根据步骤类型选择执行代理
- **FlowFactory** (`app/flow/flow_factory.py`):
  - 流程工厂：创建不同类型的流程

**Schema** (`app/schema.py`)
- **Message**: 消息模型
  - 角色：SYSTEM/USER/ASSISTANT/TOOL
  - 内容：文本、图像、工具调用
- **Memory**: 内存管理
  - 消息列表管理
  - 消息数量限制
  - 最近消息查询
- **AgentState**: 代理状态枚举
- **ToolChoice**: 工具选择策略枚举

**Logger** (`app/logger.py`)
- 基于Loguru的日志系统
- 支持文件和控制台输出
- 动态日志级别配置

## 3. 数据流

### 3.1 单代理执行流程

```
用户输入
   │
   ▼
Manus.run(request)
   │
   ▼
BaseAgent.run() - 主循环
   │
   ├─► 状态检查 (IDLE?)
   │
   ├─► 添加用户消息到内存
   │
   ├─► 进入RUNNING状态 (state_context)
   │
   ├─► 循环执行 (while current_step < max_steps)
   │     │
   │     ├─► step() - ToolCallAgent.step()
   │     │     │
   │     │     ├─► think() - ToolCallAgent.think()
   │     │     │     │
   │     │     │     ├─► 添加next_step_prompt
   │     │     │     │
   │     │     │     ├─► LLM.ask_tool()
   │     │     │     │     │
   │     │     │     │     ├─► format_messages()
   │     │     │     │     │
   │     │     │     │     ├─► count_message_tokens()
   │     │     │     │     │
   │     │     │     │     ├─► check_token_limit()
   │     │     │     │     │
   │     │     │     │     └─► API调用 (非流式)
   │     │     │     │
   │     │     │     ├─► 解析tool_calls和content
   │     │     │     │
   │     │     │     └─► 创建assistant消息并添加到内存
   │     │     │
   │     │     └─► act() - ToolCallAgent.act()
   │     │           │
   │     │           ├─► 遍历tool_calls
   │     │           │     │
   │     │           │     ├─► execute_tool()
   │     │           │     │     │
   │     │           │     │     ├─► 查找工具 (ToolCollection.get_tool())
   │     │           │     │     │
   │     │           │     │     ├─► 解析参数 (JSON)
   │     │           │     │     │
   │     │           │     │     ├─► 执行工具 (tool.execute())
   │     │           │     │     │
   │     │           │     │     ├─► 处理特殊工具 (_handle_special_tool)
   │     │           │     │     │
   │     │           │     │     └─► 格式化结果
   │     │           │     │
   │     │           │     └─► 创建tool消息并添加到内存
   │     │           │
   │     │           └─► 返回结果字符串
   │     │
   │     ├─► 检查卡死状态 (is_stuck())
   │     │
   │     └─► 更新current_step
   │
   ├─► 状态转换 (FINISHED/ERROR)
   │
   └─► 清理资源 (cleanup)
```

### 3.2 工具调用流程

```
LLM返回工具调用响应
   │
   ▼
解析tool_calls (List[ToolCall])
   │
   ▼
遍历每个工具调用
   │
   ├─► 提取工具名称和参数
   │
   ├─► 查找工具 (ToolCollection.get_tool(name))
   │     │
   │     └─► 工具不存在 → 返回错误
   │
   ├─► 解析参数 (JSON.parse(arguments))
   │     │
   │     └─► JSON解析失败 → 返回错误
   │
   ├─► 执行工具 (tool.execute(**args))
   │     │
   │     ├─► 工具执行成功 → ToolResult(output=...)
   │     │
   │     └─► 工具执行失败 → ToolResult(error=...)
   │
   ├─► 处理特殊工具
   │     │
   │     ├─► Terminate → 设置state=FINISHED
   │     │
   │     └─► 其他特殊工具 → 自定义处理
   │
   ├─► 限制结果长度 (max_observe)
   │
   └─► 创建tool消息并添加到内存
```

### 3.3 多代理流程（PlanningFlow）

```
用户输入任务
   │
   ▼
PlanningFlow.execute(input_text)
   │
   ├─► _create_initial_plan()
   │     │
   │     ├─► 构建规划提示词（包含代理描述）
   │     │
   │     ├─► LLM.ask_tool() + PlanningTool
   │     │
   │     └─► 创建计划并存储
   │
   ├─► 循环执行计划步骤
   │     │
   │     ├─► _get_current_step_info()
   │     │     │
   │     │     ├─► 查找第一个未完成的步骤
   │     │     │
   │     │     ├─► 提取步骤类型 ([CODE], [BROWSER]等)
   │     │     │
   │     │     └─► 标记步骤为IN_PROGRESS
   │     │
   │     ├─► get_executor(step_type)
   │     │     │
   │     │     └─► 根据步骤类型选择代理
   │     │
   │     ├─► _execute_step(executor, step_info)
   │     │     │
   │     │     ├─► 构建步骤提示词
   │     │     │
   │     │     ├─► executor.run(step_prompt)
   │     │     │
   │     │     └─► 记录执行结果
   │     │
   │     ├─► _mark_step_completed()
   │     │
   │     └─► 检查是否还有未完成步骤
   │
   └─► _finalize_plan()
         │
         ├─► 获取最终计划文本
         │
         └─► 生成计划总结
```

### 3.4 MCP工具集成流程

```
Manus.initialize_mcp_servers()
   │
   ├─► 遍历配置中的MCP服务器
   │     │
   │     ├─► SSE连接
   │     │     │
   │     │     └─► mcp_clients.connect_sse(url, server_id)
   │     │
   │     └─► stdio连接
   │           │
   │           └─► mcp_clients.connect_stdio(command, args, server_id)
   │
   ├─► 获取服务器工具列表
   │
   ├─► 创建MCPClientTool实例
   │
   └─► 添加到available_tools
```

### 3.5 沙箱工具执行流程（Daytona）

```
SandboxManus.initialize_sandbox_tools()
   │
   ├─► create_sandbox(password)
   │     │
   │     └─► 创建Daytona沙箱实例
   │
   ├─► 获取预览链接 (VNC、Website)
   │
   ├─► 创建沙箱工具实例
   │     │
   │     ├─► SandboxBrowserTool(sandbox)
   │     ├─► SandboxFilesTool(sandbox)
   │     ├─► SandboxShellTool(sandbox)
   │     └─► SandboxVisionTool(sandbox)
   │
   └─► 添加到available_tools

工具执行时:
   │
   ├─► tool._ensure_sandbox()
   │     │
   │     ├─► 检查沙箱状态
   │     │
   │     ├─► 如果停止/归档 → 启动沙箱
   │     │
   │     └─► 返回沙箱实例
   │
   └─► tool.execute() → 使用沙箱API执行操作
```

## 4. 关键设计模式

### 4.1 单例模式
- **Config类**: 使用双重检查锁定实现线程安全的单例
  ```python
  if cls._instance is None:
      with cls._lock:
          if cls._instance is None:
              cls._instance = super().__new__(cls)
  ```
- **LLM类**: 使用类字典缓存实现单例（基于配置键）

### 4.2 工厂模式
- **FlowFactory**: 创建不同类型的流程实例
- **Manus.create()**: 工厂方法创建Manus实例（异步初始化）
- **SandboxManus.create()**: 工厂方法创建SandboxManus实例

### 4.3 策略模式
- **ToolChoice**: 工具选择策略（NONE/AUTO/REQUIRED）
- **不同代理**: 实现不同的执行策略
- **LLM提供商**: 不同LLM提供商的策略实现

### 4.4 模板方法模式
- **BaseAgent.run()**: 定义执行框架，子类实现`step()`
- **ReActAgent.step()**: 定义think-act模式，子类实现`think()`和`act()`
- **BaseFlow.execute()**: 定义流程框架，子类实现具体逻辑

### 4.5 观察者模式
- **Memory**: 消息存储和观察
- **AgentState**: 状态变化通知

### 4.6 适配器模式
- **MCPClientTool**: 将MCP工具适配为BaseTool接口
- **不同LLM提供商**: 统一接口适配不同API

### 4.7 装饰器模式
- **@retry**: 重试装饰器用于LLM调用
- **@asynccontextmanager**: 状态管理上下文管理器

## 5. 模块依赖关系

```
main.py / run_flow.py / sandbox_main.py
   │
   ├─► app.agent.manus.Manus
   │     │
   │     ├─► app.agent.toolcall.ToolCallAgent
   │     │     │
   │     │     ├─► app.agent.react.ReActAgent
   │     │     │     │
   │     │     │     └─► app.agent.base.BaseAgent
   │     │     │           │
   │     │     │           ├─► app.schema.Memory
   │     │     │           ├─► app.llm.LLM
   │     │     │           └─► app.config.Config
   │     │     │
   │     │     └─► app.tool.ToolCollection
   │     │           │
   │     │           └─► app.tool.base.BaseTool
   │     │
   │     ├─► app.agent.browser.BrowserContextHelper
   │     │
   │     └─► app.tool.mcp.MCPClients
   │
   ├─► app.flow.planning.PlanningFlow
   │     │
   │     ├─► app.flow.base.BaseFlow
   │     │
   │     └─► app.tool.planning.PlanningTool
   │
   └─► app.sandbox.client.SANDBOX_CLIENT
         │
         └─► app.sandbox.core.sandbox.DockerSandbox
```

## 6. 配置管理

### 6.1 配置文件结构

```
config/
├── config.toml              # 主配置文件
├── config.example.toml      # 配置示例
├── config.example-*.toml    # 不同场景的配置示例
└── mcp.json                 # MCP服务器配置
```

### 6.2 配置层次

1. **LLM配置**:
   - 模型选择（gpt-4, claude等）
   - API密钥和端点
   - 参数（temperature、max_tokens等）
   - 支持多个LLM配置（default、vision等）

2. **浏览器配置**:
   - 无头模式
   - 代理设置
   - 安全设置
   - 窗口大小

3. **沙箱配置**:
   - Docker镜像
   - 资源限制（CPU、内存）
   - 超时设置
   - 工作目录

4. **搜索配置**:
   - 搜索引擎选择
   - 重试策略
   - 语言和地区

5. **MCP配置**:
   - 服务器列表
   - 连接类型（SSE/stdio）
   - 连接参数

6. **Daytona配置**:
   - API密钥
   - 服务器URL
   - VNC密码

7. **流程配置**:
   - 多代理设置
   - 规划参数

## 7. 扩展点

### 7.1 添加新代理

**步骤**:
1. 在`app/agent/`创建新文件
2. 继承`BaseAgent`、`ReActAgent`或`ToolCallAgent`
3. 实现必要方法：
   - `step()`: 单步执行（如果继承BaseAgent）
   - `think()`和`act()`: 如果继承ReActAgent
4. 配置提示词：`system_prompt`、`next_step_prompt`
5. 配置工具集合：`available_tools`
6. 可选：覆盖`cleanup()`方法

**示例**:
```python
class MyAgent(ToolCallAgent):
    name = "my_agent"
    description = "我的代理"
    system_prompt = "..."
    next_step_prompt = "..."
    available_tools = ToolCollection(MyTool())
```

### 7.2 添加新工具

**步骤**:
1. 在`app/tool/`创建新文件
2. 继承`BaseTool`
3. 定义工具属性：
   - `name`: 工具名称
   - `description`: 工具描述
   - `parameters`: JSON Schema格式的参数定义
4. 实现`execute()`方法
5. 在`app/tool/__init__.py`导出
6. 在代理的`available_tools`中注册

**示例**:
```python
class MyTool(BaseTool):
    name = "my_tool"
    description = "我的工具"
    parameters = {
        "type": "object",
        "properties": {
            "param": {"type": "string"}
        },
        "required": ["param"]
    }

    async def execute(self, param: str) -> ToolResult:
        # 实现逻辑
        return self.success_response("结果")
```

### 7.3 添加新流程

**步骤**:
1. 在`app/flow/`创建新文件
2. 继承`BaseFlow`
3. 实现`execute()`方法
4. 在`FlowFactory`中注册

**示例**:
```python
class MyFlow(BaseFlow):
    async def execute(self, input_text: str) -> str:
        # 实现流程逻辑
        return "结果"
```

### 7.4 添加新沙箱工具

**步骤**:
1. 在`app/tool/sandbox/`创建新文件
2. 继承`SandboxToolsBase`
3. 实现工具逻辑（使用`self.sandbox`访问沙箱）
4. 在`SandboxManus`中注册

## 8. 性能考虑

### 8.1 异步设计
- 所有I/O操作使用`async/await`
- 支持并发工具执行
- 异步上下文管理器确保资源清理

### 8.2 Token管理
- 实时Token计数：`TokenCounter`类
- Token限制检查：防止API调用失败
- 流式响应：减少延迟感知
- 消息截断：`max_messages`限制历史长度

### 8.3 资源管理
- 上下文管理器：`state_context`、`__aenter__`/`__aexit__`
- 及时清理：`cleanup()`方法
- 沙箱复用：`SandboxManager`管理沙箱生命周期
- 连接池：MCP连接复用

### 8.4 并发控制
- 锁机制：`asyncio.Lock`保护共享资源
- 沙箱锁：每个沙箱独立锁
- 全局锁：配置加载等全局操作

## 9. 安全性

### 9.1 沙箱隔离
- **Docker沙箱**:
  - 容器隔离代码执行
  - 资源限制（CPU、内存）
  - 网络访问控制（可配置）
- **Daytona沙箱**:
  - 云沙箱隔离
  - 独立的文件系统
  - 进程隔离

### 9.2 输入验证
- **Pydantic模型**: 数据验证和类型检查
- **JSON Schema**: 工具参数验证
- **路径验证**: 防止路径遍历攻击（`_safe_resolve_path`）
- **命令验证**: Shell命令安全检查（`_sanitize_command`）

### 9.3 错误处理
- 异常捕获和日志记录
- 优雅降级机制
- 错误信息过滤：避免泄露敏感信息
- 超时控制：防止无限等待

### 9.4 访问控制
- API密钥管理：环境变量或配置文件
- 沙箱权限：最小权限原则
- 文件访问：限制在指定目录

## 10. 未来扩展方向

1. **多模态支持**:
   - 增强图像、视频处理能力
   - 音频输入输出
   - 多模态工具集成

2. **分布式执行**:
   - 支持多机器协作
   - 任务分发和负载均衡
   - 分布式状态管理

3. **持久化存储**:
   - 对话历史持久化
   - 计划持久化
   - 工具执行历史

4. **插件系统**:
   - 动态加载工具和代理
   - 插件市场和版本管理
   - 热插拔支持

5. **监控和可观测性**:
   - 性能指标收集
   - 分布式追踪
   - 实时监控面板

6. **增强的规划能力**:
   - 更智能的计划生成
   - 计划优化和调整
   - 多代理协作规划

7. **工具市场**:
   - 工具发现和分享
   - 工具评级和评论
   - 工具版本管理

8. **Web界面**:
   - 可视化代理执行
   - 交互式工具调用
   - 实时状态监控
