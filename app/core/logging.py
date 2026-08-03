"""
app/core/logging.py

This file configures the application's logging pipeline.
In a production-ready system, centralized, structured logging is critical for monitoring,
observability, and debugging. This configuration defines log formatters, handlers,
and log levels depending on the environment (development vs production).
It configures standard output (stdout) for logging, which is the cloud-native standard
for containerized applications (Docker/Kubernetes) as it allows logging agents
to collect logs easily.
"""

import logging
import sys
from logging.config import dictConfig
from app.core.config import settings

# Determine logging level based on environment
LOG_LEVEL = "DEBUG" if settings.ENV == "development" else "INFO"

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "json": {
            "format": '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "file": "%(filename)s", "line": %(lineno)d, "message": "%(message)s"}',
            "datefmt": "%Y-%m-%dT%H:%M:%S%z",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": sys.stdout,
            # Use json formatter in production, standard human-readable formatter in development
            "formatter": "standard" if settings.ENV == "development" else "json",
            "level": LOG_LEVEL,
        },
    },
    "loggers": {
        # Root logger configurations
        "": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": True,
        },
        # FastAPI / Uvicorn internal loggers
        "uvicorn": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn.error": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn.access": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        # SQLAlchemy loggers (set to WARNING to avoid excessive query logging unless debugging)
        "sqlalchemy.engine": {
            "handlers": ["console"],
            "level": "WARNING" if settings.ENV != "development" else "INFO",
            "propagate": False,
        },
    },
}


def setup_logging() -> None:
    """
    Initializes and applies the standard logging configuration dictionary.
    Should be invoked once during application initialization (in main.py).
    """
    dictConfig(LOGGING_CONFIG)
    logger = logging.getLogger(__name__)
    logger.info("Logging successfully initialized in %s mode.", settings.ENV)
