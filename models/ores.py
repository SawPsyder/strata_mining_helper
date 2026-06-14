from typing import Any

from strata_mining_helper.models.model import Model


class Ores(Model):

    URL_ENDPOINT    = "/api/public/ores"

    FILTER_OPTIONS_CATEGORY = ['ship', 'fps', 'ground_vehicle']

    def get_ores(self, filter_category: str = None, filter_name: str = None) -> tuple[list[Any] | Any, list[Any]]:
        ores = self._data.get("ores", [])
        messages = []
        filter_category = filter_category.lower() if filter_category else None
        filter_name = filter_name.lower() if filter_name else None

        if filter_category:
            if filter_category not in self.FILTER_OPTIONS_CATEGORY:
                ores = []
                messages.append(f"Invalid category filter '{filter_category}'. Valid options are: {', '.join(self.FILTER_OPTIONS_CATEGORY)}.")
            else:
                ores = [ore for ore in ores if ore.get("category") == filter_category]

        if filter_name:
            ore_names = [ore.get("name", []) for ore in ores]
            ores = [ore for ore in ores if ( ore.get("name").lower() == filter_name or ore.get("slug").lower() == filter_name ) ]
            if not ores:
                messages.append(f"Invalid filter 'name' given: '{filter_name}'. Valid options are: {', '.join(ore_names)}.")

        return ores, messages

    def resolve_ore(self, query: str) -> tuple[dict | None, list[str]]:
        """
        Resolves an ore based on name or slug and returns (matched_ore, alternatives).
        """
        ores = self._data.get("ores", [])
        return self.find_matches(
            query=query,
            items=ores,
            search_keys=["slug", "name"],
            display_key="name",
            cutoff=0.4
        )
