import aiohttp
import json
import logging
import re
from typing import Tuple, Dict, Any, Optional

logger = logging.getLogger(__name__)

class ScheduleFetcher:
    def __init__(self, base_url: str = "https://lyceum.nstu.ru/rasp/", proxy: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.proxy = proxy
        self.headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) ScheduleBot/2.0'}

    async def fetch(self) -> Tuple[str, Dict[str, Any]]:
        """Загружает JS-файл и извлекает JSON объект NIKA[cite: 1, 2]."""
        async with aiohttp.ClientSession(headers=self.headers) as session:
            try:
                # 1. Получаем HTML и ищем JS файл
                async with session.get(f"{self.base_url}/schedule.html", proxy=self.proxy, ssl=False) as resp:
                    resp.raise_for_status()
                    html = await resp.text()

                js_filename_match = re.search(r'src="(nika_data_[^"]+\.js)"', html)
                if not js_filename_match:
                    raise ValueError("Не найден файл nika_data_*.js в HTML")
                
                js_url = f"{self.base_url}/{js_filename_match.group(1)}"

                # 2. Загружаем JS дамп
                async with session.get(js_url, proxy=self.proxy, ssl=False) as resp:
                    resp.raise_for_status()
                    js_content = await resp.text(encoding='utf-8')

                # 3. Извлекаем JSON через балансировщик скобок
                json_dict = self._extract_json_from_js(js_content)
                return js_content, json_dict

            except Exception as e:
                logger.error(f"Ошибка получения расписания: {e}")
                raise

    def _extract_json_from_js(self, js_content: str) -> Dict[str, Any]:
        """Безопасно извлекает JSON из `var NIKA = {...}`[cite: 1, 3]."""
        start_idx = js_content.find("var NIKA=")
        if start_idx == -1:
            start_idx = js_content.find("var NIKA =")
        
        if start_idx == -1:
            raise ValueError("Глобальная переменная NIKA не найдена в JS файле")
            
        json_start = js_content.find("{", start_idx)
        if json_start == -1:
            raise ValueError("Не найдено начало JSON объекта")

        # Балансировка скобок для точного захвата
        bracket_count = 0
        json_end = -1
        for i in range(json_start, len(js_content)):
            if js_content[i] == "{":
                bracket_count += 1
            elif js_content[i] == "}":
                bracket_count -= 1
                if bracket_count == 0:
                    json_end = i + 1
                    break
                    
        if json_end == -1:
            raise ValueError("Не удалось найти конец JSON объекта")

        raw_json = js_content[json_start:json_end]
        try:
            # Очистка неэкранированных символов при необходимости
            return json.loads(raw_json)
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка десериализации JSON: {e}")
            raise