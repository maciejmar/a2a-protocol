"""
Logowanie audytowe A2A — patrz PRD sekcja 21.

Każdy wpis to jedna linia JSON na stdout (czytelne dla docker logs / dowolnego
agregatora logów w środowisku zamkniętym, bez zależności od zewnętrznych usług).
"""
import json
import logging
import sys
import time
from contextlib import contextmanager
from typing import Any, Dict, Optional

_logger = logging.getLogger("a2a")
if not _logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(handler)
    _logger.setLevel(logging.INFO)
    _logger.propagate = False


def audit_log(**fields: Any) -> None:
    """Pisze jedną linię JSON z polami audytowymi (request_id, task_id, tenant_id, ...)."""
    _logger.info(json.dumps(fields, default=str, ensure_ascii=False))


@contextmanager
def audit_timer(**fields: Any):
    """Mierzy czas trwania operacji i dopisuje duration_ms + error_code (jeśli wyjątek)."""
    start = time.monotonic()
    error_code: Optional[str] = None
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - chcemy zalogować każdy błąd audytowo
        error_code = getattr(exc, "code", "INTERNAL_ERROR")
        raise
    finally:
        duration_ms = round((time.monotonic() - start) * 1000, 2)
        audit_log(duration_ms=duration_ms, error_code=error_code, **fields)
