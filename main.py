import os
import time
from typing import TYPE_CHECKING
from api.enums import LogSource, LogType
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from skills.skill_base import Skill, tool
from strata_mining_helper.cache_handler import CacheHandler
from strata_mining_helper.models.game_version import GameVersion
from strata_mining_helper.models.ore_locations import OreLocations
from strata_mining_helper.models.ores import Ores
from strata_mining_helper.models.locations import Locations
from strata_mining_helper.models.location_ores import LocationOres

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class StrataMiningHelper(Skill):
    """
    A skill that captures screenshots and uploads to SC-Tools API,
    returning the URL and attaching it to the conversation history as an image.
    """

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)
        self._data_directory = os.path.join(self.get_generated_files_dir(), "cache")
        os.makedirs(self._data_directory, exist_ok=True)
        self._cache_handler = CacheHandler(self._data_directory)
        self._api_key_celd = None
        self._uex_game_version: GameVersion | None = None
        self._celd_ores: Ores | None = None
        self._celd_ore_locations: dict = {}
        self._celd_locations: Locations | None = None
        self._celd_location_ores: dict = {}

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        self._api_key_celd = await self.retrieve_secret(
            "celd",
            errors,
            hint="Get your API key here: https://strata.celd.space/api-keys",
        )
        return errors

    async def secret_changed(self, secrets: dict[str, any]):
        await super().secret_changed(secrets)
        self._api_key_celd = await self.retrieve_secret(
            "celd",
            [],
            hint="Get your API key here: https://strata.celd.space/api-keys",
        )

    async def prepare(self) -> None:
        await super().prepare()

        # check current game version if change happened, we invalidate the complete cache
        self._uex_game_version = GameVersion(self._cache_handler, self.get_api_key_celd)
        cached = self._uex_game_version.load()
        if cached:
            new_game_version = GameVersion(self._cache_handler, self.get_api_key_celd)
            new_game_version.load(use_cache=False)
            if new_game_version.get_version() != self._uex_game_version.get_version():
                cached = False

        self.__prepare_data(cached)

    async def unload(self) -> None:
        await super().unload()

    def get_api_key_celd(self) -> str | None:
        return self._api_key_celd

    def __prepare_data(self, use_cache: bool = True) -> None:
        # get game version
        self._uex_game_version = GameVersion(self._cache_handler, None)
        self._uex_game_version.load(use_cache=use_cache)

        # get ores
        self._celd_ores = Ores(self._cache_handler, self.get_api_key_celd)
        self._celd_ores.load(use_cache=use_cache)

        # get locations list
        self._celd_locations = Locations(self._cache_handler, self.get_api_key_celd)
        self._celd_locations.load(use_cache=use_cache)

    @tool("get_ores", "Query the database of Star Citizen mining ores to get parameters like category, tier, can signature, and instability. You can filter by category ('ship', 'fps', 'ground_vehicle') or search by specific ore_names. Use this for general queries about ore properties or to look up base signature values.")
    def get_ores(self, filter_by_category: str = None, ore_names: list[str] = None) -> str:
        ores, messages = self._celd_ores.get_ores(filter_by_category)
        if messages:
            return "Errors:\n" + "\n".join(messages)

        resolved_ores = []
        unresolved = []
        resolved_mappings = {}

        if ore_names:
            for ore_name in ore_names:
                matched_ore, alternatives = self._celd_ores.resolve_ore(ore_name)
                if matched_ore:
                    if matched_ore in ores:
                        if matched_ore.get("id") not in [r.get("id") for r in resolved_ores]:
                            resolved_ores.append(matched_ore)
                            if ore_name.lower() != matched_ore.get("name", "").lower() and ore_name.lower() != matched_ore.get("slug", "").lower():
                                resolved_mappings[ore_name] = (matched_ore.get("name"), alternatives)
                    else:
                        unresolved.append(f"{ore_name} (Not in category {filter_by_category})")
                else:
                    unresolved.append(ore_name)

            if unresolved:
                suggestions = []
                for u in unresolved:
                    clean_u = u.split(" (")[0]
                    _, alternatives = self._celd_ores.resolve_ore(clean_u)
                    for alt in alternatives:
                        if alt not in suggestions:
                            suggestions.append(alt)
                suggest_str = f" Did you mean: {', '.join(suggestions[:10])}?" if suggestions else ""
                return f"Unresolved: {', '.join(unresolved)}.{suggest_str}"

            ores = resolved_ores

        if not ores:
            return "No ores found."

        category_helpers = {
            'ship': "Mined with ships (space/surfaces)",
            'fps': "Mined on-foot (caves)",
            'ground_vehicle': "Mined with ground vehicles (surfaces)"
        }
        categories = set()
        ore_lines = []
        for ore in ores:
            cat = ore.get("category", "unknown")
            categories.add(cat)
            sig = ore.get("scanSignature", "unknown")
            tier = ore.get("tier", "unknown")
            ore_lines.append(f"- {ore.get('name', 'unknown')} ({cat}, Tier: {tier}, Sig: {sig})")

        text_ores = "Ores:\n" + "\n".join(ore_lines)
        text_category_helpers = "\n\nCategories:\n" + "\n".join([f"- {cat}: {category_helpers[cat]}" for cat in categories if cat in category_helpers])

        note = ""
        if resolved_mappings:
            resolved_lines = []
            for k, (v, alts) in resolved_mappings.items():
                line = f"'{k}' -> '{v}'"
                if alts:
                    line += f" (Alternatives: {', '.join(alts)})"
                resolved_lines.append(line)
            note = f"Resolved: {', '.join(resolved_lines)}\n\n"

        return note + text_ores + text_category_helpers

    @tool('verify_scan_signature', "Resolve which resources are contained inside scanned rock clusters based on a list of scan_signatures. This solves single resources or multi-ore geological combinations (like 'Combo of 2x Copper + 1x Laranite'). Use this when a player scans signatures in-game and wants identification.")
    def verify_scan_signature(self, scan_signatures: list[int]) -> str:
        # Sanitise arguments to support both lists of ints/strings and singular ints/strings
        if isinstance(scan_signatures, (int, float)):
            scan_signatures = [int(scan_signatures)]
        elif isinstance(scan_signatures, str):
            try:
                scan_signatures = [int(x.strip()) for x in scan_signatures.split(",") if x.strip()]
            except ValueError:
                scan_signatures = []
        elif isinstance(scan_signatures, list):
            sanitized = []
            for item in scan_signatures:
                try:
                    sanitized.append(int(item))
                except (ValueError, TypeError):
                    continue
            scan_signatures = sanitized
        else:
            scan_signatures = []

        if not scan_signatures:
            return "Please provide valid scan signatures."

        ores, messages = self._celd_ores.get_ores()
        if messages:
            return "Errors:\n" + "\n".join(messages)
        if not ores:
            return "No ores found."

        return_parts = []
        for sig in scan_signatures:
            matches = []
            for ore in ores:
                signature = ore.get("scanSignature", 0)
                if not signature or signature <= 0:
                    continue
                if sig % signature == 0:
                    multiple = sig // signature
                    if multiple > 0:
                        matches.append((ore, multiple))

            if matches:
                results = []
                for ore, multiple in matches:
                    results.append(
                        f"  * {multiple}x {ore.get('name', 'unknown')} ({ore.get('category', 'unknown')}, Tier: {ore.get('tier', 'unknown')})"
                    )
                return_parts.append(f"Signature {sig}:\n" + "\n".join(results))
            else:
                # Find possible double combination matches (2-ore node clusters)
                combos = []
                valid_ores = [o for o in ores if o.get("scanSignature", 0) > 0]
                for i in range(len(valid_ores)):
                    ore_A = valid_ores[i]
                    sig_A = ore_A["scanSignature"]
                    for j in range(i + 1, len(valid_ores)):  # strictly distinct ores
                        ore_B = valid_ores[j]
                        sig_B = ore_B["scanSignature"]

                        # Loop count_A and count_B up to 5
                        for count_A in range(1, 6):
                            for count_B in range(1, 6):
                                if count_A * sig_A + count_B * sig_B == sig:
                                    combos.append(((ore_A, count_A), (ore_B, count_B)))

                if combos:
                    results = []
                    # Return top 5 combinations sorted by sum of counts (simplest combinations first)
                    combos_sorted = sorted(combos, key=lambda x: x[0][1] + x[1][1])
                    for item in combos_sorted[:5]:
                        (ore_A, count_A), (ore_B, count_B) = item
                        results.append(
                            f"  * Combo: {count_A}x {ore_A.get('name', 'unknown')} ({ore_A.get('category')}) + {count_B}x {ore_B.get('name', 'unknown')} ({ore_B.get('category')})"
                        )
                    return_parts.append(f"Signature {sig} (Possible combinations):\n" + "\n".join(results))
                else:
                    return_parts.append(f"Signature {sig}: No matching single ores or 2-ore combinations found.")

        return "Matches for signatures:\n\n" + "\n\n".join(return_parts)

    @tool('get_ore_locations', "Find the best star systems, celestial bodies (planets, moons), space stations, asteroid belts, and caves to mine specific ore_names. Resolves best spawn locations and provides best/average occurrence ranks.")
    def get_ore_locations(self, ore_names: list[str]) -> str:
        resolved = []
        unresolved = []
        resolved_mappings = {}

        all_ores, _ = self._celd_ores.get_ores()

        for ore_name in ore_names:
            matched_ore, alternatives = self._celd_ores.resolve_ore(ore_name)
            if matched_ore:
                if matched_ore.get("id") not in [r.get("id") for r in resolved]:
                    resolved.append(matched_ore)
                    # Track resolution mapping if the query is not an exact case-neutral match of name or slug
                    if ore_name.lower() != matched_ore.get("name", "").lower() and ore_name.lower() != matched_ore.get("slug", "").lower():
                        resolved_mappings[ore_name] = (matched_ore.get("name"), alternatives)
                    if matched_ore.get("id", "unknown") not in self._celd_ore_locations:
                        self.threaded_execution(self.preload_ore_location, matched_ore.get("id", "unknown"))
            else:
                unresolved.append(ore_name)

        if unresolved:
            suggestions = []
            for u in unresolved:
                _, alternatives = self._celd_ores.resolve_ore(u)
                for alt in alternatives:
                    if alt not in suggestions:
                        suggestions.append(alt)

            suggest_str = f" Did you mean: {', '.join(suggestions[:10])}?" if suggestions else ""
            return f"Unresolved: {', '.join(unresolved)}.{suggest_str}"

        # let's check in a loop if ore locations are loaded
        wait_time_max = 10
        wait_time_round = 0.25
        ready = []
        while len(ready) < len(resolved) and wait_time_max > 0:
            for ore in resolved:
                if ore not in ready and self._celd_ore_locations.get(ore.get("id", "unknown")) is not None:
                    ready.append(ore)
            if len(ready) < len(resolved):
                time.sleep(wait_time_round)
                wait_time_max -= wait_time_round

        if len(ready) < len(resolved):
            not_ready = [ore for ore in resolved if ore not in ready]
            return f"Locations for the following ores are still loading, please try again in a bit:\n{', '.join([ore.get('name', 'unknown') for ore in not_ready])}"

        locations = {}
        for ore in ready:
            for location_type in ['space', 'surface', 'cave', 'exploration']:
                if location_type in self._celd_ore_locations.get(ore.get("id", "unknown"), {}).get_ore_locations():
                    for location in self._celd_ore_locations.get(ore.get("id", "unknown"), {}).get_ore_locations()[location_type]:
                        loc_id = location.get("locationId", "unknown")
                        if loc_id not in locations:
                            locations[loc_id] = {
                                "name": location.get("location", "unknown"),
                                "system": location.get("system", "unknown"),
                                "type": location_type,
                                "best_rank_percent": 0,
                                "average_rank_percent": 0,
                                "ores": []
                            }
                        locations[loc_id]["ores"].append({
                            "name": ore.get("name", "unknown"),
                            "rank_percent": location.get("rankPct", "unknown"),
                            "tier_name": self._celd_ore_locations.get(ore.get("id", "unknown")).get_tier_legend().get(str(location.get("tier", "unknown")), "unknown"),
                        })
                        if locations[loc_id]["best_rank_percent"] < location.get("rankPct", 0):
                            locations[loc_id]["best_rank_percent"] = location.get("rankPct", 0)
                        locations[loc_id]["average_rank_percent"] += location.get("rankPct", 0)

        for location in locations.values():
            if location["ores"]:
                location["average_rank_percent"] = location["average_rank_percent"] / len(location["ores"])

        # best rank and average rank can be used to filter out locations that have very low chances to contain the ore
        # this would save tokens and processing time with the downside of limit location knowledge by the LLM

        if not locations:
            return f"Unable to find any locations for the specified ores."

        # Group locations by System -> Type
        grouped = {}
        for location in locations.values():
            system = location.get("system", "Unknown System")
            loc_type = location.get("type", "unknown")
            if system not in grouped:
                grouped[system] = {}
            if loc_type not in grouped[system]:
                grouped[system][loc_type] = []
            grouped[system][loc_type].append(location)

        return_value = "Found locations (100% rank = best):\n\n"
        for system in sorted(grouped.keys()):
            for loc_type in sorted(grouped[system].keys()):
                return_value += f"{system} > {loc_type.capitalize()}:\n"
                # Sort locations inside this type by best_rank_percent descending
                sorted_locations = sorted(
                    grouped[system][loc_type],
                    key=lambda x: x["best_rank_percent"],
                    reverse=True
                )
                for location in sorted_locations:
                    loc_name = location['name']
                    if len(location["ores"]) > 1:
                        avg_rank = round(location['average_rank_percent'], 1)
                        return_value += f"- {loc_name} (Best: {location['best_rank_percent']}%, Avg: {avg_rank}%):\n"
                        for ore in location["ores"]:
                            return_value += f"  * {ore['name']} ({ore['tier_name']}, {ore['rank_percent']}%)\n"
                    else:
                        ore = location["ores"][0]
                        return_value += f"- {loc_name}: {ore['name']} ({ore['tier_name']}, {ore['rank_percent']}%)\n"
                return_value += "\n"

        note = ""
        if resolved_mappings:
            resolved_lines = []
            for k, (v, alts) in resolved_mappings.items():
                line = f"'{k}' -> '{v}'"
                if alts:
                    line += f" (Alternatives: {', '.join(alts)})"
                resolved_lines.append(line)
            note = f"Resolved: {', '.join(resolved_lines)}\n\n"

        return note + return_value.strip()

    def preload_ore_location(self, ore_id: str):
        if ore_id in self._celd_ore_locations:
            return
        self._celd_ore_locations[ore_id] = None
        ore_locations = OreLocations(self._cache_handler, self.get_api_key_celd)
        ore_locations.load({"ore": ore_id})
        self._celd_ore_locations[ore_id] = ore_locations

    @tool('get_location', "List all mineable locations or search a specific location (using location_names) to find exactly which ores/resources can be mined there, including their concentrations and tiers. Can filter listed locations by system Name ('Stanton', 'Pyro').")
    def get_location(self, location_names: list[str] = None, filter_by_system: str = None) -> str:
        # Load all locations first
        all_locations = self._celd_locations.get_locations()
        if not all_locations:
            return "No locations found."

        # Case 1: If no specific location name is questioned, list locations matching optional system category filter
        if not location_names:
            filtered = all_locations
            if filter_by_system:
                sys_lower = filter_by_system.lower()
                filtered = [loc for loc in all_locations if loc.get("system", "").lower() == sys_lower]

            if not filtered:
                return f"No locations found for system '{filter_by_system}'."

            # Group locations by system and type for a beautiful concise output
            grouped = {}
            for loc in filtered:
                sys = loc.get("system", "unknown")
                ltype = loc.get("type", "unknown")
                if sys not in grouped:
                    grouped[sys] = {}
                if ltype not in grouped[sys]:
                    grouped[sys][ltype] = []
                grouped[sys][ltype].append(loc.get("name", "unknown"))

            output = "Available mineable locations:\n\n"
            for sys in sorted(grouped.keys()):
                output += f"System: {sys}\n"
                for ltype in sorted(grouped[sys].keys()):
                    names_str = ", ".join(sorted(grouped[sys][ltype]))
                    output += f"  - {ltype.capitalize()}: {names_str}\n"
                output += "\n"
            return output.strip()

        # Case 2: We have location_names to resolve and find ores for
        resolved = []
        unresolved = []
        resolved_mappings = {}

        for loc_name in location_names:
            matched_loc, alternatives = self._celd_locations.resolve_location(loc_name)
            if matched_loc:
                if matched_loc.get("id") not in [r.get("id") for r in resolved]:
                    resolved.append(matched_loc)
                    if loc_name.lower() != matched_loc.get("name", "").lower() and loc_name.lower() != matched_loc.get("slug", "").lower():
                        resolved_mappings[loc_name] = (matched_loc.get("name"), alternatives)
                    if matched_loc.get("id", "unknown") not in self._celd_location_ores:
                        self.threaded_execution(self.preload_location_ores, matched_loc.get("id", "unknown"))
            else:
                unresolved.append(loc_name)

        if unresolved:
            suggestions = []
            for u in unresolved:
                _, alternatives = self._celd_locations.resolve_location(u)
                for alt in alternatives:
                    if alt not in suggestions:
                        suggestions.append(alt)
            suggest_str = f" Did you mean: {', '.join(suggestions[:10])}?" if suggestions else ""
            return f"Unresolved locations: {', '.join(unresolved)}.{suggest_str}"

        # wait for ores preload
        wait_time_max = 10
        wait_time_round = 0.25
        ready = []
        while len(ready) < len(resolved) and wait_time_max > 0:
            for loc in resolved:
                if self._celd_location_ores.get(loc.get("id", "unknown")) is not None:
                    if loc not in ready:
                        ready.append(loc)
            if len(ready) < len(resolved):
                time.sleep(wait_time_round)
                wait_time_max -= wait_time_round

        if len(ready) < len(resolved):
            not_ready = [loc for loc in resolved if loc not in ready]
            return f"Ores for the following locations are still loading: {', '.join([loc.get('name', 'unknown') for loc in not_ready])}"

        # Format retrieved location ore contents beautifully and token-efficiently!
        return_value = "Resources present at locations (ranked by presence/concentration):\n\n"
        for loc in ready:
            loc_id = loc.get("id", "unknown")
            loc_ores_model = self._celd_location_ores.get(loc_id)
            if loc_ores_model:
                ores_list = loc_ores_model.get_ores_at_location()
                sys = loc.get("system", "unknown")
                ltype = loc.get("type", "unknown")

                return_value += f"{sys} > {ltype.capitalize()} > {loc.get('name', 'unknown')}:\n"
                if ores_list:
                    for ore in ores_list:
                        conc_pct = round(ore.get("concentration", 0) * 100, 1)
                        return_value += f"  - {ore.get('name', 'unknown')} ({ore.get('tierName', 'unknown')}, {conc_pct}%)\n"
                else:
                    return_value += "  - No ores present.\n"
                return_value += "\n"

        note = ""
        if resolved_mappings:
            resolved_lines = []
            for k, (v, alts) in resolved_mappings.items():
                line = f"'{k}' -> '{v}'"
                if alts:
                     line += f" (Alternatives: {', '.join(alts)})"
                resolved_lines.append(line)
            note = f"Resolved: {', '.join(resolved_lines)}\n\n"

        return note + return_value.strip()

    def preload_location_ores(self, location_id: str):
        if location_id in self._celd_location_ores:
            return
        self._celd_location_ores[location_id] = None
        loc_ores = LocationOres(self._cache_handler, self.get_api_key_celd)
        loc_ores.load({"location": location_id})
        self._celd_location_ores[location_id] = loc_ores

    @tool('get_signature_table', "Get a table of scan signatures for specific ore_names over a range of cluster sizes (multiplier multiples). Receives ore_names, min_cluster_size (default 1, min 1), and max_cluster_size (default 6, min 1). Helps players quickly cross-reference in-game scanning results for multiple rocks.")
    def get_signature_table(self, ore_names: list[str], min_cluster_size: int = 1, max_cluster_size: int = 6) -> str:
        # Validate and bound cluster sizes
        min_size = max(1, int(min_cluster_size))
        max_size = max(1, int(max_cluster_size))
        if max_size < min_size:
            max_size = min_size

        resolved = []
        unresolved = []
        resolved_mappings = {}

        for ore_name in ore_names:
            matched_ore, alternatives = self._celd_ores.resolve_ore(ore_name)
            if matched_ore:
                if matched_ore.get("id") not in [r.get("id") for r in resolved]:
                    resolved.append(matched_ore)
                    if ore_name.lower() != matched_ore.get("name", "").lower() and ore_name.lower() != matched_ore.get("slug", "").lower():
                        resolved_mappings[ore_name] = (matched_ore.get("name"), alternatives)
            else:
                unresolved.append(ore_name)

        if unresolved:
            suggestions = []
            for u in unresolved:
                _, alternatives = self._celd_ores.resolve_ore(u)
                for alt in alternatives:
                    if alt not in suggestions:
                        suggestions.append(alt)
            suggest_str = f" Did you mean: {', '.join(suggestions[:10])}?" if suggestions else ""
            return f"Unresolved: {', '.join(unresolved)}.{suggest_str}"

        if not resolved:
            return "No valid ores requested."

        table_output = f"Signature Table (Cluster size {min_size}-{max_size}):\n\n"
        for ore in resolved:
            name = ore.get("name", "unknown")
            base_sig = ore.get("scanSignature", 0)
            if not base_sig or base_sig <= 0:
                table_output += f"{name}: No known scan signature available.\n\n"
                continue

            table_output += f"{name} (Base: {base_sig}):\n"
            for size in range(min_size, max_size + 1):
                table_output += f"  * {size}x: {base_sig * size}\n"
            table_output += "\n"

        note = ""
        if resolved_mappings:
            resolved_lines = []
            for k, (v, alts) in resolved_mappings.items():
                line = f"'{k}' -> '{v}'"
                if alts:
                     line += f" (Alternatives: {', '.join(alts)})"
                resolved_lines.append(line)
            note = f"Resolved: {', '.join(resolved_lines)}\n\n"

        return note + table_output.strip()

