"""Base collector interface for KDP Scout data sources.

All collectors should inherit from BaseCollector to ensure a consistent
interface. This enables plugin-style extensibility — new data sources
can be added by implementing the collect() method.
"""

from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """Abstract base class for data collectors.

    Subclasses implement collect() to fetch data from a specific source.
    The base class provides common patterns for rate limiting, error
    handling, and result normalization.

    Example:
        class MyCollector(BaseCollector):
            name = 'my_source'

            def collect(self, query, **kwargs):
                # fetch data from source
                return [{'keyword': 'example', 'position': 1}]
    """

    name: str = 'base'

    @abstractmethod
    def collect(self, query, **kwargs):
        """Collect data for a given query.

        Args:
            query: The search query or identifier (keyword, ASIN, etc.).
            **kwargs: Source-specific parameters.

        Returns:
            List of result dicts. Structure depends on the collector type.
        """
        pass

    def is_available(self):
        """Check if this collector is properly configured and ready to use.

        Returns:
            True if the collector can operate. Override for collectors
            that require API keys or external services.
        """
        return True

    def __repr__(self):
        available = 'available' if self.is_available() else 'unavailable'
        return f'<{self.__class__.__name__} ({available})>'
