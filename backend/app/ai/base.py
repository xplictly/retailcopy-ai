"""Abstract AI provider interface."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.schemas.schemas import GeneratedContent, GenerationSettings, ProductResponse


class AIProvider(ABC):
    """Base class for all AI providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def model_id(self) -> str | None: ...

    @abstractmethod
    async def is_available(self) -> tuple[bool, str]:
        """Return (is_available, message)."""
        ...

    @abstractmethod
    async def generate(
        self,
        product: ProductResponse,
        settings: GenerationSettings,
    ) -> GeneratedContent:
        """Generate product description content."""
        ...
