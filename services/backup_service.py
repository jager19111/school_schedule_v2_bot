import os
import zipfile
import logging
from pathlib import Path
import aiosqlite
from aiogram import Bot
from aiogram.types import FSInputFile

from services.time_service import TimeService

logger = logging.getLogger(__name__)

class BackupService:
    def __init__(self, bot: Bot, db_path: str, backup_chat_id: int, time_service: TimeService):
        self.bot = bot
        self.db_path = db_path
        self.backup_chat_id = backup_chat_id
        self.time_service = time_service
        self.backup_dir = Path("backups")
        self.backup_dir.mkdir(exist_ok=True)

    async def run_backup(self) -> None:
        now = self.time_service.get_now_base()
        date_str = now.strftime("%Y-%m-%d_%H-%M")
        backup_db_path = self.backup_dir / f"schedule_{date_str}.db"
        zip_path = self.backup_dir / f"schedule_backup_{date_str}.zip"

        # БЛОК 1: Локальное создание дампа и сжатие (Критический этап)
        try:
            async with aiosqlite.connect(self.db_path) as src_db:
                async with aiosqlite.connect(backup_db_path) as dst_db:
                    await src_db.backup(dst_db)

            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                zipf.write(backup_db_path, arcname=f"schedule_bot_{date_str}.db")

            # Удаляем сырой .db сразу после успешного создания архива
            if backup_db_path.exists():
                os.remove(backup_db_path)
                
            logger.info("Локальная резервная копия успешно создана: %s", zip_path.name)
            
        except Exception as e:
            logger.error("Критическая ошибка при создании локального дампа БД: %s", e, exc_info=True)
            return  # Если архив не создался, отправлять нечего, прерываемся

        # БЛОК 2: Отправка в Telegram (Опциональный этап, изолирован от падений)
        if self.backup_chat_id:
            try:
                document = FSInputFile(path=str(zip_path))
                await self.bot.send_document(
                    chat_id=self.backup_chat_id,
                    document=document,
                    caption=f"📦 Резервная копия БД бота расписания за {now.strftime('%d.%m.%Y %H:%M')}"
                )
                logger.info("Резервная копия отправлена в админ-чат.")
            except Exception as e:
                # Ошибка сети или неверный chat_id не должна ронять сервис
                logger.error("Не удалось отправить бэкап в Telegram. Локальная копия сохранена. Ошибка: %s", e, exc_info=True)
        else:
            logger.info("BACKUP_CHAT_ID не задан. Бэкап сохранен только локально.")

        # БЛОК 3: Ротация старых файлов
        try:
            self._cleanup_old_backups(days_to_keep=7)
        except Exception as e:
            logger.error("Ошибка при ротации старых бэкапов: %s", e, exc_info=True)

    def _cleanup_old_backups(self, days_to_keep: int) -> None:
        now_ts = self.time_service.get_now_base().timestamp()
        for file in self.backup_dir.glob("*.zip"):
            if file.is_file():
                file_age_days = (now_ts - file.stat().st_mtime) / (24 * 3600)
                if file_age_days > days_to_keep:
                    os.remove(file)
                    logger.info("Удален старый бэкап: %s", file.name)