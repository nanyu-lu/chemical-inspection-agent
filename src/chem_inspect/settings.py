"""运行时配置。所有密钥与模型名只从 .env / 环境变量进入，代码内不硬编码。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .contracts import NetworkMode
from .paths import app_home, resources_root

DEFAULT_BASE_URL = (
    "https://ws-8cl1ej8elduuovea.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # 千炼（MaaS）网关
    maas_api_key: str = ""
    maas_base_url: str = DEFAULT_BASE_URL

    # 模型（详见 config/models.yaml）
    maas_vision_model: str = "qwen3-vl-plus"
    maas_ocr_model: str = "qwen-vl-ocr"
    maas_text_model: str = "qwen3.8-flash"

    # 运行模式：online | degraded | offline | airgap
    network_mode: NetworkMode = NetworkMode.ONLINE

    # 判定阈值（与 config/hazard_rules.yaml 保持一致）
    conf_drop: float = 0.45
    conf_review: float = 0.75

    # 请求
    request_timeout_s: int = 90
    max_retries: int = 2

    # 后台 worker（DB 任务表轮询）
    worker_enabled: bool = True
    worker_concurrency: int = 2
    worker_poll_interval: float = 1.0

    # 图像/视频
    max_long_side: int = 1280   # 小目标（安全帽）需要足够分辨率，别压太狠
    video_fps: float = 0.5      # 视频抽帧频率（帧/秒）

    # 前端托管（单端口交付：后端直接托管 web/dist）
    serve_web: bool = True
    web_dist: Path = Field(default_factory=lambda: resources_root() / "web" / "dist")
    port: int = 8000

    # 路径：数据写用户目录（打包后可写），配置与前端从资源目录读
    data_dir: Path = Field(default_factory=lambda: app_home() / "data")
    config_dir: Path = Field(default_factory=lambda: resources_root() / "config")

    def model_post_init(self, __context: object, /) -> None:
        # Key 优先级：环境变量/.env（已由 BaseSettings 读入）> 用户目录 config.json
        if not self.maas_api_key:
            from .credentials import load_api_key

            key = load_api_key()
            if key:
                self.maas_api_key = key

    @property
    def has_key(self) -> bool:
        return bool(self.maas_api_key.strip())

    @property
    def masked_key(self) -> str:
        key = self.maas_api_key.strip()
        if len(key) < 12:
            return "***"
        return f"{key[:7]}***{key[-4:]}"

    def require_key(self) -> str:
        if not self.has_key:
            raise RuntimeError(
                "未配置 MAAS_API_KEY。请复制 .env.example 为 .env 并填入密钥。"
            )
        return self.maas_api_key.strip()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
