import logging
import colorlog

def setup_logging():
    # Цветовая схема
    log_colors = {
        'DEBUG': 'cyan',
        'INFO': 'green',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'red,bg_white',
    }
    
    # Формат логов: ЦВЕТ | ВРЕМЯ | УРОВЕНЬ | ИМЯ | СООБЩЕНИЕ
    formatter = colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%м-%d %H:%M:%S",
        log_colors=log_colors
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    # Применяем настройки ко всему приложению
    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler],
        force=True # Важно! Перезаписывает настройки uvicorn/python по умолчанию
    )
