class VKUIRenderer:
    @staticmethod
    def render_welcome_new_user() -> str:
        return (
            "👋 Привет! Я — бот школьного расписания.\n\n"
            "Пожалуйста, напишите свой код семьи или выберите роль "
            "(введите 'Ученик' или 'Родитель').\n\n"
            "Полный функционал с кнопками и настройками доступен в нашем Telegram-боте!"
        )

    @staticmethod
    def render_already_registered(role: str) -> str:
        return (
            f"✅ Вы уже зарегистрированы как {role}!\n\n"
            "Напишите 'Расписание', чтобы увидеть свои уроки на сегодня."
        )

    @staticmethod
    def render_echo(text: str) -> str:
        return f"Вы написали: {text}\nК сожалению, я пока понимаю только базовые команды."