from vkbottle import Keyboard, KeyboardButtonColor, Text

class VKKeyboards:
    @staticmethod
    def get_role_selection() -> str:
        """Клавиатура выбора роли с передачей payload (скрытых данных)."""
        keyboard = Keyboard(one_time=True, inline=False)
        keyboard.add(Text("👨‍👩‍👧 Родитель", payload={"role": "parent"}), color=KeyboardButtonColor.PRIMARY)
        keyboard.row()
        keyboard.add(Text("👶 Ученик", payload={"role": "child"}), color=KeyboardButtonColor.PRIMARY)
        keyboard.row()
        keyboard.add(Text("👁 Наблюдатель", payload={"role": "observer"}), color=KeyboardButtonColor.SECONDARY)
        return keyboard.get_json()