"""Rank catalog queries without owning catalog publication or eligibility."""

from collections import OrderedDict
from collections.abc import Callable
from collections.abc import Mapping
from typing import cast

_CatalogEntry = dict[str, object]
_RankedResults = tuple[_CatalogEntry, ...]
_RankedCache = OrderedDict[tuple[int, str], _RankedResults]
_FlatScore = tuple[int, int, int, int, int, int, int, int]
_ExactScore = tuple[int, int, int, int, int, int, int, int, str, int]


class RankedCatalogSearch:
    def __init__(
        self,
        *,
        normalize_text: Callable[[object], str],
        coerce_int: Callable[[object, int], int],
        capacity: int,
    ) -> None:
        self._normalize_text = normalize_text
        self._coerce_int = coerce_int
        self._capacity = capacity
        self._flat_ranked_search_cache: _RankedCache = OrderedDict()
        self._exact_ranked_search_cache: _RankedCache = OrderedDict()

    def clear(self) -> None:
        self._flat_ranked_search_cache.clear()
        self._exact_ranked_search_cache.clear()

    def search_flat(
        self,
        raw_query: str,
        *,
        generation: int,
        entries: Mapping[int, _CatalogEntry],
        limit: int,
    ) -> list[_CatalogEntry]:
        query = self._normalize_text(raw_query)
        if not query:
            return []

        ranked_results = self._get_ranked_search_cache_entry(self._flat_ranked_search_cache, query, generation)
        if ranked_results is None:
            ranked_results = self._build_ranked_catalog_search_results(query, entries)
            self._store_ranked_search_cache_entry(self._flat_ranked_search_cache, query, ranked_results, generation)
        return list(ranked_results[: max(1, int(limit))])

    def search_exact(
        self,
        raw_query: str,
        *,
        generation: int,
        typed_entries: Mapping[tuple[int, int], _CatalogEntry],
        untyped_entries: Mapping[int, _CatalogEntry],
        limit: int,
    ) -> list[_CatalogEntry]:
        query = self._normalize_text(raw_query)
        if not query:
            return []

        ranked_results = self._get_ranked_search_cache_entry(self._exact_ranked_search_cache, query, generation)
        if ranked_results is None:
            ranked_results = self._build_ranked_exact_catalog_search_results(query, typed_entries, untyped_entries)
            self._store_ranked_search_cache_entry(self._exact_ranked_search_cache, query, ranked_results, generation)
        return list(ranked_results[: max(1, int(limit))])

    def _get_ranked_search_cache_entry(
        self,
        cache: _RankedCache,
        query: str,
        generation: int,
    ) -> _RankedResults | None:
        cache_key = (int(generation), query)
        cached_results = cache.get(cache_key)
        if cached_results is None:
            return None
        cache.move_to_end(cache_key)
        return cached_results

    def _store_ranked_search_cache_entry(
        self,
        cache: _RankedCache,
        query: str,
        ranked_results: _RankedResults,
        generation: int,
    ) -> None:
        cache_key = (int(generation), query)
        cache[cache_key] = ranked_results
        cache.move_to_end(cache_key)
        while len(cache) > self._capacity:
            cache.popitem(last=False)

    def _build_ranked_catalog_search_results(
        self,
        query: str,
        entries: Mapping[int, _CatalogEntry],
    ) -> _RankedResults:
        matches: list[tuple[_FlatScore, _CatalogEntry]] = []
        for entry in entries.values():
            name = str(entry.get("name", "")).strip()
            model_id = max(0, self._coerce_int(entry.get("model_id", 0), 0))
            if model_id <= 0 or not name:
                continue

            item_type = self._normalize_text(entry.get("item_type", ""))
            material_type = self._normalize_text(entry.get("material_type", ""))
            model_id_text = str(model_id)
            name_lower = self._normalize_text(name)
            alias_labels = entry.get("alias_labels", {})
            alias_matches: list[str] = []
            if isinstance(alias_labels, dict):
                alias_matches = [
                    normalized_alias
                    for normalized_alias in cast(dict[str, object], alias_labels).keys()
                    if query in str(normalized_alias or "")
                ]
            if (
                query not in name_lower
                and query not in model_id_text
                and query not in item_type
                and query not in material_type
                and not alias_matches
            ):
                continue

            exact_alias_hit = any(alias == query for alias in alias_matches)
            prefix_alias_hit = any(alias.startswith(query) for alias in alias_matches)
            score = (
                0 if query == model_id_text else 1,
                0 if name_lower.startswith(query) else 1,
                0 if query in name_lower else 1,
                0 if exact_alias_hit else 1,
                0 if prefix_alias_hit else 1,
                0 if alias_matches else 1,
                0 if query in item_type or query in material_type else 1,
                len(name),
            )
            matches.append((score, entry))

        matches.sort(key=lambda match: match[0])
        return tuple(entry for _, entry in matches)

    def _build_ranked_exact_catalog_search_results(
        self,
        query: str,
        typed_entries: Mapping[tuple[int, int], _CatalogEntry],
        untyped_entries: Mapping[int, _CatalogEntry],
    ) -> _RankedResults:
        matches: list[tuple[_ExactScore, _CatalogEntry]] = []
        for entries in (typed_entries, untyped_entries):
            for entry in entries.values():
                name = str(entry.get("name", "")).strip()
                model_id = max(0, self._coerce_int(entry.get("model_id", 0), 0))
                if model_id <= 0 or not name:
                    continue

                item_type = self._normalize_text(entry.get("item_type", ""))
                material_type = self._normalize_text(entry.get("material_type", ""))
                model_id_text = str(model_id)
                name_lower = self._normalize_text(name)
                alias_labels = entry.get("alias_labels", {})
                alias_matches: list[str] = []
                if isinstance(alias_labels, dict):
                    alias_matches = [
                        normalized_alias
                        for normalized_alias in cast(dict[str, object], alias_labels).keys()
                        if query in str(normalized_alias or "")
                    ]
                if (
                    query not in name_lower
                    and query not in model_id_text
                    and query not in item_type
                    and query not in material_type
                    and not alias_matches
                ):
                    continue

                exact_alias_hit = any(alias == query for alias in alias_matches)
                prefix_alias_hit = any(alias.startswith(query) for alias in alias_matches)
                raw_item_type_id = entry.get("item_type_id")
                type_sort = self._coerce_int(raw_item_type_id, -1) if raw_item_type_id is not None else -1
                score = (
                    0 if query == model_id_text else 1,
                    0 if name_lower.startswith(query) else 1,
                    0 if query in name_lower else 1,
                    0 if exact_alias_hit else 1,
                    0 if prefix_alias_hit else 1,
                    0 if alias_matches else 1,
                    0 if query in item_type or query in material_type else 1,
                    len(name),
                    name_lower,
                    type_sort,
                )
                matches.append((score, entry))

        matches.sort(key=lambda match: match[0])
        return tuple(entry for _, entry in matches)
