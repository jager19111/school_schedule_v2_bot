from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HelpLinksDTO:
    public_help_url: str | None
    author_contact_url: str | None
    donation_url: str | None


@dataclass(frozen=True)
class HelpPageDTO:
    section: str
    role: str | None
    links: HelpLinksDTO


class HelpService:
    """
    Сервис пользовательской справки.

    Не зависит от БД и Telegram API.
    Handler передаёт роль текущего пользователя, если она известна.
    """

    def __init__(
        self,
        *,
        public_help_url: str | None,
        author_contact_url: str | None,
        donation_url: str | None,
    ) -> None:
        self._links = HelpLinksDTO(
            public_help_url=public_help_url or None,
            author_contact_url=author_contact_url or None,
            donation_url=donation_url or None,
        )

    def get_page(
        self,
        *,
        section: str = "main",
        role: str | None = None,
    ) -> HelpPageDTO:
        allowed_sections = {
            "main",
            "child",
            "parent",
            "observer",
            "teacher",
            "family",
            "notifications",
            "extras",
            "privacy",
            "support",
        }

        normalized_section = (
            section
            if section in allowed_sections
            else "main"
        )

        return HelpPageDTO(
            section=normalized_section,
            role=role,
            links=self._links,
        )