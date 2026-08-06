"""External material ingestion and retrieval for report generation."""

from .client import EXTERNAL_LIBRARIES

__all__ = [
    "EXTERNAL_LIBRARIES",
    "debug_ingest_external_library",
    "initial_ingest_all_external_libraries",
    "initial_ingest_external_library",
    "retrieve_external_rag",
    "update_all_external_libraries",
    "update_external_library",
]


def __getattr__(name):
    if name in {
        "debug_ingest_external_library",
        "initial_ingest_all_external_libraries",
        "initial_ingest_external_library",
        "update_all_external_libraries",
        "update_external_library",
    }:
        from . import ingestion

        return getattr(ingestion, name)
    if name == "retrieve_external_rag":
        from . import retriever

        return getattr(retriever, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
