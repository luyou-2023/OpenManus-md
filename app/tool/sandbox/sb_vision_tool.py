import base64  # Base64编码库，用于图像编码
import mimetypes  # MIME类型库，用于检测文件类型
import os  # 操作系统接口库
from io import BytesIO  # 字节流IO
from typing import Optional  # 类型提示

from PIL import Image  # PIL图像处理库
from pydantic import Field  # Pydantic字段定义

from app.daytona.tool_base import Sandbox, SandboxToolsBase, ThreadMessage  # Daytona沙箱、沙箱工具基类、线程消息
from app.tool.base import ToolResult  # 工具结果基类


# 最大文件大小（原图10MB，压缩后5MB）
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 最大图像大小：10MB
MAX_COMPRESSED_SIZE = 5 * 1024 * 1024  # 最大压缩后大小：5MB

# 压缩设置
DEFAULT_MAX_WIDTH = 1920  # 默认最大宽度：1920像素
DEFAULT_MAX_HEIGHT = 1080  # 默认最大高度：1080像素
DEFAULT_JPEG_QUALITY = 85  # 默认JPEG质量：85
DEFAULT_PNG_COMPRESS_LEVEL = 6  # 默认PNG压缩级别：6

_VISION_DESCRIPTION = """
A sandbox-based vision tool that allows the agent to read image files inside the sandbox using the see_image action.
* Only the see_image action is supported, with the parameter being the relative path of the image under /workspace.
* The image will be compressed and converted to base64 for use in subsequent context.
* Supported formats: JPG, PNG, GIF, WEBP. Maximum size: 10MB.
"""  # 沙箱视觉工具的描述文本


class SandboxVisionTool(SandboxToolsBase):
    """沙箱视觉工具类

    基于沙箱的视觉工具，允许代理使用see_image操作读取沙箱内的图像文件。
    """
    name: str = "sandbox_vision"  # 工具名称
    description: str = _VISION_DESCRIPTION  # 工具描述
    parameters: dict = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["see_image"],
                "description": "要执行的视觉动作，目前仅支持 see_image",
            },
            "file_path": {
                "type": "string",
                "description": "图片在 /workspace 下的相对路径，如 'screenshots/image.png'",
            },
        },
        "required": ["action", "file_path"],
        "dependencies": {"see_image": ["file_path"]},
    }

    # def __init__(self, project_id: str, thread_id: str, thread_manager: ThreadManager):
    #     super().__init__(project_id=project_id, thread_manager=thread_manager)
    #     self.thread_id = thread_id
    #     self.thread_manager = thread_manager

    vision_message: Optional[ThreadMessage] = Field(default=None, exclude=True)

    def __init__(
        self, sandbox: Optional[Sandbox] = None, thread_id: Optional[str] = None, **data
    ):
        """Initialize with optional sandbox and thread_id."""
        super().__init__(**data)
        if sandbox is not None:
            self._sandbox = sandbox

    def compress_image(self, image_bytes: bytes, mime_type: str, file_path: str):
        """压缩图片，保持合理质量。"""
        try:
            img = Image.open(BytesIO(image_bytes))
            if img.mode in ("RGBA", "LA", "P"):
                background = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                background.paste(
                    img, mask=img.split()[-1] if img.mode == "RGBA" else None
                )
                img = background
            width, height = img.size
            if width > DEFAULT_MAX_WIDTH or height > DEFAULT_MAX_HEIGHT:
                ratio = min(DEFAULT_MAX_WIDTH / width, DEFAULT_MAX_HEIGHT / height)
                new_width = int(width * ratio)
                new_height = int(height * ratio)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            output = BytesIO()
            if mime_type == "image/gif":
                img.save(output, format="GIF", optimize=True)
                output_mime = "image/gif"
            elif mime_type == "image/png":
                img.save(
                    output,
                    format="PNG",
                    optimize=True,
                    compress_level=DEFAULT_PNG_COMPRESS_LEVEL,
                )
                output_mime = "image/png"
            else:
                img.save(
                    output, format="JPEG", quality=DEFAULT_JPEG_QUALITY, optimize=True
                )
                output_mime = "image/jpeg"
            compressed_bytes = output.getvalue()
            return compressed_bytes, output_mime
        except Exception:
            return image_bytes, mime_type

    async def execute(
        self, action: str, file_path: Optional[str] = None, **kwargs
    ) -> ToolResult:
        """
        执行视觉动作，目前仅支持 see_image。
        参数：
            action: 必须为 'see_image'
            file_path: 图片相对路径
        """
        if action != "see_image":
            return self.fail_response(f"未知的视觉动作: {action}")
        if not file_path:
            return self.fail_response("file_path 参数不能为空")
        try:
            await self._ensure_sandbox()
            cleaned_path = self.clean_path(file_path)
            full_path = f"{self.workspace_path}/{cleaned_path}"
            try:
                file_info = self.sandbox.fs.get_file_info(full_path)
                if file_info.is_dir:
                    return self.fail_response(f"路径 '{cleaned_path}' 是目录，不是图片文件。")
            except Exception:
                return self.fail_response(f"图片文件未找到: '{cleaned_path}'")
            if file_info.size > MAX_IMAGE_SIZE:
                return self.fail_response(
                    f"图片文件 '{cleaned_path}' 过大 ({file_info.size / (1024*1024):.2f}MB)，最大允许 {MAX_IMAGE_SIZE / (1024*1024)}MB。"
                )
            try:
                image_bytes = self.sandbox.fs.download_file(full_path)
            except Exception:
                return self.fail_response(f"无法读取图片文件: {cleaned_path}")
            mime_type, _ = mimetypes.guess_type(full_path)
            if not mime_type or not mime_type.startswith("image/"):
                ext = os.path.splitext(cleaned_path)[1].lower()
                if ext == ".jpg" or ext == ".jpeg":
                    mime_type = "image/jpeg"
                elif ext == ".png":
                    mime_type = "image/png"
                elif ext == ".gif":
                    mime_type = "image/gif"
                elif ext == ".webp":
                    mime_type = "image/webp"
                else:
                    return self.fail_response(
                        f"不支持或未知的图片格式: '{cleaned_path}'。支持: JPG, PNG, GIF, WEBP。"
                    )
            compressed_bytes, compressed_mime_type = self.compress_image(
                image_bytes, mime_type, cleaned_path
            )
            if len(compressed_bytes) > MAX_COMPRESSED_SIZE:
                return self.fail_response(
                    f"图片文件 '{cleaned_path}' 压缩后仍过大 ({len(compressed_bytes) / (1024*1024):.2f}MB)，最大允许 {MAX_COMPRESSED_SIZE / (1024*1024)}MB。"
                )
            base64_image = base64.b64encode(compressed_bytes).decode("utf-8")
            image_context_data = {
                "mime_type": compressed_mime_type,
                "base64": base64_image,
                "file_path": cleaned_path,
                "original_size": file_info.size,
                "compressed_size": len(compressed_bytes),
            }
            message = ThreadMessage(
                type="image_context", content=image_context_data, is_llm_message=False
            )
            self.vision_message = message
            # return self.success_response(f"成功加载并压缩图片 '{cleaned_path}' (由 {file_info.size / 1024:.1f}KB 压缩到 {len(compressed_bytes) / 1024:.1f}KB)。")
            return ToolResult(
                output=f"成功加载并压缩图片 '{cleaned_path}'",
                base64_image=base64_image,
            )
        except Exception as e:
            return self.fail_response(f"see_image 执行异常: {str(e)}")
