from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # PwC Internal LLM
    PwC_LLM_URL: str = "https://genai-sharedservice-americas.pwcinternal.com/chat/completions"
    PwC_LLM_API_KEY: str = ""
    PwC_LLM_MODEL: str = "bedrock.anthropic.claude-opus-4-6"

    # 앱 설정
    MAX_FILE_SIZE_MB: int = 50
    TEMP_DIR: str = "./temp"
    JOB_TTL_MINUTES: int = 60

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    @property
    def uploads_dir(self) -> Path:
        return Path(self.TEMP_DIR) / "uploads"

    @property
    def outputs_dir(self) -> Path:
        return Path(self.TEMP_DIR) / "outputs"


settings = Settings()

# 임시 디렉토리 자동 생성
settings.uploads_dir.mkdir(parents=True, exist_ok=True)
settings.outputs_dir.mkdir(parents=True, exist_ok=True)
