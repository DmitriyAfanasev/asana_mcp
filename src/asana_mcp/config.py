import os
from dataclasses import dataclass
from typing import Final

from asana_mcp.errors import ConfigurationError

ASANA_BASE_URL: Final = "https://app.asana.com/api/1.0"
MCP_SERVER_NAME: Final = "AsanaIntegrationServer"
DEFAULT_DONE_SECTION_NAME: Final = "Готово. На проверке"
DEFAULT_IN_PROGRESS_SECTION_NAME: Final = "В работе"
COMPLETED_TASKS_START_DATE: Final = "2020-01-01T00:00:00.000Z"
DEFAULT_REQUEST_TIMEOUT_SECONDS: Final = 15.0
DEFAULT_CONNECT_TIMEOUT_SECONDS: Final = 15.0


@dataclass(frozen=True, slots=True)
class HTTPHeaders:
    """Заголовки, которые используются для запросов к Asana."""

    authorization: str
    accept: str = "application/json"

    def as_mapping(self) -> dict[str, str]:
        """Возвращает заголовки в формате, который принимает httpx."""
        return {"Authorization": self.authorization, "Accept": self.accept}


@dataclass(frozen=True, slots=True)
class Settings:
    """Настройки запуска MCP-сервера."""

    asana_pat: str
    asana_base_url: str = ASANA_BASE_URL
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS

    @classmethod
    def from_environment(cls) -> "Settings":
        """Загружает настройки из переменных окружения."""
        token = os.getenv("ASANA_PAT")
        if not token:
            raise ConfigurationError("ASANA_PAT environment variable is missing")
        return cls(asana_pat=token)

    def headers(self) -> HTTPHeaders:
        """Создаёт авторизационные заголовки для Asana."""
        return HTTPHeaders(authorization=f"Bearer {self.asana_pat}")
