"""插件层：可插拔的功能增强"""
from .base import Plugin  # noqa: F401
from .character_consistency import CharacterConsistencyPlugin  # noqa: F401
from .state_autosave import StateAutoSavePlugin  # noqa: F401
