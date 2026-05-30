"""Pomodoro-related DTOs."""
from nexusx import DefineSubset, SubsetConfig
from src.models import PomodoroSession


class PomodoroSessionItem(DefineSubset):
    """Pomodoro session DTO."""
    __subset__ = SubsetConfig(kls=PomodoroSession, fields=["id", "started_at", "finished_at", "phase", "duration_seconds", "completed"])
