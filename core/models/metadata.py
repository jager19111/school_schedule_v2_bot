# core/models/metadata.py
#
# Вынесено из dto.py в рамках P0-рефакторинга.
# SchoolMetadata — это не DTO представления, а доменный объект,
# используемый репозиторием и сервисами.

from dataclasses import dataclass
from typing import Dict, Mapping
from core.models.domain import Class, Teacher, Room

@dataclass(frozen=True, slots=True)
class SchoolMetadata:
    """
    Единый объект метаданных школы (кэшируется в памяти репозитория).

    Используется для расшифровки ID в человекочитаемые названия
    и для логики второй смены.
    """
    classes: Mapping[str, Class]
    groups: Mapping[str, str]
    teachers: Mapping[str, Teacher]
    rooms: dict[str, 'Room']
    class_shift: Mapping[str, Mapping[str, int]]
    second_relative: bool