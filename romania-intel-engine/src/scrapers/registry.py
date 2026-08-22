from typing import Dict, Any

class ScraperRegistry:
    def __init__(self):
        self._adapters: Dict[str, Any] = {}

    def register(self, adapter: Any):
        name = getattr(adapter, "name", adapter.__class__.__name__)
        self._adapters[name] = adapter

    def get_all(self) -> Dict[str, Any]:
        return self._adapters

    def get(self, name: str):
        return self._adapters.get(name)

registry = ScraperRegistry()
