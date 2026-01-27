# tool/planning.py
from typing import Dict, List, Literal, Optional  # 类型提示

from app.exceptions import ToolError  # 工具错误异常
from app.tool.base import BaseTool, ToolResult  # 工具基类和结果类


_PLANNING_TOOL_DESCRIPTION = """
A planning tool that allows the agent to create and manage plans for solving complex tasks.
The tool provides functionality for creating plans, updating plan steps, and tracking progress.
"""  # 规划工具的描述文本


class PlanningTool(BaseTool):
    """规划工具类

    允许代理创建和管理用于解决复杂任务的计划。
    提供创建计划、更新计划步骤和跟踪进度的功能。
    """

    name: str = "planning"  # 工具名称
    description: str = _PLANNING_TOOL_DESCRIPTION  # 工具描述
    parameters: dict = {
        "type": "object",  # 参数类型为对象
        "properties": {
            "command": {
                "description": "The command to execute. Available commands: create, update, list, get, set_active, mark_step, delete.",  # 命令描述
                "enum": [
                    "create",  # 创建计划
                    "update",  # 更新计划
                    "list",  # 列出计划
                    "get",  # 获取计划
                    "set_active",  # 设置活动计划
                    "mark_step",  # 标记步骤
                    "delete",  # 删除计划
                ],
                "type": "string",  # 命令类型为字符串
            },
            "plan_id": {
                "description": "Unique identifier for the plan. Required for create, update, set_active, and delete commands. Optional for get and mark_step (uses active plan if not specified).",  # 计划ID描述
                "type": "string",  # 计划ID类型为字符串
            },
            "title": {
                "description": "Title for the plan. Required for create command, optional for update command.",  # 计划标题描述
                "type": "string",  # 标题类型为字符串
            },
            "steps": {
                "description": "List of plan steps. Required for create command, optional for update command.",  # 计划步骤描述
                "type": "array",  # 步骤类型为数组
                "items": {"type": "string"},  # 数组元素类型为字符串
            },
            "step_index": {
                "description": "Index of the step to update (0-based). Required for mark_step command.",  # 步骤索引描述
                "type": "integer",  # 索引类型为整数
            },
            "step_status": {
                "description": "Status to set for a step. Used with mark_step command.",  # 步骤状态描述
                "enum": ["not_started", "in_progress", "completed", "blocked"],  # 状态枚举值
                "type": "string",  # 状态类型为字符串
            },
            "step_notes": {
                "description": "Additional notes for a step. Optional for mark_step command.",  # 步骤备注描述
                "type": "string",  # 备注类型为字符串
            },
        },
        "required": ["command"],  # 必需参数：command
        "additionalProperties": False,  # 不允许额外属性
    }

    plans: dict = {}  # 按plan_id存储计划的字典
    _current_plan_id: Optional[str] = None  # 跟踪当前活动计划ID

    async def execute(
        self,
        *,
        command: Literal[
            "create", "update", "list", "get", "set_active", "mark_step", "delete"
        ],
        plan_id: Optional[str] = None,
        title: Optional[str] = None,
        steps: Optional[List[str]] = None,
        step_index: Optional[int] = None,
        step_status: Optional[
            Literal["not_started", "in_progress", "completed", "blocked"]
        ] = None,
        step_notes: Optional[str] = None,
        **kwargs,
    ):
        """执行规划工具，使用给定的命令和参数

        Args:
            command: 要执行的操作
            plan_id: 计划的唯一标识符
            title: 计划标题（用于create命令）
            steps: 计划步骤列表（用于create命令）
            step_index: 要更新的步骤索引（用于mark_step命令）
            step_status: 要为步骤设置的状态（用于mark_step命令）
            step_notes: 步骤的附加备注（用于mark_step命令）
            **kwargs: 其他参数

        Returns:
            ToolResult: 工具执行结果

        Raises:
            ToolError: 如果命令无效或参数错误
        """

        if command == "create":  # 如果命令是创建
            return self._create_plan(plan_id, title, steps)  # 调用创建计划方法
        elif command == "update":  # 如果命令是更新
            return self._update_plan(plan_id, title, steps)  # 调用更新计划方法
        elif command == "list":  # 如果命令是列出
            return self._list_plans()  # 调用列出计划方法
        elif command == "get":  # 如果命令是获取
            return self._get_plan(plan_id)  # 调用获取计划方法
        elif command == "set_active":  # 如果命令是设置活动
            return self._set_active_plan(plan_id)  # 调用设置活动计划方法
        elif command == "mark_step":  # 如果命令是标记步骤
            return self._mark_step(plan_id, step_index, step_status, step_notes)  # 调用标记步骤方法
        elif command == "delete":  # 如果命令是删除
            return self._delete_plan(plan_id)  # 调用删除计划方法
        else:  # 如果命令无效
            raise ToolError(
                f"Unrecognized command: {command}. Allowed commands are: create, update, list, get, set_active, mark_step, delete"  # 抛出工具错误
            )

    def _create_plan(
        self, plan_id: Optional[str], title: Optional[str], steps: Optional[List[str]]
    ) -> ToolResult:
        """Create a new plan with the given ID, title, and steps."""
        if not plan_id:
            raise ToolError("Parameter `plan_id` is required for command: create")

        if plan_id in self.plans:
            raise ToolError(
                f"A plan with ID '{plan_id}' already exists. Use 'update' to modify existing plans."
            )

        if not title:
            raise ToolError("Parameter `title` is required for command: create")

        if (
            not steps
            or not isinstance(steps, list)
            or not all(isinstance(step, str) for step in steps)
        ):
            raise ToolError(
                "Parameter `steps` must be a non-empty list of strings for command: create"
            )

        # Create a new plan with initialized step statuses
        plan = {
            "plan_id": plan_id,
            "title": title,
            "steps": steps,
            "step_statuses": ["not_started"] * len(steps),
            "step_notes": [""] * len(steps),
        }

        self.plans[plan_id] = plan
        self._current_plan_id = plan_id  # Set as active plan

        return ToolResult(
            output=f"Plan created successfully with ID: {plan_id}\n\n{self._format_plan(plan)}"
        )

    def _update_plan(
        self, plan_id: Optional[str], title: Optional[str], steps: Optional[List[str]]
    ) -> ToolResult:
        """Update an existing plan with new title or steps."""
        if not plan_id:
            raise ToolError("Parameter `plan_id` is required for command: update")

        if plan_id not in self.plans:
            raise ToolError(f"No plan found with ID: {plan_id}")

        plan = self.plans[plan_id]

        if title:
            plan["title"] = title

        if steps:
            if not isinstance(steps, list) or not all(
                isinstance(step, str) for step in steps
            ):
                raise ToolError(
                    "Parameter `steps` must be a list of strings for command: update"
                )

            # Preserve existing step statuses for unchanged steps
            old_steps = plan["steps"]
            old_statuses = plan["step_statuses"]
            old_notes = plan["step_notes"]

            # Create new step statuses and notes
            new_statuses = []
            new_notes = []

            for i, step in enumerate(steps):
                # If the step exists at the same position in old steps, preserve status and notes
                if i < len(old_steps) and step == old_steps[i]:
                    new_statuses.append(old_statuses[i])
                    new_notes.append(old_notes[i])
                else:
                    new_statuses.append("not_started")
                    new_notes.append("")

            plan["steps"] = steps
            plan["step_statuses"] = new_statuses
            plan["step_notes"] = new_notes

        return ToolResult(
            output=f"Plan updated successfully: {plan_id}\n\n{self._format_plan(plan)}"
        )

    def _list_plans(self) -> ToolResult:
        """List all available plans."""
        if not self.plans:
            return ToolResult(
                output="No plans available. Create a plan with the 'create' command."
            )

        output = "Available plans:\n"
        for plan_id, plan in self.plans.items():
            current_marker = " (active)" if plan_id == self._current_plan_id else ""
            completed = sum(
                1 for status in plan["step_statuses"] if status == "completed"
            )
            total = len(plan["steps"])
            progress = f"{completed}/{total} steps completed"
            output += f"• {plan_id}{current_marker}: {plan['title']} - {progress}\n"

        return ToolResult(output=output)

    def _get_plan(self, plan_id: Optional[str]) -> ToolResult:
        """Get details of a specific plan."""
        if not plan_id:
            # If no plan_id is provided, use the current active plan
            if not self._current_plan_id:
                raise ToolError(
                    "No active plan. Please specify a plan_id or set an active plan."
                )
            plan_id = self._current_plan_id

        if plan_id not in self.plans:
            raise ToolError(f"No plan found with ID: {plan_id}")

        plan = self.plans[plan_id]
        return ToolResult(output=self._format_plan(plan))

    def _set_active_plan(self, plan_id: Optional[str]) -> ToolResult:
        """Set a plan as the active plan."""
        if not plan_id:
            raise ToolError("Parameter `plan_id` is required for command: set_active")

        if plan_id not in self.plans:
            raise ToolError(f"No plan found with ID: {plan_id}")

        self._current_plan_id = plan_id
        return ToolResult(
            output=f"Plan '{plan_id}' is now the active plan.\n\n{self._format_plan(self.plans[plan_id])}"
        )

    def _mark_step(
        self,
        plan_id: Optional[str],
        step_index: Optional[int],
        step_status: Optional[str],
        step_notes: Optional[str],
    ) -> ToolResult:
        """Mark a step with a specific status and optional notes."""
        if not plan_id:
            # If no plan_id is provided, use the current active plan
            if not self._current_plan_id:
                raise ToolError(
                    "No active plan. Please specify a plan_id or set an active plan."
                )
            plan_id = self._current_plan_id

        if plan_id not in self.plans:
            raise ToolError(f"No plan found with ID: {plan_id}")

        if step_index is None:
            raise ToolError("Parameter `step_index` is required for command: mark_step")

        plan = self.plans[plan_id]

        if step_index < 0 or step_index >= len(plan["steps"]):
            raise ToolError(
                f"Invalid step_index: {step_index}. Valid indices range from 0 to {len(plan['steps'])-1}."
            )

        if step_status and step_status not in [
            "not_started",
            "in_progress",
            "completed",
            "blocked",
        ]:
            raise ToolError(
                f"Invalid step_status: {step_status}. Valid statuses are: not_started, in_progress, completed, blocked"
            )

        if step_status:
            plan["step_statuses"][step_index] = step_status

        if step_notes:
            plan["step_notes"][step_index] = step_notes

        return ToolResult(
            output=f"Step {step_index} updated in plan '{plan_id}'.\n\n{self._format_plan(plan)}"
        )

    def _delete_plan(self, plan_id: Optional[str]) -> ToolResult:
        """Delete a plan."""
        if not plan_id:
            raise ToolError("Parameter `plan_id` is required for command: delete")

        if plan_id not in self.plans:
            raise ToolError(f"No plan found with ID: {plan_id}")

        del self.plans[plan_id]

        # If the deleted plan was the active plan, clear the active plan
        if self._current_plan_id == plan_id:
            self._current_plan_id = None

        return ToolResult(output=f"Plan '{plan_id}' has been deleted.")

    def _format_plan(self, plan: Dict) -> str:
        """Format a plan for display."""
        output = f"Plan: {plan['title']} (ID: {plan['plan_id']})\n"
        output += "=" * len(output) + "\n\n"

        # Calculate progress statistics
        total_steps = len(plan["steps"])
        completed = sum(1 for status in plan["step_statuses"] if status == "completed")
        in_progress = sum(
            1 for status in plan["step_statuses"] if status == "in_progress"
        )
        blocked = sum(1 for status in plan["step_statuses"] if status == "blocked")
        not_started = sum(
            1 for status in plan["step_statuses"] if status == "not_started"
        )

        output += f"Progress: {completed}/{total_steps} steps completed "
        if total_steps > 0:
            percentage = (completed / total_steps) * 100
            output += f"({percentage:.1f}%)\n"
        else:
            output += "(0%)\n"

        output += f"Status: {completed} completed, {in_progress} in progress, {blocked} blocked, {not_started} not started\n\n"
        output += "Steps:\n"

        # Add each step with its status and notes
        for i, (step, status, notes) in enumerate(
            zip(plan["steps"], plan["step_statuses"], plan["step_notes"])
        ):
            status_symbol = {
                "not_started": "[ ]",
                "in_progress": "[→]",
                "completed": "[✓]",
                "blocked": "[!]",
            }.get(status, "[ ]")

            output += f"{i}. {status_symbol} {step}\n"
            if notes:
                output += f"   Notes: {notes}\n"

        return output
