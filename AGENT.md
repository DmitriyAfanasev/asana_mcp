# Agent Instructions

These instructions apply to the whole repository.

## Project Context

- This repository contains an MCP server that exposes Asana operations through
  tools and communicates with the Asana HTTP API.
- Keep the MCP layer small. Tool functions should validate tool arguments,
  call an application/service operation, and return a clear tool result.
- Keep HTTP details, Asana response parsing, formatting, and business rules out
  of MCP tool functions whenever practical.
- Preserve the existing user-facing language: MCP tool names and API-facing
  identifiers are English, while user-facing messages and docstrings may remain
  in Russian.

## General Workflow

- Read the relevant code before changing it and inspect the current worktree
  with `git status --short` before editing.
- Keep changes focused on the requested cleanup or behavior. Do not rewrite
  unrelated code or remove user changes.
- Prefer `rg` and `rg --files` for searching.
- Use `apply_patch` for manual file edits. Do not create files with shell
  redirection, `cat`, or ad-hoc scripts.
- Do not add generated files, local environment files, IDE metadata, caches, or
  secrets to the repository.
- Run the narrowest relevant checks after each meaningful change. If a check
  cannot be run, state that explicitly in the handoff.

## Python Style and Types

- Target Python 3.13 and use native generic type syntax such as `list[str]`,
  `dict[str, Any]`, and `str | None`.
- Add explicit return types to functions and methods.
- Prefer precise domain types over anonymous containers:
  - Use `TypedDict` for JSON-shaped data crossing a boundary.
  - Use frozen dataclasses for internal value objects and immutable command or
    result data.
  - Use `Enum` or `Literal` for a closed set of statuses or modes.
  - Use `NewType` or small value objects for identifiers when mixing different
    identifiers could cause a bug.
- Do not expose `dict[str, str]`, `dict[str, Any]`, or `Any` from public
  application APIs when the shape is known. For example, use a named
  `HTTPHeaders`, `AsanaTask`, `TaskOperationResult`, or equivalent type.
- Keep `Any` at untyped external boundaries only. Parse and validate external
  JSON immediately into typed objects before using it in the application layer.
- Do not use `object` as a substitute for a real type. Use a specific union,
  `TypedDict`, dataclass, `Protocol`, or a deliberately local `Any`.
- Prefer immutable values and pure functions for formatting, mapping, and
  normalization logic.
- Avoid clever comprehensions or overly compressed expressions when a named
  helper makes the intent easier to read.

## Naming and Readability

- Choose names that describe the domain action or data shape, not the
  implementation detail. Prefer `resolve_current_user` over `get_data` and
  `AsanaTaskSummary` over `TaskDict`.
- Use action-oriented names for operations (`create_task`,
  `move_task_to_section`) and noun-oriented names for data and adapters
  (`AsanaClient`, `TaskResponse`, `HTTPHeaders`).
- Avoid abbreviations unless they are established in the Asana API, such as
  `gid`, `URL`, or `HTTP`.
- Keep functions short and cohesive. Extract a helper when a function has more
  than one reason to change, mixes I/O with formatting, or hides a meaningful
  domain decision.
- Prefer one obvious control flow over deeply nested branches. Use early
  returns for expected cases and named variables for important intermediate
  values.

## Modules and Architecture

- Do not grow the root `server.py` into a second application layer. New code
  should be placed in small modules with one clear responsibility.
- Aim for a structure similar to:

  ```text
  src/
    app.py                 # MCP server construction and startup
    config.py              # environment-backed configuration
    errors.py              # project-specific exceptions
    types.py               # shared aliases, TypedDicts, enums, value objects
    asana/
      client.py            # HTTP transport and endpoint calls
      models.py            # typed Asana API models
      mappers.py           # external JSON -> internal types
    tools/
      tasks.py             # task-related MCP tools
      projects.py          # project and section MCP tools
    presentation/
      markdown.py          # user-facing result formatting
  ```

- Adapt the structure to the actual size of the code. Do not create empty
  layers or wrappers merely to follow the diagram.
- Keep dependency direction clear: configuration and infrastructure may be
  imported by application code, but formatting and domain types must not
  depend on MCP registration or HTTP client internals.
- Reuse one configured HTTP client and one Asana adapter where lifecycle and
  testability allow it. Do not duplicate URL construction, headers, timeout,
  error handling, or current-user lookup in every tool.
- Use dependency injection through function parameters or small `Protocol`s
  when it makes unit testing easier; do not introduce a service locator or
  global mutable state.

## Errors and External API Boundaries

- Raise custom exceptions when callers need to distinguish a meaningful
  failure, for example `ConfigurationError`, `AsanaApiError`,
  `ResourceNotFoundError`, or `SectionNotFoundError`.
- Do not create custom exception classes for trivial one-off failures where a
  standard exception already communicates the problem.
- Preserve the original exception as the cause with `raise ... from exc` when
  translating an HTTP, JSON, or configuration error.
- Handle expected Asana responses explicitly. A missing task, missing section,
  invalid configuration, timeout, and unexpected API response should not all
  collapse into a generic `Exception` or an untyped dictionary.
- Do not silently swallow exceptions. Log enough context to diagnose the
  operation, but never log access tokens, authorization headers, or secrets.
- Keep transport errors at the adapter boundary and translate them into
  project-specific errors before they reach MCP tools.

## Comments and Documentation

- Write documentation in docstrings, not in large block comments.
- Public MCP tools, public classes, and non-obvious helpers must have useful
  docstrings describing purpose, parameters, return value, and important
  failure behavior.
- Russian docstrings are allowed and preferred for user-facing MCP tools and
  their parameters. Internal implementation docstrings may also be Russian
  when that matches the surrounding module.
- Comments are allowed only for non-obvious constraints, protocol quirks,
  security considerations, or decisions that cannot be expressed clearly in
  code. Do not keep comments that merely narrate the next line.
- Keep docstrings accurate after refactors. Do not duplicate the same long
  explanation in a docstring, comment, and README.

## MCP Tool Contracts

- Keep tool signatures explicit and stable. Use meaningful parameter names and
  defaults, and validate values at the boundary.
- Return a consistent, typed result shape for machine-readable operations.
  Avoid mixing unrelated result keys or returning arbitrary raw Asana JSON.
- Keep human-readable Markdown formatting in a dedicated presentation helper
  when more than one tool needs it.
- Do not expose credentials, raw response bodies, or internal stack traces in
  tool results.
- When a tool performs multiple external mutations, make the order and partial
  failure behavior explicit in code and documentation.

## Testing and Verification

- Add unit tests for typed mapping, normalization, formatting, validation, and
  custom error behavior without making real network calls.
- Test the Asana adapter separately with mocked transport or a small fake
  client. Verify request method, URL, headers, parameters, payload, and error
  translation.
- Keep a small number of integration tests for MCP wiring and the real API
  contract when credentials and a safe test workspace are available.
- Never require a real token for the default test suite and never commit a
  token or a real `.env` file.
- At minimum, run syntax/import checks and the relevant test subset. Also run
  formatting, linting, and type checking when those tools are configured.

## Change Handoff

- Summarize what changed and why, including any module split or public type
  introduced.
- List verification commands and their result.
- Call out remaining technical debt or assumptions instead of hiding it in a
  broad refactor.
