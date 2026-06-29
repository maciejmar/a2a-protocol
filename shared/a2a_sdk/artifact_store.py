"""
Budowanie artefaktów A2A — PRD sekcja 9.4.

Przechowywanie artefaktów (insert/select) leży w TaskManager (task_manager.py).
Ten moduł odpowiada tylko za walidację mime-type i wygodne konstruktory,
żeby handlery skilli nie musiały ręcznie składać obiektu Artifact.
"""
from typing import Any, Dict

from .errors import A2AError
from .schemas import Artifact

ALLOWED_MIME_TYPES = {
    "text/plain",
    "text/markdown",
    "application/json",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/csv",
}


def make_artifact(task_id: str, name: str, content: Any, mime_type: str = "application/json") -> Artifact:
    if mime_type not in ALLOWED_MIME_TYPES:
        raise A2AError(
            "INVALID_MESSAGE",
            f"Niedozwolony mime_type artefaktu: {mime_type!r}",
            data={"allowed": sorted(ALLOWED_MIME_TYPES)},
        )
    return Artifact(task_id=task_id, name=name, type=mime_type, content=content)


def text_artifact(task_id: str, name: str, text: str) -> Artifact:
    return make_artifact(task_id, name, text, mime_type="text/plain")


def json_artifact(task_id: str, name: str, content: Dict[str, Any]) -> Artifact:
    return make_artifact(task_id, name, content, mime_type="application/json")
