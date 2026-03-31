import re

with open("main.py", "r", encoding="utf-8") as f:
    text = f.read()

# 1. Update imports
text = re.sub(
    r'from \.core import \((.*?)\)',
    r'from .core import (\1)\n    from .core.memory_manager import MemoryManager',
    text,
    flags=re.DOTALL
)

text = re.sub(
    r'from core import \(  # type: ignore\n(.*?)\)',
    r'from core import (  # type: ignore\n\1)\n    from core.memory_manager import MemoryManager  # type: ignore',
    text,
    flags=re.DOTALL
)

# 2. Update __init__
text = re.sub(
    r'self\._conversation_splitter = ConversationSplitter\(self\._state_store, logger\).*?self\._mode_dirty_runtime: Dict\[str, Dict\[str, bool\]\] = \{\}',
    r'''self._conversation_splitter = ConversationSplitter(self._state_store, logger)
        from astrbot.api.star import StarTools
        self._memory_manager = MemoryManager(StarTools.get_data_dir(), logger)
        self._mode_dirty_runtime: Dict[str, Dict[str, bool]] = {}''',
    text,
    flags=re.DOTALL
)

text = re.sub(
    r'@register\("character_split", "Elysium-Seeker", "Split work/rest dialog for mnemosyne memory backend", "1.0.1"\)',
    r'@register("character_split", "Elysium-Seeker", "Split work/rest dialog & auto-memory extraction", "1.1.0")',
    text
)

# Replace mnemosyne methods with memory manager methods
text = re.sub(
    r'mnemosyne_available = await self\._is_mnemosyne_available\(\)\n\s+require_backend.*?backend_state\)",',
    r'split_state = "enabled"\n            text = (\n                f"mode: {mode} ({source})\\n"\n                f"split_state: {split_state}\\n"',
    text,
    flags=re.DOTALL
)

with open("main.py", "w", encoding="utf-8") as f:
    f.write(text)
