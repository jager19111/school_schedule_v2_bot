import os
import logging.config
from pathlib import Path

def setup_logging(log_level: str = "INFO", log_dir: str = "logs") -> None:
    """
    Настраивает структурированное логирование с ротацией файлов.
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            },
            "detailed": {
                "format": "%(asctime)s - %(levelname)s - %(name)s - [%(filename)s:%(lineno)d] - %(message)s"
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": log_level,
                "formatter": "standard",
                "stream": "ext://sys.stdout"
            },
            "file_app": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": log_level,
                "formatter": "standard",
                "filename": os.path.join(log_dir, "app.log"),
                "maxBytes": 10485760,  # 10 MB
                "backupCount": 5,
                "encoding": "utf8"
            },
            "file_error": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "WARNING",
                "formatter": "detailed",
                "filename": os.path.join(log_dir, "errors.log"),
                "maxBytes": 10485760,  # 10 MB
                "backupCount": 5,
                "encoding": "utf8"
            }
        },
        "loggers": {
            "": {  # Root logger (перехватывает всё)
                "handlers": ["console", "file_app", "file_error"],
                "level": log_level,
                "propagate": True
            },
            # Подавляем спам от сторонних библиотек
            "aiogram.event": {
                "level": "WARNING"
            },
            "aiogram.dispatcher": {
                "level": "WARNING"
            },
            "apscheduler": {
                "level": "WARNING"
            }
        }
    }
    
    logging.config.dictConfig(logging_config)