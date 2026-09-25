from collections.abc import Mapping
from typing import Any

import httpx

from asana_mcp.config import COMPLETED_TASKS_START_DATE, Settings
from asana_mcp.errors import AsanaAPIError, AsanaResourceNotFoundError
from asana_mcp.types import AsanaProject, AsanaSection, AsanaTask, AsanaUser

JsonObject = dict[str, Any]


class AsanaClient:
    """Адаптер HTTP API Asana для операций MCP-сервера."""

    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self._http_client = http_client
        self._settings = settings

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json: JsonObject | None = None,
    ) -> JsonObject:
        """Выполняет запрос и переводит ошибки транспорта в ошибки приложения.

        :param method: HTTP-метод запроса.
        :param path: Путь API относительно базового URL Asana.
        :param params: Query-параметры запроса.
        :param json: JSON-тело запроса.
        :return: Распознанный JSON-объект ответа.
        """
        try:
            response = await self._http_client.request(
                method,
                f"{self._settings.asana_base_url}{path}",
                headers=self._settings.headers().as_mapping(),
                params=params,
                json=json,
            )
            if response.status_code == 404:
                raise AsanaResourceNotFoundError(f"Asana resource was not found: {path}")
            response.raise_for_status()
            payload = response.json()
        except AsanaResourceNotFoundError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise AsanaAPIError(f"Asana request failed: {method} {path}") from exc

        if not isinstance(payload, dict):
            raise AsanaAPIError(f"Asana returned a non-object response: {method} {path}")
        return payload

    @classmethod
    def _data(cls, payload: JsonObject) -> Any:
        """Извлекает поле `data` из ответа Asana.

        :param payload: JSON-объект ответа Asana.
        :return: Значение поля `data`.
        """
        if "data" not in payload:
            raise AsanaAPIError("Asana response does not contain a data field")
        return payload["data"]

    @classmethod
    def _resource(cls, payload: JsonObject) -> AsanaTask:
        """Преобразует ответ Asana в типизированную задачу.

        :param payload: JSON-объект ответа Asana.
        :return: Данные задачи.
        """
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("gid"), str):
            raise AsanaAPIError("Asana returned an invalid resource")
        return AsanaTask(**data)

    @classmethod
    def _resource_list(cls, payload: JsonObject) -> list[dict[str, Any]]:
        """Проверяет, что поле `data` содержит список объектов.

        :param payload: JSON-объект ответа Asana.
        :return: Список JSON-объектов ресурсов.
        """
        data = payload.get("data", [])
        if not isinstance(data, list):
            raise AsanaAPIError("Asana returned an invalid resource list")
        resources: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                raise AsanaAPIError("Asana returned an invalid resource list")
            resources.append(item)
        return resources

    async def current_user(self) -> AsanaUser:
        """Возвращает текущего пользователя Asana."""
        data = self._data(await self._request("GET", "/users/me"))
        if not isinstance(data, dict) or not isinstance(data.get("gid"), str):
            raise AsanaAPIError("Asana returned an invalid current user")
        return AsanaUser(**data)

    async def list_tasks_for_user(self, user: AsanaUser, completed: bool) -> list[AsanaTask]:
        """Возвращает задачи текущего пользователя.

        :param user: Текущий пользователь Asana.
        :param completed: Включать ли выполненные задачи.
        :return: Список задач пользователя.
        """
        workspaces = user.get("workspaces", [])
        if not workspaces:
            return []
        payload = await self._request(
            "GET",
            "/tasks",
            params={
                "assignee": user["gid"],
                "workspace": workspaces[0]["gid"],
                "completed_since": COMPLETED_TASKS_START_DATE if completed else "now",
                "opt_fields": "name,due_on,completed,notes,permalink_url",
            },
        )
        return [AsanaTask(**task) for task in self._resource_list(payload)]

    async def list_projects(self, user: AsanaUser) -> list[AsanaProject]:
        """Возвращает проекты первого workspace текущего пользователя.

        :param user: Текущий пользователь Asana.
        :return: Список проектов workspace.
        """
        workspaces = user.get("workspaces", [])
        if not workspaces:
            return []
        payload = await self._request(
            "GET",
            "/projects",
            params={"workspace": workspaces[0]["gid"], "opt_fields": "name,permalink_url"},
        )
        return [AsanaProject(**project) for project in self._resource_list(payload)]

    async def create_task(
        self,
        user: AsanaUser,
        title: str,
        notes: str,
        due_on: str | None,
        project_gid: str | None,
    ) -> AsanaTask:
        """Создаёт задачу и, при необходимости, добавляет её в проект.

        :param user: Пользователь, на которого назначается задача.
        :param title: Название задачи.
        :param notes: Описание задачи.
        :param due_on: Срок выполнения в формате Asana.
        :param project_gid: Идентификатор проекта для добавления задачи.
        :return: Созданная задача.
        """
        workspaces = user.get("workspaces", [])
        if not workspaces:
            raise AsanaAPIError("Current user does not belong to a workspace")
        data: JsonObject = {
            "name": title,
            "notes": notes,
            "assignee": user["gid"],
            "workspace": workspaces[0]["gid"],
        }
        if due_on:
            data["due_on"] = due_on
        if project_gid:
            data["projects"] = [project_gid]
        return self._resource(await self._request("POST", "/tasks", json={"data": data}))

    async def list_sections(self, project_gid: str) -> list[AsanaSection]:
        """Возвращает секции проекта.

        :param project_gid: Идентификатор проекта.
        :return: Список секций проекта.
        """
        payload = await self._request(
            "GET", f"/projects/{project_gid}/sections", params={"opt_fields": "name"}
        )
        return [AsanaSection(**section) for section in self._resource_list(payload)]

    async def task_memberships(self, task_gid: str) -> list[dict[str, Any]]:
        """Возвращает связи задачи с проектами.

        :param task_gid: Идентификатор задачи.
        :return: Список связей задачи с проектами.
        """
        data = self._data(
            await self._request(
                "GET", f"/tasks/{task_gid}", params={"opt_fields": "memberships.project.gid"}
            )
        )
        if not isinstance(data, dict) or not isinstance(data.get("memberships", []), list):
            raise AsanaAPIError("Asana returned invalid task memberships")
        memberships: list[dict[str, Any]] = []
        for membership in data["memberships"]:
            if not isinstance(membership, dict):
                raise AsanaAPIError("Asana returned invalid task memberships")
            memberships.append(membership)
        return memberships

    async def add_task_to_section(self, task_gid: str, section_gid: str) -> None:
        """Добавляет задачу в секцию.

        :param task_gid: Идентификатор задачи.
        :param section_gid: Идентификатор секции.
        """
        await self._request(
            "POST", f"/sections/{section_gid}/addTask", json={"data": {"task": task_gid}}
        )

    async def delete_task(self, task_gid: str) -> None:
        """Удаляет задачу.

        :param task_gid: Идентификатор задачи.
        """
        await self._request("DELETE", f"/tasks/{task_gid}")

    async def update_task(self, task_gid: str, fields: JsonObject) -> AsanaTask:
        """Изменяет поля задачи.

        :param task_gid: Идентификатор задачи.
        :param fields: Поля задачи для обновления.
        :return: Обновлённая задача.
        """
        return self._resource(
            await self._request("PUT", f"/tasks/{task_gid}", json={"data": fields})
        )

    async def list_project_tasks(
        self, project_gid: str, section_gid: str | None
    ) -> list[AsanaTask]:
        """Возвращает задачи проекта или отдельной секции.

        :param project_gid: Идентификатор проекта.
        :param section_gid: Идентификатор секции или None для всего проекта.
        :return: Список задач.
        """
        path = f"/sections/{section_gid}/tasks" if section_gid else f"/projects/{project_gid}/tasks"
        payload = await self._request(
            "GET",
            path,
            params={
                "opt_fields": "name,due_on,completed,notes,permalink_url,assignee.name,assignee.gid"
            },
        )
        return [AsanaTask(**task) for task in self._resource_list(payload)]

    async def create_subtask(
        self,
        parent_task_gid: str,
        title: str,
        notes: str,
        assignee_gid: str | None,
        due_on: str | None,
    ) -> AsanaTask:
        """Создаёт подзадачу.

        :param parent_task_gid: Идентификатор родительской задачи.
        :param title: Название подзадачи.
        :param notes: Описание подзадачи.
        :param assignee_gid: Идентификатор исполнителя.
        :param due_on: Срок выполнения в формате Asana.
        :return: Созданная подзадача.
        """
        data: JsonObject = {"name": title, "notes": notes}
        if assignee_gid:
            data["assignee"] = assignee_gid
        if due_on:
            data["due_on"] = due_on
        return self._resource(
            await self._request("POST", f"/tasks/{parent_task_gid}/subtasks", json={"data": data})
        )
