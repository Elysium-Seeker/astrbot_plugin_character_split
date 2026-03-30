from .config import SplitConfig
from .constants import MODE_WORK


class PersonaPromptBuilder:
    def __init__(self, config: SplitConfig):
        self._config = config

    def build(self, mode: str) -> str:
        default_core = (
            "You are the same person in both work and rest modes. "
            "Keep the same values, memory continuity and identity across modes."
        )
        default_work = (
            "WORK augmentation: keep responses concise and structured. "
            "Strengthen capability in task decomposition, priority planning, risk spotting, "
            "decision framing and practical execution suggestions."
        )
        default_rest = (
            "REST augmentation: keep responses warm, empathetic and humanized while staying truthful. "
            "Use a relaxed conversational tone and include emotional support when appropriate."
        )

        core_prompt = str(self._config.get("core_persona_prompt", default_core)).strip() or default_core

        if mode == MODE_WORK:
            mode_prompt = str(self._config.get("work_persona_prompt", default_work)).strip() or default_work
            return f"{core_prompt}\n\n{mode_prompt}"

        mode_prompt = str(self._config.get("rest_persona_prompt", default_rest)).strip() or default_rest
        return f"{core_prompt}\n\n{mode_prompt}"
