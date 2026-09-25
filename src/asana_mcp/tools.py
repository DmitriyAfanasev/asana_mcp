import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from asana_mcp.client import AsanaClient
from asana_mcp.config import (
    DEFAULT_DONE_SECTION_NAME,
    DEFAULT_IN_PROGRESS_SECTION_NAME,
    Settings,
)
from asana_mcp.errors import AsanaResourceNotFoundError
from asana_mcp.formatting import format_projects, format_sections, format_tasks
from asana_mcp.registry import mcp
from asana_mcp.types import CreatedTaskResult, TaskOperationResult

logger = logging.getLogger(__name__)


@asynccontextmanager
async def client_context() -> AsyncIterator[AsanaClient]:
    """Создаёт клиент Asana с общими настройками таймаутов.

    :return: Асинхронный контекст с клиентом Asana.
    """
    settings = Settings.from_environment()
    timeout = httpx.Timeout(
        settings.request_timeout_seconds,
        connect=settings.connect_timeout_seconds,
    )
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as http_client:
        yield AsanaClient(http_client, settings)


async def resolve_section_gid(
    client: AsanaClient,
    project_gid: str,
    section_name: str,
) -> str | None:
    """Ищет секцию по имени без учёта регистра и внешних пробелов.

    :param client: Клиент Asana.
    :param project_gid: Идентификатор проекта.
    :param section_name: Искомое название секции.
    :return: Идентификатор секции или None, если секция не найдена.
    """
    target_name = section_name.strip().casefold()
    sections = await client.list_sections(project_gid)
    return next(
        (
            section["gid"]
            for section in sections
            if section.get("name", "").strip().casefold() == target_name
        ),
        None,
    )


async def move_task_in_projects(
    client: AsanaClient,
    task_gid: str,
    section_name: str,
    project_gids: list[str],
) -> bool:
    """Переносит задачу в одноимённые секции всех указанных проектов.

    :param client: Клиент Asana.
    :param task_gid: Идентификатор задачи.
    :param section_name: Название целевой секции.
    :param project_gids: Идентификаторы проектов задачи.
    :return: True, если задача была перенесена хотя бы в одну секцию.
    """
    moved = False
    for project_gid in project_gids:
        section_gid = await resolve_section_gid(client, project_gid, section_name)
        if section_gid:
            await client.add_task_to_section(task_gid, section_gid)
            moved = True
    return moved


@mcp.tool()
async def get_my_tasks(completed: bool = False) -> str:
    """Возвращает список задач текущего пользователя в Asana.

    :param completed: Если False, возвращаются только активные задачи. Если True,
        в результат также включаются выполненные задачи.
    :return: Отформатированный список задач.
    """
    async with client_context() as client:
        user = await client.current_user()
        tasks = await client.list_tasks_for_user(user, completed)
    return format_tasks(tasks, "Ваши задачи в Asana", "У вас нет активных задач в Asana.")


@mcp.tool()
async def list_projects() -> str:
    """Возвращает проекты первого workspace текущего пользователя.

    :return: Отформатированный список проектов с их идентификаторами.
    """
    async with client_context() as client:
        projects = await client.list_projects(await client.current_user())
    return format_projects(projects)


@mcp.tool()
async def create_task(
    title: str,
    notes: str = "",
    due_on: str | None = None,
    project_gid: str | None = None,
) -> CreatedTaskResult:
    """Создаёт задачу и назначает её текущему пользователю.

    :param title: Обязательное название задачи.
    :param notes: Подробное описание задачи. Поле необязательное; по умолчанию
        используется пустая строка.
    :param due_on: Дата, до которой задачу нужно выполнить, в формате
        `YYYY-MM-DD`. Это дата без времени и часового пояса. Поле необязательное.
    :param project_gid: Идентификатор проекта, в который нужно добавить задачу.
        Поле необязательное. Если его не передать, задача останется только в
        личном списке задач пользователя и не появится на общей доске проекта.
    :return: Результат создания задачи.
    """
    async with client_context() as client:
        user = await client.current_user()
        task = await client.create_task(user, title, notes, due_on, project_gid)
    return {
        "status": "created",
        "gid": task["gid"],
        "title": task["name"],
        "url": task.get("permalink_url"),
        "visible_on_board": bool(project_gid),
    }


@mcp.tool()
async def list_sections(project_gid: str) -> str:
    """Возвращает секции проекта вместе с их идентификаторами.

    :param project_gid: Обязательный идентификатор проекта, секции которого
        нужно получить. Идентификатор можно узнать через `list_projects`.
    :return: Отформатированный список секций.
    """
    async with client_context() as client:
        sections = await client.list_sections(project_gid)
    return format_sections(sections)


@mcp.tool()
async def move_task_to_section(
    task_gid: str,
    section_name: str,
    project_gid: str | None = None,
) -> TaskOperationResult:
    """Переносит задачу в секцию проекта по названию.

    :param task_gid: Обязательный идентификатор задачи.
    :param section_name: Точное название целевой секции без учёта регистра и
        внешних пробелов, например `В работе`.
    :param project_gid: Идентификатор проекта, в котором нужно искать секцию.
        Поле необязательное. Если его не передать, используется первый проект,
        связанный с задачей.
    :return: Результат переноса задачи.
    """
    async with client_context() as client:
        project_gids = (
            [project_gid]
            if project_gid
            else [
                membership["project"]["gid"]
                for membership in await client.task_memberships(task_gid)
            ]
        )
        if not project_gids:
            return {"status": "no_project", "gid": task_gid}
        section_gid = await resolve_section_gid(client, project_gids[0], section_name)
        if not section_gid:
            return {"status": "section_not_found", "gid": task_gid, "section_name": section_name}
        await client.add_task_to_section(task_gid, section_gid)
    logger.info("Task %s moved to section %s", task_gid, section_name)
    return {
        "status": "moved",
        "gid": task_gid,
        "section_gid": section_gid,
        "section_name": section_name,
    }


@mcp.tool()
async def delete_task(task_gid: str) -> TaskOperationResult:
    """Удаляет задачу из Asana.

    :param task_gid: Обязательный идентификатор задачи, которую нужно удалить.
    :return: Результат удаления задачи.
    """
    async with client_context() as client:
        try:
            await client.delete_task(task_gid)
        except AsanaResourceNotFoundError:
            return {"status": "not_found", "gid": task_gid}
    logger.info("Task %s deleted", task_gid)
    return {"status": "deleted", "gid": task_gid}


@mcp.tool()
async def complete_task(
    task_gid: str,
    completed: bool = True,
    done_section_name: str | None = DEFAULT_DONE_SECTION_NAME,
) -> TaskOperationResult:
    """Отмечает задачу выполненной или возвращает её в работу.

    :param task_gid: Обязательный идентификатор задачи.
    :param completed: Новое состояние задачи. Значение True отмечает задачу
        выполненной, False снимает отметку о выполнении. По умолчанию True.
    :param done_section_name: Название секции, куда нужно перенести задачу после
        завершения. По умолчанию используется секция из конфигурации проекта.
        Передайте None, чтобы изменить только признак выполнения и не менять
        секцию задачи.
    :return: Результат обновления задачи.
    """
    async with client_context() as client:
        task = await client.update_task(task_gid, {"completed": completed})
        result: TaskOperationResult = {
            "status": "completed" if completed else "reopened",
            "gid": task["gid"],
            "title": task["name"],
            "completed": task.get("completed", completed),
        }
        if completed and done_section_name:
            project_gids = [
                membership["project"]["gid"]
                for membership in await client.task_memberships(task_gid)
            ]
            moved = await move_task_in_projects(client, task_gid, done_section_name, project_gids)
            result["moved_to_section"] = done_section_name if moved else None
    logger.info("Task %s completed=%s", task_gid, completed)
    return result


@mcp.tool()
async def list_section_tasks(
    project_gid: str,
    section_name: str | None = None,
    section_gid: str | None = None,
    assignee_gid: str | None = None,
) -> str:
    """Возвращает задачи проекта или секции с фильтрацией по исполнителю.

    :param project_gid: Обязательный идентификатор проекта.
    :param section_name: Название секции, задачи которой нужно получить. Поле
        необязательное; если не задано, возвращаются задачи всего проекта.
    :param section_gid: Идентификатор секции, если он уже известен. Имеет
        приоритет над `section_name`.
    :param assignee_gid: Идентификатор исполнителя для фильтрации. Специальное
        значение `me` означает текущего пользователя. Поле необязательное.
    :return: Отформатированный список задач.
    """
    async with client_context() as client:
        target_section_gid = section_gid
        if not target_section_gid and section_name:
            target_section_gid = await resolve_section_gid(client, project_gid, section_name)
            if not target_section_gid:
                return f"Секция с названием '{section_name}' не найдена в проекте."
        target_assignee = assignee_gid
        if target_assignee == "me":
            target_assignee = (await client.current_user())["gid"]
        tasks = await client.list_project_tasks(project_gid, target_section_gid)
    if target_assignee:
        tasks = [
            task for task in tasks if (task.get("assignee") or {}).get("gid") == target_assignee
        ]
    heading = f"Задачи проекта `[{project_gid}]`"
    if target_section_gid:
        heading += f" (Секция `[{target_section_gid}]`)"
    return format_tasks(
        tasks, heading, "В данной секции/проекте нет задач, соответствующих фильтрам."
    )


@mcp.tool()
async def assign_task(task_gid: str, assignee_gid: str = "me") -> TaskOperationResult:
    """Назначает исполнителя на задачу.

    :param task_gid: Обязательный идентификатор задачи.
    :param assignee_gid: Идентификатор пользователя, которому назначается
        задача. Специальное значение `me` назначает задачу текущему пользователю.
        По умолчанию используется `me`.
    :return: Результат назначения исполнителя.
    """
    async with client_context() as client:
        target_assignee = (
            (await client.current_user())["gid"] if assignee_gid == "me" else assignee_gid
        )
        task = await client.update_task(task_gid, {"assignee": target_assignee})
    assignee = task.get("assignee") or {}
    return {
        "status": "assigned",
        "gid": task_gid,
        "title": task["name"],
        "assignee_gid": target_assignee,
        "assignee_name": assignee.get("name", target_assignee),
    }


@mcp.tool()
async def take_task(
    task_gid: str,
    in_progress_section_name: str | None = DEFAULT_IN_PROGRESS_SECTION_NAME,
) -> TaskOperationResult:
    """Назначает задачу текущему пользователю и переносит её в работу.

    :param task_gid: Обязательный идентификатор задачи.
    :param in_progress_section_name: Название секции, куда нужно перенести
        задачу после назначения. По умолчанию используется секция из
        конфигурации проекта. Передайте None, чтобы не менять секцию.
    :return: Результат взятия задачи в работу.
    """
    async with client_context() as client:
        user = await client.current_user()
        task = await client.update_task(task_gid, {"assignee": user["gid"]})
        result: TaskOperationResult = {
            "status": "taken",
            "gid": task_gid,
            "title": task["name"],
            "assignee_name": user.get("name", user["gid"]),
        }
        if in_progress_section_name:
            project_gids = [
                membership["project"]["gid"]
                for membership in await client.task_memberships(task_gid)
            ]
            moved = await move_task_in_projects(
                client, task_gid, in_progress_section_name, project_gids
            )
            result["moved_to_section"] = in_progress_section_name if moved else None
    logger.info("Task %s taken by user %s", task_gid, user["gid"])
    return result


@mcp.tool()
async def create_subtask(
    parent_task_gid: str,
    title: str,
    notes: str = "",
    assignee_gid: str | None = "me",
    due_on: str | None = None,
) -> TaskOperationResult:
    """Создаёт подзадачу внутри родительской задачи.

    :param parent_task_gid: Обязательный идентификатор родительской задачи.
    :param title: Обязательное название подзадачи.
    :param notes: Описание подзадачи. Поле необязательное; по умолчанию
        используется пустая строка.
    :param assignee_gid: Идентификатор исполнителя. Специальное значение `me`
        назначает подзадачу текущему пользователю. Передайте None, чтобы не
        назначать исполнителя. По умолчанию используется `me`.
    :param due_on: Дата, до которой подзадачу нужно выполнить, в формате
        `YYYY-MM-DD`. Это дата без времени и часового пояса. Поле необязательное.
    :return: Результат создания подзадачи.
    """
    async with client_context() as client:
        target_assignee = (
            (await client.current_user())["gid"] if assignee_gid == "me" else assignee_gid
        )
        task = await client.create_subtask(parent_task_gid, title, notes, target_assignee, due_on)
    logger.info("Subtask %s created under parent %s", task["gid"], parent_task_gid)
    return {
        "status": "subtask_created",
        "gid": task["gid"],
        "parent_task_gid": parent_task_gid,
        "title": task["name"],
        "assignee_gid": target_assignee,
        "url": task.get("permalink_url"),
    }
