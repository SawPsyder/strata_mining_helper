from typing import Any

from strata_mining_helper.models.model import Model


class OreLocations(Model):

    URL_ENDPOINT    = "/api/public/ore-locations/{ore}"

    FILTER_OPTIONS_CATEGORY = ['ship', 'fps', 'ground_vehicle']

    def get_ore_locations(self) -> dict:
        ore_locations = self._data.get("results", {})
        return ore_locations

    def get_tier_legend(self) -> dict:
        tier_legend = self._data.get("tierLegend", {})
        return tier_legend