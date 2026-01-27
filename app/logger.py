import sys  # 系统相关功能，用于标准错误输出
from datetime import datetime  # 日期时间处理，用于生成日志文件名

from loguru import logger as _logger  # loguru日志库，提供强大的日志功能

from app.config import PROJECT_ROOT  # 项目根目录路径


_print_level = "INFO"  # 全局变量：控制台打印的日志级别，默认INFO


def define_log_level(print_level="INFO", logfile_level="DEBUG", name: str = None):
    """定义日志级别并配置日志输出

    配置两个日志输出目标：
    1. 控制台输出（stderr）：使用print_level级别
    2. 日志文件：使用logfile_level级别，文件名包含时间戳

    Args:
        print_level (str): 控制台输出的日志级别，默认"INFO"
        logfile_level (str): 日志文件的日志级别，默认"DEBUG"
        name (str, optional): 日志文件名前缀，如果提供则文件名格式为"{name}_{timestamp}.log"

    Returns:
        Logger: 配置好的logger实例
    """
    global _print_level  # 声明使用全局变量
    _print_level = print_level  # 更新全局日志级别

    current_date = datetime.now()  # 获取当前日期时间
    formatted_date = current_date.strftime("%Y%m%d%H%M%S")  # 格式化为YYYYMMDDHHMMSS格式
    log_name = (
        f"{name}_{formatted_date}" if name else formatted_date
    )  # 如果有名称前缀则添加前缀，否则只使用时间戳

    _logger.remove()  # 移除所有现有的日志处理器
    _logger.add(sys.stderr, level=print_level)  # 添加控制台输出处理器（标准错误输出）
    _logger.add(PROJECT_ROOT / f"logs/{log_name}.log", level=logfile_level)  # 添加文件输出处理器
    return _logger  # 返回配置好的logger实例


logger = define_log_level()  # 创建全局logger实例


if __name__ == "__main__":
    logger.info("Starting application")
    logger.debug("Debug message")
    logger.warning("Warning message")
    logger.error("Error message")
    logger.critical("Critical message")

    try:
        raise ValueError("Test error")
    except Exception as e:
        logger.exception(f"An error occurred: {e}")
