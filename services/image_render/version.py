"""Версия данных расписания для ключей кэша постеров.

Semantic-хэш NIKA (ScheduleRepository) меняется только при реальном
изменении расписания — именно он служит «версией» в ключах L1/L2:
новый хэш = новый ключ, точечная инвалидация не нужна, старые записи
умирают по TTL (решение из обсуждения ТЗ v2.2).
"""

from __future__ import annotations

from core.repository.schedule_repository import ScheduleRepository


async def get_schedule_version(schedule_repo: ScheduleRepository) -> str:
    """Короткая строка-версия текущих данных расписания."""
    state = await schedule_repo.get_nika_source_state()
    if state is None or not state.semantic_sha256:
        return "v0"
    return state.semantic_sha256[:8]
