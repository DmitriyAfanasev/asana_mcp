class AsanaMCPError(Exception):
    """Базовая ошибка Asana MCP-сервера."""


class ConfigurationError(AsanaMCPError):
    """Конфигурация сервера неполна или некорректна."""


class AsanaAPIError(AsanaMCPError):
    """Asana не приняла запрос или вернула неожиданный ответ."""


class AsanaResourceNotFoundError(AsanaAPIError):
    """Запрошенный ресурс не найден в Asana."""
