from typing import Callable
import requests
import re
from strata_mining_helper.cache_handler import CacheHandler


class Model:

    URL_BASE = "https://strata.celd.space"

    # URL_ENDPOINT defines the API path after URL_BASE.
    # It can optionally contain curly brace placeholders for parameters (e.g. "/api/items/{item_id}").
    # Any such placeholder MUST match a key in the `parameters` dictionary passed to `load()`.
    # Example:
    #   URL_ENDPOINT = "/api/v1/ship/{ship_id}/cargo"
    #   and load(parameters={"ship_id": "c2-hercules"}) will result in:
    #   "/api/v1/ship/c2-hercules/cargo"
    URL_ENDPOINT = ""

    def __init__(self, cache_handler: CacheHandler, key_retrieval_function: Callable | None = None) -> None:
        self._cache_handler = cache_handler
        self._key_retrieval_function = key_retrieval_function
        self._data = {}

    @property
    def _api_key(self) -> str | None:
        if self._key_retrieval_function:
            return self._key_retrieval_function()
        return None

    def __loud_by_data(self, data: dict) -> dict:
        self._data = data
        return self._data

    def load(self, parameters: None|dict = None, use_cache: bool = True) -> bool:
        url_endpoint = self.URL_ENDPOINT
        if parameters:
            try:
                url_endpoint = self.URL_ENDPOINT.format(**parameters)
            except (KeyError, IndexError, ValueError) as e:
                print(f"Error formatting URL_ENDPOINT '{self.URL_ENDPOINT}' with parameters {parameters}: {str(e)}")

        url = self.URL_BASE + url_endpoint
        data, cached = self.__fetch(url, use_cache)
        if data:
            self.__loud_by_data(data)
        return cached

    def __get_headers(self) -> dict|None:
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        if headers == {}:
            return None
        return headers

    def __fetch(self, url: str, use_cache: bool = True, update_cache: bool = True) -> tuple[dict | None, bool]:
        cache_key = re.sub(r'[^a-zA-Z0-9_-]', '_', url)
        cache = None
        if use_cache:
            cache = self._cache_handler.retrieve(cache_key)
        if cache:
            return cache, True
        
        # fetch if no valid cache
        try:
            header = self.__get_headers()
            if header is not None:
                response = requests.get(url, headers=header)
            else:
                response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            if update_cache:
                self._cache_handler.store(cache_key, data)
            return data, False
        except Exception as e:
            print(f"Error fetching data from {url}: {str(e)}")
            return None, False

    def find_matches(
        self,
        query: str,
        items: list[dict],
        search_keys: list[str],
        display_key: str,
        cutoff: float = 0.4
    ) -> tuple[dict | None, list[str]]:
        """
        Broad, neutral string matching utility helper.
        Finds direct/substring or fuzzy matches within a list of dictionaries based on given keys.
        Returns a tuple/pair of (matched_item, list_of_close_alternative_display_names).
        """
        import difflib
        query_lower = query.lower()

        # 1. Exact match
        for item in items:
            for key in search_keys:
                val = str(item.get(key, "")).lower()
                if val == query_lower:
                    return item, []

        # 2. Substring match
        for item in items:
            for key in search_keys:
                val = str(item.get(key, "")).lower()
                if val and (query_lower in val or val in query_lower):
                    return item, []

        # 3. Fuzzy matching on combined candidate values across all search keys
        candidates = []
        cand_map = {}
        for item in items:
            for key in search_keys:
                val = str(item.get(key, "")).lower()
                if val:
                    candidates.append(val)
                    cand_map[val] = item

        matches = difflib.get_close_matches(query_lower, candidates, n=20, cutoff=cutoff)
        if matches:
            matched_item = cand_map[matches[0]]
            # Gather unique alternative display names from the rest of the matches
            alternatives = []
            for m in matches[1:]:
                alt_item = cand_map[m]
                alt_name = alt_item.get(display_key)
                if alt_name and alt_name != matched_item.get(display_key) and alt_name not in alternatives:
                    alternatives.append(alt_name)
            return matched_item, alternatives[:10]

        # 4. Overall close matches for suggestion in case of no resolved item
        overall_candidates = []
        cand_map_suggestion = {}
        for item in items:
            for key in search_keys:
                val = str(item.get(key, "")).lower()
                if val:
                    overall_candidates.append(val)
                    cand_map_suggestion[val] = item

        matches = difflib.get_close_matches(query_lower, overall_candidates, n=10, cutoff=0.1)
        alternatives = []
        for m in matches:
            alt_item = cand_map_suggestion[m]
            alt_name = alt_item.get(display_key)
            if alt_name and alt_name not in alternatives:
                alternatives.append(alt_name)

        return None, alternatives[:10]
