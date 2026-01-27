import multiprocessing  # 多进程库，用于在独立进程中执行代码以实现超时控制
import sys  # 系统相关功能，用于重定向标准输出
from io import StringIO  # 字符串IO，用于捕获print输出
from typing import Dict  # 类型提示

from app.tool.base import BaseTool  # 工具基类


class PythonExecute(BaseTool):
    """Python代码执行工具类

    用于执行Python代码字符串，支持超时和安全限制。
    使用多进程在独立进程中执行代码，避免阻塞主进程。
    """

    name: str = "python_execute"  # 工具名称
    description: str = "Executes Python code string. Note: Only print outputs are visible, function return values are not captured. Use print statements to see results."  # 工具描述：注意只有print输出可见，函数返回值不会被捕获
    parameters: dict = {
        "type": "object",  # 参数类型为对象
        "properties": {
            "code": {
                "type": "string",  # 代码类型为字符串
                "description": "The Python code to execute.",  # 代码描述
            },
        },
        "required": ["code"],  # 必需参数：code
    }

    def _run_code(self, code: str, result_dict: dict, safe_globals: dict) -> None:
        """在独立进程中运行代码

        重定向标准输出以捕获print输出，执行代码并记录结果。

        Args:
            code: 要执行的Python代码
            result_dict: 结果字典（共享内存），用于返回执行结果
            safe_globals: 安全的全局命名空间
        """
        original_stdout = sys.stdout  # 保存原始标准输出
        try:
            output_buffer = StringIO()  # 创建字符串缓冲区
            sys.stdout = output_buffer  # 重定向标准输出到缓冲区
            exec(code, safe_globals, safe_globals)  # 执行代码，使用安全的全局命名空间
            result_dict["observation"] = output_buffer.getvalue()  # 获取缓冲区内容作为观察结果
            result_dict["success"] = True  # 标记执行成功
        except Exception as e:  # 捕获任何异常
            result_dict["observation"] = str(e)  # 将异常信息作为观察结果
            result_dict["success"] = False  # 标记执行失败
        finally:
            sys.stdout = original_stdout  # 恢复原始标准输出

    async def execute(
        self,
        code: str,
        timeout: int = 5,
    ) -> Dict:
        """执行提供的Python代码，带超时控制

        使用多进程在独立进程中执行代码，如果超时则终止进程。

        Args:
            code: 要执行的Python代码字符串
            timeout: 执行超时时间（秒），默认5秒

        Returns:
            Dict: 包含'observation'（执行输出或错误消息）和'success'（成功状态）的字典
        """

        with multiprocessing.Manager() as manager:  # 使用进程管理器创建共享字典
            result = manager.dict({"observation": "", "success": False})  # 创建共享结果字典
            if isinstance(__builtins__, dict):  # 如果__builtins__是字典
                safe_globals = {"__builtins__": __builtins__}  # 直接使用
            else:  # 如果__builtins__是模块
                safe_globals = {"__builtins__": __builtins__.__dict__.copy()}  # 复制字典
            proc = multiprocessing.Process(  # 创建进程
                target=self._run_code, args=(code, result, safe_globals)  # 设置目标函数和参数
            )
            proc.start()  # 启动进程
            proc.join(timeout)  # 等待进程完成，最多等待timeout秒

            # 超时处理
            if proc.is_alive():  # 如果进程仍在运行（超时）
                proc.terminate()  # 终止进程
                proc.join(1)  # 等待进程终止（最多1秒）
                return {
                    "observation": f"Execution timeout after {timeout} seconds",  # 返回超时消息
                    "success": False,  # 标记为失败
                }
            return dict(result)  # 返回结果字典
