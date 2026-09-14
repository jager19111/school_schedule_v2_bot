# core/models/metadata.py
#
# Вынесено из dto.py в рамках P0-рефакторинга.
# SchoolMetadata — это не DTO представления, а доменный объект,
# используемый репозиторием и сервисами.

from dataclasses import dataclass
from typing import Dict, Mapping


@dataclass(frozen=True, slots=True)
class SchoolMetadata:
    """
    Единый объект метаданных школы (кэшируется в памяти репозитория).

    Используется для расшифровки ID в человекочитаемые названия
    и для логики второй смены.
    """
    classes: Mapping[str, str]
    groups: Mapping[str, str]
    teachers: Mapping[str, str]
    class_shift: Mapping[str, Mapping[str, int]]
    second_relative: bool