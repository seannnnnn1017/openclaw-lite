import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from config_loader import Config
from skill_runtime import SkillRuntime


class SkillExecuteRequest(BaseModel):
    skill: str
    action: str
    args: dict = Field(default_factory=dict)


logger = logging.getLogger("openclaw.skill_server")


def create_app():
    if not logger.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )

    app = FastAPI(title="OpenClaw Skill Server")
    config = Config("agent\\config\\config.json")

    def runtime() -> SkillRuntime:
        config.reload_if_changed()
        return SkillRuntime(config.skills)

    @app.get("/skills")
    def list_skills():
        skills = runtime().list_skills()
        logger.info("list_skills count=%s", len(skills))
        return {"skills": skills}

    @app.post("/skills/execute")
    def execute_skill(payload: SkillExecuteRequest):
        logger.info(
            "skill_request skill=%s action=%s args=%s",
            payload.skill,
            payload.action,
            payload.args,
        )
        try:
            result = runtime().execute(
                skill_name=payload.skill,
                action=payload.action,
                args=payload.args,
            )
        except Exception as exc:
            logger.exception(
                "skill_failed skill=%s action=%s args=%s error=%s",
                payload.skill,
                payload.action,
                payload.args,
                exc,
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        logger.info(
            "skill_success skill=%s action=%s result=%s",
            payload.skill,
            payload.action,
            result,
        )
        return {
            "status": "ok",
            "skill": payload.skill,
            "action": payload.action,
            "result": result,
        }

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("skill_server:app", host="127.0.0.1", port=8000, reload=False)
