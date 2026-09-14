"""APatch Studio product edition boundary."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class StudioEdition(StrEnum):
    """The public distribution contains the local OSS client only."""

    OSS = "oss"

    @classmethod
    def parse(cls, value: str | "StudioEdition") -> "StudioEdition":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError as exc:
            raise ValueError("this distribution provides APatch Studio OSS only") from exc


def product_projection(
    edition: StudioEdition, *, execution_intents: bool | None = None,
) -> dict[str, Any]:
    """Return the small human-facing edition capability projection."""

    return {
        "schema": "apatch.studio.product.v1",
        "name": "APatch Studio",
        "edition": edition.value,
        "features": {
            "local_governed_runs": True,
            "recovery": True,
            "evidence": True,
            "full_agent_api": True,
            "execution_intents": bool(execution_intents),
        },
    }
