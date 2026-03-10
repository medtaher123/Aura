import logging

logger = logging.getLogger("bdtopo_pipeline")

logger.setLevel(logging.INFO)

logger.addHandler(logging.StreamHandler())

logger.propagate = False

logger.handlers.clear()

formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
handler = logging.StreamHandler()
handler.setFormatter(formatter)
logger.addHandler(handler)

logger.info("BDTOPO pipeline logger initialized")


def get_logger(name: str = "bdtopo_pipeline") -> logging.Logger:
    return logger.getChild(name)
