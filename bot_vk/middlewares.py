from vkbottle import BaseMiddleware
from vkbottle.bot import Message

def create_di_middleware(state_dispenser, **services):
    class DependencyInjectionMiddleware(BaseMiddleware[Message]):
        async def pre(self):
            # Прокидываем сервисы и FSM-диспетчер в аргументы хендлеров
            self.send({"state_dispenser": state_dispenser, **services})
            
    return DependencyInjectionMiddleware