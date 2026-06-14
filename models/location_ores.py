from typing import Any
from strata_mining_helper.models.model import Model


class LocationOres(Model):

    URL_ENDPOINT = "/api/public/location-ores/{location}"

    def get_location_details(self) -> dict:
        return self._data.get("location", {})

    def get_ores_at_location(self) -> list[dict]:
        return self._data.get("ores", [])

