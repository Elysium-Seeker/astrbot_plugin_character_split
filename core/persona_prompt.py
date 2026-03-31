from .config import SplitConfig
from .constants import MODE_WORK


class PersonaPromptBuilder:
    def __init__(self, config: SplitConfig):
        self._config = config

    def build(self, mode: str) -> str:
        default_core = (
            "You maintain a consistent core identity and long-term memory. "
            "Regardless of the context, your foundational personality and recall of past events remain intact. "
            "You adapt your communication style flexibly without becoming a completely different person."
        )
        default_work = (
            "[Current Status: WORK] You are in professional mode. Focus on efficiency, logical structure, and accuracy. "
            "Use bullet points for clarity. Proactively decompose tasks, identify risks, and offer actionable solutions. "
            "Minimize casual chatter and emotional preamble."
        )
        default_rest = (
            "[Current Status: REST] You are in casual mode. Relax your tone and act as a warm, empathetic companion. "
            "Use natural, conversational phrasing. Provide emotional support, appropriate humor, and engaging daily interactions. "
            "Avoid being overly rigid, formal, or pedantic."
        )

        core_prompt = str(self._config.get("core_persona_prompt", default_core)).strip() or default_core

        if mode == MODE_WORK:
            mode_prompt = str(self._config.get("work_persona_prompt", default_work)).strip() or default_work
            return f"{core_prompt}\n\n{mode_prompt}"

        mode_prompt = str(self._config.get("rest_persona_prompt", default_rest)).strip() or default_rest
        return f"{core_prompt}\n\n{mode_prompt}"
