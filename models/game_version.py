from strata_mining_helper.models.model import Model


class GameVersion(Model):

    URL_BASE        = "https://api.uexcorp.space/2.0"
    URL_ENDPOINT    = "/game_versions"

    def get_version(self) -> str | None:
        return self._data.get("data", {}).get("live", None)