from typing import Any
from strata_mining_helper.models.model import Model


class Locations(Model):

    URL_ENDPOINT = "/api/public/locations"

    def get_locations(self) -> list[dict]:
        return self._data.get("locations", [])

    def resolve_location(self, query: str) -> tuple[dict | None, list[str]]:
        """
        Resolves a location based on name or slug and returns (matched_location, alternatives).
        """
        locations = self.get_locations()
        return self.find_matches(
            query=query,
            items=locations,
            search_keys=["name", "slug"],
            display_key="name",
            cutoff=0.4
        )

