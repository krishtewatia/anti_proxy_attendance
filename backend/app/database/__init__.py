"""Database package initialization."""

from .mongodb import get_client, close_client, get_database, init_indexes

__all__ = ["get_client", "close_client", "get_database", "init_indexes"]
