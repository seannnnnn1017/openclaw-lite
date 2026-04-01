import sys
from pathlib import Path


def _load_run_schedule_skill():
    try:
        from agent.scheduling.runtime import run_schedule_skill

        return run_schedule_skill
    except ModuleNotFoundError:
        pass

    try:
        from scheduling.runtime import run_schedule_skill

        return run_schedule_skill
    except ModuleNotFoundError:
        pass

    script_path = Path(__file__).resolve()
    agent_dir = script_path.parents[3]
    project_root = agent_dir.parent

    for candidate in (str(project_root), str(agent_dir)):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)

    try:
        from agent.scheduling.runtime import run_schedule_skill

        return run_schedule_skill
    except ModuleNotFoundError:
        from scheduling.runtime import run_schedule_skill

        return run_schedule_skill


RUN_SCHEDULE_SKILL = _load_run_schedule_skill()


def run(
    action: str,
    name: str = "",
    task_prompt: str = "",
    task: str = "",
    prompt: str = "",
    command: str = "",
    arguments: str = "",
    schedule_type: str = "",
    start_time: str = "",
    start_date: str = "",
    modifier=None,
    days_of_week=None,
    overwrite=False,
    enabled=True,
    include_deleted=False,
    reason: str = "",
    timeout_seconds=None,
    registry_path: str = "",
    **kwargs,
):
    return RUN_SCHEDULE_SKILL(
        action=action,
        name=name,
        task_prompt=task_prompt,
        task=task,
        prompt=prompt,
        command=command,
        arguments=arguments,
        schedule_type=schedule_type,
        start_time=start_time,
        start_date=start_date,
        modifier=modifier,
        days_of_week=days_of_week,
        overwrite=overwrite,
        enabled=enabled,
        include_deleted=include_deleted,
        reason=reason,
        timeout_seconds=timeout_seconds,
        registry_path=registry_path or None,
        **kwargs,
    )
