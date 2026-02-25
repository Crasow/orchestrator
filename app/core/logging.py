import logging
import sys
import colorlog

def setup_logging():
    # Color scheme
    log_colors = {
        'DEBUG': 'cyan',
        'INFO': 'green',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'red,bg_white',
    }
    
    # Log format: COLOR | TIME | LEVEL | NAME | MESSAGE
    formatter = colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors=log_colors,
        reset=True,
        style='%'
    )

    # Use stdout so Docker captures logs correctly
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Clear existing handlers to avoid duplicates from uvicorn
    root_logger.handlers = []
    root_logger.addHandler(handler)

    # Override Uvicorn loggers for consistent formatting
    for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error"]:
        logger = logging.getLogger(logger_name)
        logger.handlers = [] # Удаляем дефолтные хендлеры uvicorn
        logger.addHandler(handler)
        logger.propagate = False # Чтобы не дублировалось в root
