import logging
import sys
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
    # Исправлен формат даты: %m вместо %м
    formatter = colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors=log_colors,
        reset=True,
        style='%'
    )

    # Используем stdout, чтобы Docker корректно ловил логи
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(formatter)

    # Настраиваем корневой логгер
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Очищаем существующие хендлеры (чтобы не было дублей от uvicorn)
    root_logger.handlers = []
    root_logger.addHandler(handler)

    # Перехватываем логгеры Uvicorn для единого стиля
    for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error"]:
        logger = logging.getLogger(logger_name)
        logger.handlers = [] # Удаляем дефолтные хендлеры uvicorn
        logger.addHandler(handler)
        logger.propagate = False # Чтобы не дублировалось в root
