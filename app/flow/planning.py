import json  # JSON解析库，用于解析工具参数
import time  # 时间库，用于生成计划ID
from enum import Enum  # 枚举类型
from typing import Dict, List, Optional, Union  # 类型提示

from pydantic import Field  # Pydantic字段定义

from app.agent.base import BaseAgent  # 代理基类
from app.flow.base import BaseFlow  # 流程基类
from app.llm import LLM  # LLM客户端
from app.logger import logger  # 日志记录器
from app.schema import AgentState, Message, ToolChoice  # 数据模型和枚举
from app.tool import PlanningTool  # 规划工具


class PlanStepStatus(str, Enum):
    """计划步骤状态枚举类

    定义了计划步骤的所有可能状态
    """

    NOT_STARTED = "not_started"  # 未开始状态
    IN_PROGRESS = "in_progress"  # 进行中状态
    COMPLETED = "completed"  # 已完成状态
    BLOCKED = "blocked"  # 阻塞状态

    @classmethod
    def get_all_statuses(cls) -> list[str]:
        """返回所有可能的步骤状态值列表

        Returns:
            list[str]: 所有状态值的列表
        """
        return [status.value for status in cls]  # 提取所有枚举值

    @classmethod
    def get_active_statuses(cls) -> list[str]:
        """返回表示活动状态的值列表（未开始或进行中）

        Returns:
            list[str]: 活动状态值列表
        """
        return [cls.NOT_STARTED.value, cls.IN_PROGRESS.value]  # 返回未开始和进行中状态

    @classmethod
    def get_status_marks(cls) -> Dict[str, str]:
        """返回状态到标记符号的映射

        Returns:
            Dict[str, str]: 状态到标记符号的字典
        """
        return {
            cls.COMPLETED.value: "[✓]",  # 已完成标记
            cls.IN_PROGRESS.value: "[→]",  # 进行中标记
            cls.BLOCKED.value: "[!]",  # 阻塞标记
            cls.NOT_STARTED.value: "[ ]",  # 未开始标记
        }


class PlanningFlow(BaseFlow):
    """规划流程类

    管理使用代理进行任务的规划和执行。
    实现规划-执行模式：先创建计划，然后逐步执行计划中的步骤。
    """

    llm: LLM = Field(default_factory=lambda: LLM())  # LLM客户端，默认创建新实例
    planning_tool: PlanningTool = Field(default_factory=PlanningTool)  # 规划工具，默认创建新实例
    executor_keys: List[str] = Field(default_factory=list)  # 执行代理键名列表，默认为空列表
    active_plan_id: str = Field(default_factory=lambda: f"plan_{int(time.time())}")  # 活动计划ID，默认使用时间戳生成
    current_step_index: Optional[int] = None  # 当前步骤索引，可选

    def __init__(
        self, agents: Union[BaseAgent, List[BaseAgent], Dict[str, BaseAgent]], **data
    ):
        """初始化规划流程

        Args:
            agents: 代理对象、代理列表或代理字典
            **data: 其他数据（executors、plan_id、planning_tool等）
        """
        # 在super().__init__之前设置executor keys
        if "executors" in data:  # 如果data中包含executors
            data["executor_keys"] = data.pop("executors")  # 将executors重命名为executor_keys

        # 如果提供了计划ID，则设置
        if "plan_id" in data:  # 如果data中包含plan_id
            data["active_plan_id"] = data.pop("plan_id")  # 将plan_id重命名为active_plan_id

        # 如果未提供规划工具，则初始化
        if "planning_tool" not in data:  # 如果data中不包含planning_tool
            planning_tool = PlanningTool()  # 创建规划工具实例
            data["planning_tool"] = planning_tool  # 添加到data中

        # 使用处理后的数据调用父类的init
        super().__init__(agents, **data)  # 调用父类构造函数

        # 如果未指定executor_keys，则设置为所有代理键名
        if not self.executor_keys:  # 如果executor_keys为空
            self.executor_keys = list(self.agents.keys())  # 使用所有代理的键名

    def get_executor(self, step_type: Optional[str] = None) -> BaseAgent:
        """获取当前步骤的适当执行代理

        可以根据步骤类型选择代理。可以扩展以基于步骤类型/需求选择代理。

        Args:
            step_type: 步骤类型，可选

        Returns:
            BaseAgent: 执行代理对象
        """
        # 如果提供了步骤类型且匹配代理键名，使用该代理
        if step_type and step_type in self.agents:  # 如果步骤类型存在且匹配代理键名
            return self.agents[step_type]  # 返回对应的代理

        # 否则使用第一个可用的执行代理或回退到主代理
        for key in self.executor_keys:  # 遍历执行代理键名列表
            if key in self.agents:  # 如果键名在代理字典中
                return self.agents[key]  # 返回对应的代理

        # 回退到主代理
        return self.primary_agent  # 返回主代理

    async def execute(self, input_text: str) -> str:
        """使用代理执行规划流程

        主要执行流程：
        1. 创建初始计划（如果提供了输入）
        2. 循环执行计划步骤直到完成
        3. 完成计划并返回结果

        Args:
            input_text: 输入文本（任务描述）

        Returns:
            str: 执行结果摘要
        """
        try:
            if not self.primary_agent:  # 如果没有主代理
                raise ValueError("No primary agent available")  # 抛出值错误

            # 如果提供了输入，创建初始计划
            if input_text:  # 如果输入文本不为空
                await self._create_initial_plan(input_text)  # 创建初始计划

                # 验证计划是否成功创建
                if self.active_plan_id not in self.planning_tool.plans:  # 如果计划ID不在规划工具的计划字典中
                    logger.error(
                        f"Plan creation failed. Plan ID {self.active_plan_id} not found in planning tool."  # 记录错误日志
                    )
                    return f"Failed to create plan for: {input_text}"  # 返回失败消息

            result = ""  # 初始化结果字符串
            while True:  # 无限循环，直到计划完成
                # 获取要执行的当前步骤
                self.current_step_index, step_info = await self._get_current_step_info()  # 获取当前步骤索引和信息

                # 如果没有更多步骤或计划完成，退出
                if self.current_step_index is None:  # 如果当前步骤索引为None（没有更多步骤）
                    result += await self._finalize_plan()  # 完成计划并添加到结果
                    break  # 退出循环

                # 使用适当的代理执行当前步骤
                step_type = step_info.get("type") if step_info else None  # 获取步骤类型
                executor = self.get_executor(step_type)  # 获取执行代理
                step_result = await self._execute_step(executor, step_info)  # 执行步骤
                result += step_result + "\n"  # 将步骤结果添加到结果字符串

                # 检查代理是否想要终止
                if hasattr(executor, "state") and executor.state == AgentState.FINISHED:  # 如果代理状态为完成
                    break  # 退出循环

            return result  # 返回结果摘要
        except Exception as e:  # 捕获任何异常
            logger.error(f"Error in PlanningFlow: {str(e)}")  # 记录错误日志
            return f"Execution failed: {str(e)}"  # 返回失败消息

    async def _create_initial_plan(self, request: str) -> None:
        """Create an initial plan based on the request using the flow's LLM and PlanningTool."""
        logger.info(f"Creating initial plan with ID: {self.active_plan_id}")

        system_message_content = (
            "You are a planning assistant. Create a concise, actionable plan with clear steps. "
            "Focus on key milestones rather than detailed sub-steps. "
            "Optimize for clarity and efficiency."
        )
        agents_description = []
        for key in self.executor_keys:
            if key in self.agents:
                agents_description.append(
                    {
                        "name": key.upper(),
                        "description": self.agents[key].description,
                    }
                )
        if len(agents_description) > 1:
            # Add description of agents to select
            system_message_content += (
                f"\nNow we have {agents_description} agents. "
                f"The infomation of them are below: {json.dumps(agents_description)}\n"
                "When creating steps in the planning tool, please specify the agent names using the format '[agent_name]'."
            )

        # Create a system message for plan creation
        system_message = Message.system_message(system_message_content)

        # Create a user message with the request
        user_message = Message.user_message(
            f"Create a reasonable plan with clear steps to accomplish the task: {request}"
        )

        # Call LLM with PlanningTool
        response = await self.llm.ask_tool(
            messages=[user_message],
            system_msgs=[system_message],
            tools=[self.planning_tool.to_param()],
            tool_choice=ToolChoice.AUTO,
        )

        # Process tool calls if present
        if response.tool_calls:
            for tool_call in response.tool_calls:
                if tool_call.function.name == "planning":
                    # Parse the arguments
                    args = tool_call.function.arguments
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            logger.error(f"Failed to parse tool arguments: {args}")
                            continue

                    # Ensure plan_id is set correctly and execute the tool
                    args["plan_id"] = self.active_plan_id

                    # Execute the tool via ToolCollection instead of directly
                    result = await self.planning_tool.execute(**args)

                    logger.info(f"Plan creation result: {str(result)}")
                    return

        # If execution reached here, create a default plan
        logger.warning("Creating default plan")

        # Create default plan using the ToolCollection
        await self.planning_tool.execute(
            **{
                "command": "create",
                "plan_id": self.active_plan_id,
                "title": f"Plan for: {request[:50]}{'...' if len(request) > 50 else ''}",
                "steps": ["Analyze request", "Execute task", "Verify results"],
            }
        )

    async def _get_current_step_info(self) -> tuple[Optional[int], Optional[dict]]:
        """
        Parse the current plan to identify the first non-completed step's index and info.
        Returns (None, None) if no active step is found.
        """
        if (
            not self.active_plan_id
            or self.active_plan_id not in self.planning_tool.plans
        ):
            logger.error(f"Plan with ID {self.active_plan_id} not found")
            return None, None

        try:
            # Direct access to plan data from planning tool storage
            plan_data = self.planning_tool.plans[self.active_plan_id]
            steps = plan_data.get("steps", [])
            step_statuses = plan_data.get("step_statuses", [])

            # Find first non-completed step
            for i, step in enumerate(steps):
                if i >= len(step_statuses):
                    status = PlanStepStatus.NOT_STARTED.value
                else:
                    status = step_statuses[i]

                if status in PlanStepStatus.get_active_statuses():
                    # Extract step type/category if available
                    step_info = {"text": step}

                    # Try to extract step type from the text (e.g., [SEARCH] or [CODE])
                    import re

                    type_match = re.search(r"\[([A-Z_]+)\]", step)
                    if type_match:
                        step_info["type"] = type_match.group(1).lower()

                    # Mark current step as in_progress
                    try:
                        await self.planning_tool.execute(
                            command="mark_step",
                            plan_id=self.active_plan_id,
                            step_index=i,
                            step_status=PlanStepStatus.IN_PROGRESS.value,
                        )
                    except Exception as e:
                        logger.warning(f"Error marking step as in_progress: {e}")
                        # Update step status directly if needed
                        if i < len(step_statuses):
                            step_statuses[i] = PlanStepStatus.IN_PROGRESS.value
                        else:
                            while len(step_statuses) < i:
                                step_statuses.append(PlanStepStatus.NOT_STARTED.value)
                            step_statuses.append(PlanStepStatus.IN_PROGRESS.value)

                        plan_data["step_statuses"] = step_statuses

                    return i, step_info

            return None, None  # No active step found

        except Exception as e:
            logger.warning(f"Error finding current step index: {e}")
            return None, None

    async def _execute_step(self, executor: BaseAgent, step_info: dict) -> str:
        """Execute the current step with the specified agent using agent.run()."""
        # Prepare context for the agent with current plan status
        plan_status = await self._get_plan_text()
        step_text = step_info.get("text", f"Step {self.current_step_index}")

        # Create a prompt for the agent to execute the current step
        step_prompt = f"""
        CURRENT PLAN STATUS:
        {plan_status}

        YOUR CURRENT TASK:
        You are now working on step {self.current_step_index}: "{step_text}"

        Please only execute this current step using the appropriate tools. When you're done, provide a summary of what you accomplished.
        """

        # Use agent.run() to execute the step
        try:
            step_result = await executor.run(step_prompt)

            # Mark the step as completed after successful execution
            await self._mark_step_completed()

            return step_result
        except Exception as e:
            logger.error(f"Error executing step {self.current_step_index}: {e}")
            return f"Error executing step {self.current_step_index}: {str(e)}"

    async def _mark_step_completed(self) -> None:
        """Mark the current step as completed."""
        if self.current_step_index is None:
            return

        try:
            # Mark the step as completed
            await self.planning_tool.execute(
                command="mark_step",
                plan_id=self.active_plan_id,
                step_index=self.current_step_index,
                step_status=PlanStepStatus.COMPLETED.value,
            )
            logger.info(
                f"Marked step {self.current_step_index} as completed in plan {self.active_plan_id}"
            )
        except Exception as e:
            logger.warning(f"Failed to update plan status: {e}")
            # Update step status directly in planning tool storage
            if self.active_plan_id in self.planning_tool.plans:
                plan_data = self.planning_tool.plans[self.active_plan_id]
                step_statuses = plan_data.get("step_statuses", [])

                # Ensure the step_statuses list is long enough
                while len(step_statuses) <= self.current_step_index:
                    step_statuses.append(PlanStepStatus.NOT_STARTED.value)

                # Update the status
                step_statuses[self.current_step_index] = PlanStepStatus.COMPLETED.value
                plan_data["step_statuses"] = step_statuses

    async def _get_plan_text(self) -> str:
        """Get the current plan as formatted text."""
        try:
            result = await self.planning_tool.execute(
                command="get", plan_id=self.active_plan_id
            )
            return result.output if hasattr(result, "output") else str(result)
        except Exception as e:
            logger.error(f"Error getting plan: {e}")
            return self._generate_plan_text_from_storage()

    def _generate_plan_text_from_storage(self) -> str:
        """Generate plan text directly from storage if the planning tool fails."""
        try:
            if self.active_plan_id not in self.planning_tool.plans:
                return f"Error: Plan with ID {self.active_plan_id} not found"

            plan_data = self.planning_tool.plans[self.active_plan_id]
            title = plan_data.get("title", "Untitled Plan")
            steps = plan_data.get("steps", [])
            step_statuses = plan_data.get("step_statuses", [])
            step_notes = plan_data.get("step_notes", [])

            # Ensure step_statuses and step_notes match the number of steps
            while len(step_statuses) < len(steps):
                step_statuses.append(PlanStepStatus.NOT_STARTED.value)
            while len(step_notes) < len(steps):
                step_notes.append("")

            # Count steps by status
            status_counts = {status: 0 for status in PlanStepStatus.get_all_statuses()}

            for status in step_statuses:
                if status in status_counts:
                    status_counts[status] += 1

            completed = status_counts[PlanStepStatus.COMPLETED.value]
            total = len(steps)
            progress = (completed / total) * 100 if total > 0 else 0

            plan_text = f"Plan: {title} (ID: {self.active_plan_id})\n"
            plan_text += "=" * len(plan_text) + "\n\n"

            plan_text += (
                f"Progress: {completed}/{total} steps completed ({progress:.1f}%)\n"
            )
            plan_text += f"Status: {status_counts[PlanStepStatus.COMPLETED.value]} completed, {status_counts[PlanStepStatus.IN_PROGRESS.value]} in progress, "
            plan_text += f"{status_counts[PlanStepStatus.BLOCKED.value]} blocked, {status_counts[PlanStepStatus.NOT_STARTED.value]} not started\n\n"
            plan_text += "Steps:\n"

            status_marks = PlanStepStatus.get_status_marks()

            for i, (step, status, notes) in enumerate(
                zip(steps, step_statuses, step_notes)
            ):
                # Use status marks to indicate step status
                status_mark = status_marks.get(
                    status, status_marks[PlanStepStatus.NOT_STARTED.value]
                )

                plan_text += f"{i}. {status_mark} {step}\n"
                if notes:
                    plan_text += f"   Notes: {notes}\n"

            return plan_text
        except Exception as e:
            logger.error(f"Error generating plan text from storage: {e}")
            return f"Error: Unable to retrieve plan with ID {self.active_plan_id}"

    async def _finalize_plan(self) -> str:
        """Finalize the plan and provide a summary using the flow's LLM directly."""
        plan_text = await self._get_plan_text()

        # Create a summary using the flow's LLM directly
        try:
            system_message = Message.system_message(
                "You are a planning assistant. Your task is to summarize the completed plan."
            )

            user_message = Message.user_message(
                f"The plan has been completed. Here is the final plan status:\n\n{plan_text}\n\nPlease provide a summary of what was accomplished and any final thoughts."
            )

            response = await self.llm.ask(
                messages=[user_message], system_msgs=[system_message]
            )

            return f"Plan completed:\n\n{response}"
        except Exception as e:
            logger.error(f"Error finalizing plan with LLM: {e}")

            # Fallback to using an agent for the summary
            try:
                agent = self.primary_agent
                summary_prompt = f"""
                The plan has been completed. Here is the final plan status:

                {plan_text}

                Please provide a summary of what was accomplished and any final thoughts.
                """
                summary = await agent.run(summary_prompt)
                return f"Plan completed:\n\n{summary}"
            except Exception as e2:
                logger.error(f"Error finalizing plan with agent: {e2}")
                return "Plan completed. Error generating summary."
