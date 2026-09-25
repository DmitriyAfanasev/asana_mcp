from typing import TypedDict


class UserReference(TypedDict, total=False):
    gid: str
    name: str


class WorkspaceReference(TypedDict):
    gid: str


class Membership(TypedDict):
    project: UserReference


class AsanaUser(TypedDict, total=False):
    gid: str
    name: str
    workspaces: list[WorkspaceReference]


class AsanaTask(TypedDict, total=False):
    gid: str
    name: str
    notes: str
    due_on: str | None
    completed: bool
    permalink_url: str | None
    assignee: UserReference | None
    memberships: list[Membership]


class AsanaProject(TypedDict, total=False):
    gid: str
    name: str
    permalink_url: str | None


class AsanaSection(TypedDict, total=False):
    gid: str
    name: str


class CreatedTaskResult(TypedDict):
    status: str
    gid: str
    title: str
    url: str | None
    visible_on_board: bool


class TaskOperationResult(TypedDict, total=False):
    status: str
    gid: str
    title: str
    url: str | None
    section_gid: str
    section_name: str
    moved_to_section: str | None
    completed: bool
    assignee_gid: str | None
    assignee_name: str
    parent_task_gid: str
