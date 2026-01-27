import argparse  # 命令行参数解析库
import asyncio  # 异步IO库，用于运行异步主函数

from app.agent.manus import Manus  # 导入Manus代理类
from app.logger import logger  # 导入日志记录器


async def main():
    """主函数：创建并运行Manus代理

    支持两种方式提供提示词：
    1. 通过命令行参数 --prompt
    2. 通过交互式输入

    异常处理：
    - KeyboardInterrupt: 用户中断操作
    - 其他异常：记录错误并退出
    """
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="Run Manus agent with a prompt")  # 创建参数解析器
    parser.add_argument(
        "--prompt", type=str, required=False, help="Input prompt for the agent"  # 添加可选提示词参数
    )
    args = parser.parse_args()  # 解析命令行参数

    # 创建并初始化Manus代理
    agent = await Manus.create()  # 异步创建Manus代理实例
    try:
        # 如果提供了命令行提示词则使用，否则从用户输入获取
        prompt = args.prompt if args.prompt else input("Enter your prompt: ")  # 获取提示词
        if not prompt.strip():  # 检查提示词是否为空
            logger.warning("Empty prompt provided.")  # 记录警告日志
            return  # 提前返回

        logger.warning("Processing your request...")  # 记录处理开始日志
        await agent.run(prompt)  # 运行代理处理提示词
        logger.info("Request processing completed.")  # 记录处理完成日志
    except KeyboardInterrupt:  # 捕获用户中断异常（Ctrl+C）
        logger.warning("Operation interrupted.")  # 记录中断警告
    finally:
        # 确保在退出前清理代理资源
        await agent.cleanup()  # 清理代理资源（关闭浏览器、断开MCP连接等）


if __name__ == "__main__":
    asyncio.run(main())  # 运行异步主函数
