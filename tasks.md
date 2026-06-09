# AgentIQ Development Tasks

## Task Workflow
Follow the `.claude/commands/task.md` format for focused development:

Before starting, confirm:
1. Which single file will be modified or created?
2. Which single function is being added or changed?
3. Does a plan exist? If the task touches more than 2 files, enter plan mode first.

Then implement only that. Do not create new files unless the task explicitly requires it.
Do not modify files outside the stated scope.
When done, run: ruff check . && mypy . --strict && pytest tests/unit/ -q
Report: file changed, function written, tests passing yes/no.

## Completed Tasks
- ✅ **db/queries.py**: Created 6 analytics query functions (get_session_volume, get_top_intents, get_top_workflow_paths, get_dropoff_by_step, get_tool_usage, get_quality_by_intent)

## Pending Tasks
(Add new tasks here following the single-file task format)