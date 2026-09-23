import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

class AuditService:
    """
    Сервис для логирования бизнес-событий (смена профиля, изменение настроек).
    Пишет в изолированный файл audit.log.
    """
    def __init__(self, log_dir: str = "logs"):
        self.audit_logger = logging.getLogger("audit")
        self.audit_logger.setLevel(logging.INFO)
        
        # Отключаем всплытие логов в Root Logger (чтобы не дублировалось в app.log)
        self.audit_logger.propagate = False
        
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        
        # Ротация аудита: 10 МБ, храним 10 бэкапов (чтобы была история действий)
        audit_handler = RotatingFileHandler(
            filename=log_path / "audit.log",
            maxBytes=10485760,
            backupCount=10,
            encoding="utf8"
        )
        formatter = logging.Formatter("%(asctime)s - [AUDIT] - %(message)s")
        audit_handler.setFormatter(formatter)
        
        if not self.audit_logger.handlers:
            self.audit_logger.addHandler(audit_handler)

    def log_action(self, user_id: int, action: str, details: str = "") -> None:
        """
        Пример: audit_service.log_action(12345, "CHANGE_CLASS", "Set to 11A")
        """
        msg = f"User={user_id} | Action={action} | Details={details}"
        self.audit_logger.info(msg)