from asana_mcp.types import AsanaProject, AsanaSection, AsanaTask


def preview_notes(notes: str | None) -> str:
    """Возвращает короткое однострочное превью описания задачи.

    :param notes: Полное описание задачи.
    :return: Обрезанное описание без переносов строк.
    """
    if not notes:
        return ""
    return notes.strip().replace("\n", " ")[:100]


def format_tasks(tasks: list[AsanaTask], heading: str, empty_message: str) -> str:
    """Форматирует список задач в Markdown.

    :param tasks: Список задач Asana.
    :param heading: Заголовок результата.
    :param empty_message: Сообщение для пустого списка.
    :return: Markdown-представление задач.
    """
    if not tasks:
        return empty_message

    output = [f"### {heading}:\n"]
    for task in tasks:
        status = "✅" if task.get("completed") else "📌"
        due = f" (Срок: {task['due_on']})" if task.get("due_on") else ""
        url = f" — [Ссылка]({task['permalink_url']})" if task.get("permalink_url") else ""
        assignee = task.get("assignee") or {}
        assignee_text = f" 👤 _{assignee.get('name', assignee.get('gid', ''))}_" if assignee else ""
        output.append(
            f"{status} **{task.get('name', 'Без названия')}** `[{task['gid']}]`"
            f"{due}{assignee_text}{url}"
        )
        notes = preview_notes(task.get("notes"))
        if notes:
            output.append(f"  └ _Описание: {notes}..._")
    return "\n".join(output)


def format_projects(projects: list[AsanaProject]) -> str:
    """Форматирует список проектов в Markdown.

    :param projects: Список проектов Asana.
    :return: Markdown-представление проектов.
    """
    if not projects:
        return "В этом workspace нет доступных проектов."
    lines = ["### Проекты в вашем workspace:\n"]
    lines.extend(
        f"📋 **{project.get('name', 'Без названия')}** `[{project['gid']}]`" for project in projects
    )
    return "\n".join(lines)


def format_sections(sections: list[AsanaSection]) -> str:
    """Форматирует список секций в Markdown.

    :param sections: Список секций Asana.
    :return: Markdown-представление секций.
    """
    if not sections:
        return "В этом проекте нет секций."
    lines = ["### Секции проекта:\n"]
    lines.extend(
        f"🗂 **{section.get('name', 'Без названия')}** `[{section['gid']}]`" for section in sections
    )
    return "\n".join(lines)
