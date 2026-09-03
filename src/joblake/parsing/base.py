from abc import ABC, abstractmethod

from joblake.parsing.models import ParseContext, ParserOutput


class JobParser(ABC):
    source: str
    version: str

    @property
    def name(self) -> str:
        return self.source

    @abstractmethod
    def parse(
        self,
        html: str,
        context: ParseContext,
    ) -> ParserOutput:
        """Extract one canonical job from one accepted raw HTML object."""
