import os
import sys
import logging
from typing import Any

import httpx

from mcp.server.mcpserver import MCPServer

# Логирование строго в stderr (stdout зарезервирован под JSON-RPC MCP)
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("AsanaMCPServer")

ASANA_PAT = os.getenv("ASANA_PAT")
ASANA_BASE_URL = "https://app.asana.com/api/1.0"

mcp = MCPServer("AsanaIntegrationServer")

def get_headers() -> dict[str, str]:
    if not ASANA_PAT:
        raise ValueError("ASANA_PAT environment variable is missing")
    return {
        "Authorization": f"Bearer {ASANA_PAT}",
        "Accept": "application/json",
    }

# -------------------------------------------------------------------
# Tool 1: Получение моих задач
# -------------------------------------------------------------------
@mcp.tool()
async def get_my_tasks(completed: bool = False) -> str:
    """
    Возвращает список задач, назначенных на текущего пользователя в Asana.

    :param completed: Если True — покажет выполненные задачи, False — только активные.
    """
    async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
        # 1. Получаем ID пользователя и workspace
        me_resp = await client.get(f"{ASANA_BASE_URL}/users/me", headers=get_headers())
        me_resp.raise_for_status()
        user_data = me_resp.json()["data"]

        user_gid = user_data["gid"]
        workspace_gid = user_data["workspaces"][0]["gid"]

        # 2. Запрашиваем задачи
        params = {
            "assignee": user_gid,
            "workspace": workspace_gid,
            "completed_since": "now" if not completed else "2020-01-01T00:00:00.000Z",
            "opt_fields": "name,due_on,completed,notes,permalink_url",
        }
        tasks_resp = await client.get(f"{ASANA_BASE_URL}/tasks", headers=get_headers(), params=params)
        tasks_resp.raise_for_status()

        tasks = tasks_resp.json().get("data", [])

        if not tasks:
            return "У вас нет активных задач в Asana."

        # 3. Форматируем результат в читаемый Markdown
        output = ["### Ваши задачи в Asana:\n"]
        for t in tasks:
            status = "✅" if t.get("completed") else "📌"
            due = f" (Срок: {t['due_on']})" if t.get("due_on") else ""
            url = f" — [Ссылка]({t['permalink_url']})" if t.get("permalink_url") else ""

            output.append(f"{status} **{t['name']}** `[{t['gid']}]`{due}{url}")
            if t.get("notes"):
                # Показываем первые 100 символов описания, если оно есть
                note_preview = t['notes'].strip().replace("\n", " ")[:100]
                output.append(f"  └ _Описание: {note_preview}..._")

        return "\n".join(output)

# -------------------------------------------------------------------
# Tool 2a: Список проектов (досок) в workspace
# -------------------------------------------------------------------
@mcp.tool()
async def list_projects() -> str:
    """
    Возвращает список проектов (досок) в workspace пользователя вместе с их gid.
    gid нужен, чтобы передать его в create_task через project_gid и сделать
    задачу видимой всей команде на доске, а не только вам.
    """
    async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
        me_resp = await client.get(f"{ASANA_BASE_URL}/users/me", headers=get_headers())
        me_resp.raise_for_status()
        workspace_gid = me_resp.json()["data"]["workspaces"][0]["gid"]

        params = {"workspace": workspace_gid, "opt_fields": "name,permalink_url"}
        resp = await client.get(f"{ASANA_BASE_URL}/projects", headers=get_headers(), params=params)
        resp.raise_for_status()

        projects = resp.json().get("data", [])
        if not projects:
            return "В этом workspace нет доступных проектов."

        output = ["### Проекты в вашем workspace:\n"]
        for p in projects:
            output.append(f"📋 **{p['name']}** `[{p['gid']}]`")
        return "\n".join(output)

# -------------------------------------------------------------------
# Tool 2b: Создание новой задачи
# -------------------------------------------------------------------
@mcp.tool()
async def create_task(
    title: str,
    notes: str = "",
    due_on: str | None = None,
    project_gid: str | None = None,
) -> dict[str, Any]:
    """
    Создает новую задачу в Asana и назначает её на текущего пользователя.

    В Asana видимость задачи для других определяется не назначенным
    исполнителем, а тем, в какой проект (доску) она добавлена. Если
    project_gid не передан, задача попадёт только в ваш личный список
    "My Tasks" и другие участники её не увидят. Чтобы задача появилась на
    общей доске проекта, передайте project_gid (его можно узнать через
    list_projects).

    :param title: Название задачи.
    :param notes: Описание/детали задачи.
    :param due_on: Срок выполнения в формате YYYY-MM-DD (необязательно).
    :param project_gid: gid проекта, в который нужно добавить задачу, чтобы
        она была видна остальным участникам проекта (необязательно).
    """
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=15.0),
        trust_env=False
    ) as client:
        # Узнаем workspace пользователя
        me_resp = await client.get(f"{ASANA_BASE_URL}/users/me", headers=get_headers())
        me_resp.raise_for_status()
        user_data = me_resp.json()["data"]
        workspace_gid = user_data["workspaces"][0]["gid"]
        user_gid = user_data["gid"]

        payload = {
            "data": {
                "name": title,
                "notes": notes,
                "assignee": user_gid,
                "workspace": workspace_gid,
            }
        }
        if due_on:
            payload["data"]["due_on"] = due_on
        if project_gid:
            payload["data"]["projects"] = [project_gid]

        resp = await client.post(f"{ASANA_BASE_URL}/tasks", headers=get_headers(), json=payload)
        resp.raise_for_status()

        task_data = resp.json()["data"]
        return {
            "status": "created",
            "gid": task_data["gid"],
            "title": task_data["name"],
            "url": task_data.get("permalink_url"),
            "visible_on_board": bool(project_gid),
        }

# -------------------------------------------------------------------
# Tool 2c: Список секций (колонок доски) проекта
# -------------------------------------------------------------------
@mcp.tool()
async def list_sections(project_gid: str) -> str:
    """
    Возвращает список секций (колонок доски) проекта вместе с их gid.
    Нужен, чтобы узнать, как называется/какой gid у колонки вроде
    "Готово. На проверке", если хотите переносить туда задачи вручную
    через move_task_to_section.

    :param project_gid: gid проекта (доски), можно получить через list_projects.
    """
    async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
        resp = await client.get(
            f"{ASANA_BASE_URL}/projects/{project_gid}/sections",
            headers=get_headers(),
            params={"opt_fields": "name"},
        )
        resp.raise_for_status()

        sections = resp.json().get("data", [])
        if not sections:
            return "В этом проекте нет секций."

        output = ["### Секции проекта:\n"]
        for s in sections:
            output.append(f"🗂 **{s['name']}** `[{s['gid']}]`")
        return "\n".join(output)


async def _find_section_gid(client: httpx.AsyncClient, project_gid: str, section_name: str) -> str | None:
    """Ищет в проекте секцию с указанным именем (без учёта регистра/пробелов) и возвращает её gid."""
    resp = await client.get(
        f"{ASANA_BASE_URL}/projects/{project_gid}/sections",
        headers=get_headers(),
        params={"opt_fields": "name"},
    )
    resp.raise_for_status()

    target = section_name.strip().casefold()
    for section in resp.json().get("data", []):
        if section["name"].strip().casefold() == target:
            return section["gid"]
    return None

# -------------------------------------------------------------------
# Tool: Перенос задачи в другую секцию доски
# -------------------------------------------------------------------
@mcp.tool()
async def move_task_to_section(task_gid: str, section_name: str, project_gid: str | None = None) -> dict[str, Any]:
    """
    Переносит задачу в указанную секцию (колонку) доски по её названию.

    Если project_gid не передан, используется первый проект, в который
    добавлена задача.

    :param task_gid: gid задачи.
    :param section_name: Название секции-колонки, например "Готово. На проверке".
    :param project_gid: gid проекта, в котором искать секцию (необязательно).
    """
    async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
        target_project_gid = project_gid
        if not target_project_gid:
            task_resp = await client.get(
                f"{ASANA_BASE_URL}/tasks/{task_gid}",
                headers=get_headers(),
                params={"opt_fields": "memberships.project.gid"},
            )
            task_resp.raise_for_status()
            memberships = task_resp.json()["data"].get("memberships", [])
            if not memberships:
                return {"status": "no_project", "gid": task_gid}
            target_project_gid = memberships[0]["project"]["gid"]

        section_gid = await _find_section_gid(client, target_project_gid, section_name)
        if not section_gid:
            return {"status": "section_not_found", "gid": task_gid, "section_name": section_name}

        move_resp = await client.post(
            f"{ASANA_BASE_URL}/sections/{section_gid}/addTask",
            headers=get_headers(),
            json={"data": {"task": task_gid}},
        )
        move_resp.raise_for_status()

        logger.info("Task %s moved to section '%s' (%s)", task_gid, section_name, section_gid)
        return {"status": "moved", "gid": task_gid, "section_gid": section_gid, "section_name": section_name}

# -------------------------------------------------------------------
# Tool 3: Удаление задачи
# -------------------------------------------------------------------
@mcp.tool()
async def delete_task(task_gid: str) -> dict[str, Any]:
    """
    Удаляет задачу из Asana по её gid.

    :param task_gid: Идентификатор задачи (gid), полученный, например, из get_my_tasks.
    """
    async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
        resp = await client.delete(f"{ASANA_BASE_URL}/tasks/{task_gid}", headers=get_headers())
        if resp.status_code == 404:
            return {"status": "not_found", "gid": task_gid}
        resp.raise_for_status()

        logger.info("Task %s deleted", task_gid)
        return {"status": "deleted", "gid": task_gid}

# -------------------------------------------------------------------
# Tool 4: Отметить задачу выполненной
# -------------------------------------------------------------------
@mcp.tool()
async def complete_task(
    task_gid: str,
    completed: bool = True,
    done_section_name: str | None = "Готово. На проверке",
) -> dict[str, Any]:
    """
    Отмечает задачу как выполненную (или возвращает в работу).

    Проставить completed=True в Asana — это только галочка "выполнено", она
    сама по себе не двигает карточку между колонками доски (например, из
    "Features" в "Готово. На проверке") — перенос между колонками это смена
    секции задачи, отдельное действие. Поэтому при completed=True этот тул
    дополнительно ищет секцию done_section_name в проекте(ах) задачи и
    переносит её туда.

    :param task_gid: Идентификатор задачи (gid), полученный, например, из get_my_tasks.
    :param completed: True — отметить выполненной, False — снять отметку о выполнении.
    :param done_section_name: Название колонки, куда перенести задачу при
        завершении (по умолчанию "Готово. На проверке"). Передайте None, чтобы
        не переносить задачу между колонками.
    """
    async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
        payload = {"data": {"completed": completed}}
        resp = await client.put(
            f"{ASANA_BASE_URL}/tasks/{task_gid}",
            headers=get_headers(),
            json=payload,
        )
        resp.raise_for_status()

        task_data = resp.json()["data"]
        result = {
            "status": "completed" if completed else "reopened",
            "gid": task_data["gid"],
            "title": task_data["name"],
            "completed": task_data.get("completed", completed),
        }

        if completed and done_section_name:
            task_resp = await client.get(
                f"{ASANA_BASE_URL}/tasks/{task_gid}",
                headers=get_headers(),
                params={"opt_fields": "memberships.project.gid"},
            )
            task_resp.raise_for_status()
            memberships = task_resp.json()["data"].get("memberships", [])

            moved_in_projects = []
            for membership in memberships:
                project_gid = membership["project"]["gid"]
                section_gid = await _find_section_gid(client, project_gid, done_section_name)
                if not section_gid:
                    continue
                move_resp = await client.post(
                    f"{ASANA_BASE_URL}/sections/{section_gid}/addTask",
                    headers=get_headers(),
                    json={"data": {"task": task_gid}},
                )
                move_resp.raise_for_status()
                moved_in_projects.append(project_gid)

            if moved_in_projects:
                result["moved_to_section"] = done_section_name
            else:
                result["moved_to_section"] = None
                logger.warning(
                    "Section '%s' not found in any project of task %s — task stayed in its current column",
                    done_section_name, task_gid,
                )

        logger.info("Task %s completed=%s", task_gid, completed)
        return result

# -------------------------------------------------------------------
# Tool: Задачи проекта/секции с фильтрацией
# -------------------------------------------------------------------
@mcp.tool()
async def list_section_tasks(
    project_gid: str,
    section_name: str | None = None,
    section_gid: str | None = None,
    assignee_gid: str | None = None,
) -> str:
    """
    Возвращает список задач в проекте (или конкретной секции/колонке) с поддержкой фильтрации.

    :param project_gid: gid проекта (можно узнать через list_projects).
    :param section_name: Название секции (например, "Features" или "In Progress"). Если передано, найдет ее gid.
    :param section_gid: Прямой gid секции (если известен). Преобладает над section_name.
    :param assignee_gid: gid исполнителя для фильтрации задач.
           Передайте "me", чтобы показать задачи только текущего пользователя.
    """
    async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
        # 1. Если передано "me" в assignee_gid — получаем gid текущего юзера
        target_assignee = assignee_gid
        if target_assignee == "me":
            me_resp = await client.get(f"{ASANA_BASE_URL}/users/me", headers=get_headers())
            me_resp.raise_for_status()
            target_assignee = me_resp.json()["data"]["gid"]

        # 2. Определяем target_section_gid (если искали по названию)
        target_section_gid = section_gid
        if not target_section_gid and section_name:
            target_section_gid = await _find_section_gid(client, project_gid, section_name)
            if not target_section_gid:
                return f"Секция с названием '{section_name}' не найдена в проекте."

        # 3. Делаем запрос: либо к эндпоинту секции, либо к эндпоинту проекта
        fields = "name,due_on,completed,notes,permalink_url,assignee.name,assignee.gid"
        
        if target_section_gid:
            url = f"{ASANA_BASE_URL}/sections/{target_section_gid}/tasks"
            params = {"opt_fields": fields}
        else:
            url = f"{ASANA_BASE_URL}/projects/{project_gid}/tasks"
            params = {"opt_fields": fields}

        resp = await client.get(url, headers=get_headers(), params=params)
        resp.raise_for_status()
        tasks = resp.json().get("data", [])

        # 4. Если запрашивали весь проект, но передавали assignee_gid — фильтруем на стороне клиенте
        if target_assignee:
            tasks = [
                t for t in tasks 
                if t.get("assignee") and t["assignee"].get("gid") == target_assignee
            ]

        if not tasks:
            return "В данной секции/проекте нет задач, соответствующих фильтрам."

        # 5. Форматируем вывод
        header = f"### Задачи проекта `[{project_gid}]`"
        if target_section_gid:
            header += f" (Секция `[{target_section_gid}]`)"
        
        output = [f"{header}:\n"]
        for t in tasks:
            status = "✅" if t.get("completed") else "📌"
            due = f" (Срок: {t['due_on']})" if t.get("due_on") else ""
            
            assignee_info = ""
            if t.get("assignee"):
                assignee_info = f" 👤 _{t['assignee']['name']}_"

            url_str = f" — [Ссылка]({t['permalink_url']})" if t.get("permalink_url") else ""

            output.append(f"{status} **{t['name']}** `[{t['gid']}]`{due}{assignee_info}{url_str}")
            if t.get("notes"):
                note_preview = t["notes"].strip().replace("\n", " ")[:100]
                output.append(f"  └ _Описание: {note_preview}..._")

        return "\n".join(output)

# -------------------------------------------------------------------
# Tool: Назначение исполнителя на задачу
# -------------------------------------------------------------------
@mcp.tool()
async def assign_task(task_gid: str, assignee_gid: str = "me") -> dict[str, Any]:
    """
    Назначает исполнителя на задачу в Asana.

    :param task_gid: Идентификатор задачи (gid).
    :param assignee_gid: gid пользователя, которому назначается задача.
           Передайте "me", чтобы назначить задачу на себя.
    """
    async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
        target_assignee = assignee_gid
        if target_assignee == "me":
            me_resp = await client.get(f"{ASANA_BASE_URL}/users/me", headers=get_headers())
            me_resp.raise_for_status()
            target_assignee = me_resp.json()["data"]["gid"]

        payload = {"data": {"assignee": target_assignee}}
        resp = await client.put(
            f"{ASANA_BASE_URL}/tasks/{task_gid}",
            headers=get_headers(),
            json=payload,
        )
        resp.raise_for_status()

        task_data = resp.json()["data"]
        assigned_name = task_data.get("assignee", {}).get("name", target_assignee)

        logger.info("Task %s assigned to %s", task_gid, target_assignee)
        return {
            "status": "assigned",
            "gid": task_gid,
            "title": task_data["name"],
            "assignee_gid": target_assignee,
            "assignee_name": assigned_name,
        }

# -------------------------------------------------------------------
# Tool: Взять задачу в работу на себя
# -------------------------------------------------------------------
@mcp.tool()
async def take_task(
    task_gid: str,
    in_progress_section_name: str | None = "В работе",
) -> dict[str, Any]:
    """
    Назначает текущего пользователя исполнителем задачи и опционально
    переносит её в секцию "В работе".

    :param task_gid: Идентификатор задачи (gid).
    :param in_progress_section_name: Название секции (колонки), куда перенести
           задачу при взятии в работу (по умолчанию "В работе"). Передайте None,
           чтобы не менять колонку.
    """
    async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
        # 1. Получаем gid текущего пользователя
        me_resp = await client.get(f"{ASANA_BASE_URL}/users/me", headers=get_headers())
        me_resp.raise_for_status()
        user_data = me_resp.json()["data"]
        user_gid = user_data["gid"]

        # 2. Назначаем исполнителя
        payload = {"data": {"assignee": user_gid}}
        resp = await client.put(
            f"{ASANA_BASE_URL}/tasks/{task_gid}",
            headers=get_headers(),
            json=payload,
        )
        resp.raise_for_status()
        task_data = resp.json()["data"]

        result = {
            "status": "taken",
            "gid": task_gid,
            "title": task_data["name"],
            "assignee_name": user_data.get("name", user_gid),
        }

        # 3. Переносим в секцию "В работе" (если указана)
        if in_progress_section_name:
            task_info_resp = await client.get(
                f"{ASANA_BASE_URL}/tasks/{task_gid}",
                headers=get_headers(),
                params={"opt_fields": "memberships.project.gid"},
            )
            task_info_resp.raise_for_status()
            memberships = task_info_resp.json()["data"].get("memberships", [])

            moved_in_projects = []
            for membership in memberships:
                project_gid = membership["project"]["gid"]
                section_gid = await _find_section_gid(client, project_gid, in_progress_section_name)
                if not section_gid:
                    continue
                move_resp = await client.post(
                    f"{ASANA_BASE_URL}/sections/{section_gid}/addTask",
                    headers=get_headers(),
                    json={"data": {"task": task_gid}},
                )
                move_resp.raise_for_status()
                moved_in_projects.append(project_gid)

            if moved_in_projects:
                result["moved_to_section"] = in_progress_section_name
            else:
                result["moved_to_section"] = None

        logger.info("Task %s taken by user %s", task_gid, user_gid)
        return result

# -------------------------------------------------------------------
# Tool: Создание подзадачи (subtask)
# -------------------------------------------------------------------
@mcp.tool()
async def create_subtask(
    parent_task_gid: str,
    title: str,
    notes: str = "",
    assignee_gid: str | None = "me",
    due_on: str | None = None,
) -> dict[str, Any]:
    """
    Создает подзадачу (subtask) внутри родительской задачи в Asana.

    :param parent_task_gid: gid родительской задачи, к которой добавляется подзадача.
    :param title: Название подзадачи.
    :param notes: Описание/детали подзадачи (необязательно).
    :param assignee_gid: gid исполнителя. По умолчанию "me" (назначить на себя).
           Передайте None, если подзадачу пока не нужно ни на кого назначать.
    :param due_on: Срок выполнения в формате YYYY-MM-DD (необязательно).
    """
    async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
        # 1. Если assignee_gid == "me", узнаем gid текущего пользователя
        target_assignee = assignee_gid
        if target_assignee == "me":
            me_resp = await client.get(f"{ASANA_BASE_URL}/users/me", headers=get_headers())
            me_resp.raise_for_status()
            target_assignee = me_resp.json()["data"]["gid"]

        payload = {
            "data": {
                "name": title,
                "notes": notes,
            }
        }
        if target_assignee:
            payload["data"]["assignee"] = target_assignee
        if due_on:
            payload["data"]["due_on"] = due_on

        # 2. Создаем подзадачу через родительский эндпоинт /tasks/{parent_task_gid}/subtasks
        resp = await client.post(
            f"{ASANA_BASE_URL}/tasks/{parent_task_gid}/subtasks",
            headers=get_headers(),
            json=payload,
        )
        resp.raise_for_status()

        subtask_data = resp.json()["data"]
        logger.info("Subtask %s created under parent %s", subtask_data["gid"], parent_task_gid)

        return {
            "status": "subtask_created",
            "gid": subtask_data["gid"],
            "parent_task_gid": parent_task_gid,
            "title": subtask_data["name"],
            "assignee_gid": target_assignee,
            "url": subtask_data.get("permalink_url"),
        }


if __name__ == "__main__":
    mcp.run(transport="stdio")
