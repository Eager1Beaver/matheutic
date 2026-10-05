from abc import ABC, abstractmethod


class AIProvider(ABC):
    @abstractmethod
    async def reply(self, message: str) -> str:
        """Generate a textual reply to a user message."""
        raise NotImplementedError