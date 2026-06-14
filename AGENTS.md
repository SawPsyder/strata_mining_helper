# Strata Mining Helper — Agent Development Guide

> **Audience:** an AI coding agent (or a developer using one) tasked with reading, modifying, or
> extending this skill. You need **zero prior knowledge** of this codebase to work here — everything
> required is below. If you only want to know how the *runtime tools behave* for an end user, jump to
> [Tool Reference](#tool-reference); everything else is about changing the code.

This is a **Wingman AI custom skill** for *Star Citizen*. It wraps the **Strata Mining Tools API**
(`strata.celd.space`) and exposes five AI-callable tools for ore discovery, scan-signature math, and
mining-location intelligence. It is a thin, cache-backed read-only client over a public REST API.

---

## TL;DR for a Modifying Agent

1. **Read this whole file first.** Then read `main.py` (the skill) and `models/model.py` (the base
   class every data model inherits). Those two files explain 90% of the codebase.
2. **Trust live/cached JSON over `openapi.json`.** The upstream spec is out of date in places — see
   [Gotcha #1](#gotchas--non-obvious-facts).
3. **Adding a tool is the most common task.** Follow the [recipe](#recipe-add-a-new-tool). Keep the
   tool count low and returns short — this skill runs on a **token budget** (see [Platform
   Constraints](#platform-constraints--token-budget)).
4. **Don't break the import style.** All imports are absolute from the package root
   (`from strata_mining_helper.models.model import Model`), never relative.
5. **You cannot restart Core.** If you change a `@tool` signature/schema, tell the user to reload the
   skill so the LLM sees the new schema.

---

## File Map

```
strata_mining_helper/
├── main.py                  # StrataMiningHelper(Skill): lifecycle + 5 @tool methods + 2 preload helpers
├── cache_handler.py         # CacheHandler: file-based JSON cache (7-day TTL)
├── default_config.yaml      # Skill metadata (name MUST equal the class name)
├── openapi.json             # Upstream API spec — REFERENCE ONLY, partly stale (see Gotcha #1)
├── logo.png                 # Skill icon
└── models/
    ├── model.py             # Model base class: HTTP fetch, auth, caching, URL templating, find_matches()
    ├── game_version.py      # GameVersion: UEXcorp endpoint, used to detect SC patch changes
    ├── ores.py              # Ores:        GET /api/public/ores
    ├── locations.py         # Locations:   GET /api/public/locations
    ├── ore_locations.py     # OreLocations: GET /api/public/ore-locations/{ore}
    └── location_ores.py     # LocationOres: GET /api/public/location-ores/{location}
```

There are **no tests** in this skill. Each model is trivially unit-testable in isolation — see
[Testing & Debugging](#testing--debugging).

---

## Architecture

Three layers, top to bottom:

```
┌─────────────────────────────────────────────────────────────┐
│ main.py  ·  StrataMiningHelper(Skill)                        │  ← AI-facing layer
│   @tool methods → resolve inputs, orchestrate models,        │    (the only layer the LLM sees)
│   format compact text responses                              │
└───────────────┬─────────────────────────────────────────────┘
                │ instantiates + calls
┌───────────────▼─────────────────────────────────────────────┐
│ models/*.py  ·  Model subclasses                             │  ← data-access layer
│   one class per API endpoint; parse self._data into          │    (typed views over JSON)
│   convenient accessors (get_ores, resolve_location, …)       │
└───────────────┬─────────────────────────────────────────────┘
                │ load() → fetch + cache
┌───────────────▼─────────────────────────────────────────────┐
│ cache_handler.py  ·  CacheHandler                            │  ← persistence layer
│   JSON files on disk, keyed by sanitized URL, 7-day TTL      │
└─────────────────────────────────────────────────────────────┘
```

**Data lives in two tiers:**

| Tier | Endpoints | When loaded | Where cached in memory |
| --- | --- | --- | --- |
| **Discovery** (small, global) | `/ores`, `/locations`, game version | Eagerly in `prepare()` | `self._celd_ores`, `self._celd_locations` |
| **Detail** (per-entity) | `/ore-locations/{ore}`, `/location-ores/{location}` | Lazily, in a background thread, on first request | `self._celd_ore_locations[id]`, `self._celd_location_ores[id]` |

---

## The `Model` Base Class (read this before touching any model)

Every endpoint is a subclass of `Model` (`models/model.py`). Subclasses typically set two class
attributes and add a few typed accessors. The base handles everything else.

```python
class Ores(Model):
    URL_ENDPOINT = "/api/public/ores"          # appended to URL_BASE
    def get_ores(self, ...): return self._data.get("ores", [])
```

**Contract:**

- **`URL_BASE`** — defaults to `https://strata.celd.space`. Override it for a different host
  (`GameVersion` points at UEXcorp).
- **`URL_ENDPOINT`** — the path. May contain `{placeholders}` that are filled from the `parameters`
  dict passed to `load()` via `str.format(**parameters)` (e.g. `"/ore-locations/{ore}"` +
  `load({"ore": "iron_ore"})`).
- **`__init__(cache_handler, key_retrieval_function)`** — the second arg is a **callable returning
  the API key**, *not the key itself*. It is invoked lazily per request, so a key the user changes at
  runtime is picked up without reconstructing the model. Pass `None` for keyless endpoints.
- **`load(parameters=None, use_cache=True) -> bool`** — formats the URL, fetches (cache-aware),
  stores the parsed JSON into `self._data`, and returns **`True` if the response came from cache**.
  Pass `use_cache=False` to force a network refresh (which also re-writes the cache).
- **`find_matches(query, items, search_keys, display_key, cutoff=0.4)`** — the shared fuzzy resolver.
  Four stages, short-circuiting: (1) exact match → (2) substring match → (3) `difflib` fuzzy match at
  `cutoff` → (4) loose suggestions at cutoff `0.1`. Returns `(matched_item | None, alternatives[:10])`.
  This is what powers typo-tolerant ore/location names. Models wrap it in `resolve_ore()` /
  `resolve_location()`.

**Cache key derivation:** the full URL with every non-alphanumeric char replaced by `_`, lowercased,
`.json` appended. So `https://strata.celd.space/api/public/ores` →
`https___strata_celd_space_api_public_ores.json`.

> **Note:** `Model` swallows HTTP errors — on failure `__fetch` logs via bare `print()` and returns
> `(None, False)`, leaving `self._data` unchanged (`{}` on a fresh instance). Callers must tolerate
> empty data. See [Gotcha #7](#gotchas--non-obvious-facts) about the `print()` deviation.

### Model subclass summary

| Class | Endpoint | Key accessors |
| --- | --- | --- |
| `GameVersion` | UEXcorp `/game_versions` (no key) | `get_version()` → live patch string e.g. `"4.8.1"` |
| `Ores` | `/api/public/ores` | `get_ores(filter_category, filter_name)`, `resolve_ore(query)` |
| `Locations` | `/api/public/locations` | `get_locations()`, `resolve_location(query)` |
| `OreLocations` | `/api/public/ore-locations/{ore}` | `get_ore_locations()` (grouped by `space/surface/cave/exploration`), `get_tier_legend()` |
| `LocationOres` | `/api/public/location-ores/{location}` | `get_ores_at_location()`, `get_location_details()` |

---

## Lifecycle (in `main.py`)

| Hook | What it does | Notes for modifiers |
| --- | --- | --- |
| `__init__` | Sets up the cache dir (`<generated_files>/StrataMiningHelper/cache`), a `CacheHandler`, and empty in-memory caches. | Don't do I/O or network here. Don't cache config values. |
| `validate()` | Retrieves the **`celd` API key secret** via `retrieve_secret()`; reports a `MISSING_SECRET` error if absent. | The key is a **secret**, never a custom property. |
| `secret_changed()` | Re-fetches the key when the user updates secrets. | Keep this in sync with `validate()`. |
| `prepare()` | Detects SC patch changes (loads cached `GameVersion`, fetches a fresh one, compares), then calls `__prepare_data()` to (re)load the discovery endpoints. | See the patch-invalidation caveat below. |
| `unload()` | Currently a no-op beyond `super()`. | Add cleanup here if you introduce threads/connections. |

**Patch-change refresh — read carefully:** `prepare()` compares the cached vs. live game version. If
they differ it sets `cached = False`, which makes `__prepare_data()` reload `/ores` and `/locations`
with `use_cache=False`. **It does *not* clear the per-entity detail caches** (`/ore-locations/{…}`,
`/location-ores/{…}`); those refresh only on their own 7-day TTL. The inline comment says "we
invalidate the complete cache," but the code does not — if you need a true full refresh on patch
change, call `self._cache_handler.invalidate_all()` in `prepare()`. Treat this as a known caveat /
easy fix, not intended behavior to preserve.

---

## Tool Reference

All five are `@tool`-decorated methods. The decorator auto-generates the OpenAI schema from the type
hints, so **type hints are mandatory** and parameter names become the schema. Returns are plain
strings shown to the LLM (kept deliberately compact).

| Tool | Signature | Purpose |
| --- | --- | --- |
| `get_ores` | `(filter_by_category=None, ore_names=None)` | Ore catalog: category, tier, scan signature. Category ∈ `ship`/`fps`/`ground_vehicle`. |
| `verify_scan_signature` | `(scan_signatures: list[int])` | Identify scanned rock clusters from signature totals. Solves single ores and **2-ore combinations**. |
| `get_ore_locations` | `(ore_names: list[str])` | Best places to mine given ores, grouped `System > Type > Location`, with rank %. |
| `get_location` | `(location_names=None, filter_by_system=None)` | Reverse lookup. No names → list mineable locations; with names → ore concentrations there. |
| `get_signature_table` | `(ore_names, min_cluster_size=1, max_cluster_size=6)` | Multiplication table of `base_sig × cluster_size` per ore. |

### Two non-obvious algorithms

- **Combo solver (`verify_scan_signature`).** When no single ore divides the signature evenly, it
  brute-forces every pair of **two distinct ores** with counts **1–5** each, solving
  `count_A·sig_A + count_B·sig_B == signature`, then returns the **top 5 simplest** combos (sorted by
  `count_A + count_B`). Complexity is `O(n² · 25)` over signature-bearing ores. Extending to 3-ore
  combos multiplies cost and token output sharply — avoid unless explicitly required.
- **Lazy threaded preload (`get_ore_locations`, `get_location`).** Detail data is fetched off the
  request thread to keep tools responsive. The pattern uses the in-memory dict slot as a tri-state
  sentinel:

  | Slot value | Meaning |
  | --- | --- |
  | key absent | not started → kick off `self.threaded_execution(self.preload_…, id)` |
  | `None` | fetch in flight |
  | `Model` instance | ready to read |

  After dispatching, the tool **polls for non-`None`** for up to **10 s** (0.25 s steps); on timeout
  it returns a "still loading, try again" message rather than blocking forever.

### Shared output convention

When fuzzy resolution rewrites an input, tools prepend a note line:
`Resolved: 'recite' -> 'Riccite (Ore)' (Alternatives: …)`. This exact block is duplicated in four
tools — a prime **refactor target** (extract a `_format_resolution_note(resolved_mappings)` helper).

---

## Recipes (common modifications)

### Recipe: Add a new tool

1. Add a method to `StrataMiningHelper` decorated with `@tool('tool_name', "Concise description. WHEN
   TO USE: …")`. Give **every parameter a type hint**; parameters without defaults become required.
2. Resolve user-supplied ore/location names through `self._celd_ores.resolve_ore(...)` /
   `self._celd_locations.resolve_location(...)` — never trust raw strings. Reuse the `Resolved:`
   note convention.
3. Keep the **return string short and pre-formatted**. Prefer `summarize=False` on the decorator if
   the output is already user-ready, to skip a second LLM pass.
4. Mind the **token budget** — this skill already exposes five tools (above the recommended 1–3). If
   you add one, consider whether an existing tool should absorb the behavior instead.
5. Tell the user to **reload the skill** afterwards (schemas are read at load time; you can't restart
   Core yourself).

### Recipe: Add a new API endpoint / data model

The upstream API exposes endpoints this skill does **not** yet use — notably `/api/public/items` and
`/api/public/craft-cost/{item}` (crafting recipes & costs). To wire one up:

1. Create `models/<thing>.py` subclassing `Model`. Set `URL_ENDPOINT` (use `{placeholders}` for path
   params). Add typed accessors that read `self._data`. Copy `ores.py`/`location_ores.py` as a
   template.
2. For **global** data, load it eagerly in `__prepare_data()` (with `use_cache` honored). For
   **per-entity** data, mirror the lazy `preload_*` + poll pattern and store it in a new
   `self._celd_<thing> = {}` dict.
3. Expose it through a `@tool` (see above). Summarize server-side — **never return raw API JSON**.
4. Pass `self.get_api_key_celd` (the callable, un-called) as the key function for celd endpoints.

### Recipe: Change cache behavior

- **TTL:** edit `CacheHandler.DATA_RETENTION` (seconds; currently `60*60*24*7` = 7 days).
- **Full wipe on patch change:** add `self._cache_handler.invalidate_all()` in `prepare()` when the
  version differs (see the patch-change caveat above).
- **Invalidate one entry:** `self._cache_handler.invalidate_key(<sanitized-url-or-key>)`.

### Recipe: Tune the fuzzy matcher

`find_matches` lives in `models/model.py`. Raise the `cutoff` (default `0.4`) to demand closer
matches (fewer false positives, more "unresolved"); lower it to be more forgiving. The final
suggestion pass is hard-coded to `0.1`.

---

## Gotchas & Non-Obvious Facts

1. **`openapi.json` ≠ live data.** The spec claims `tier` is an integer (0–6), `instability` is
   `0.0–1.0`, and `resistance` is `0.0–1.0`. The **live `/ores` response disagrees**: `tier` is a
   *string label* (`"common"`, `"uncommon"`, `"rare"`, `"fps"`, `"ground_vehicle"`), `instability`
   is an un-normalized number (e.g. `350`, `700`), and `resistance` can be **negative** (e.g.
   `-0.4`). The *location* tier fields (`tier` 0–6 / `tierName`) **do** match the spec. The skill
   currently treats ore `tier`/`scanSignature` as opaque pass-through values, so this rarely bites —
   but **any new feature that interprets these fields must use real responses, not the spec.**
2. **Imports are absolute from the package root** (`from strata_mining_helper.models.model import
   Model`), never relative (`from .models...`). When deployed the folder sits at
   `skills/strata_mining_helper/` and the skills directory is on `sys.path`, making
   `strata_mining_helper` the top-level package. Match this style or imports break.
3. **`name` in `default_config.yaml` must equal the class name** `StrataMiningHelper`. The persistent
   storage path (`get_generated_files_dir()`) is derived from the class name, so renaming either
   without the other orphans the cache.
4. **The API key is a secret, not config.** It is fetched via `retrieve_secret("celd", …)` and passed
   to models as a **lazy callable** (`self.get_api_key_celd`), so runtime key changes apply without
   reload. Don't "simplify" this into a cached string or a custom property.
5. **`threaded_execution` is host-injected.** The base `Skill.threaded_execution` is a *not-ready
   stub* that just logs a warning. The real implementation is bound onto the instance by the host
   (`services/wingman_skill_manager.py`: `skill.threaded_execution = self._wingman.threaded_execution`)
   right after construction. So it works at runtime but is unavailable during `__init__` — never call
   it before `prepare()`.
6. **Discovery vs. detail caching are separate.** A patch change refreshes only the discovery
   endpoints in memory; detail caches expire on their own TTL (see the [lifecycle caveat](#lifecycle-in-mainpy)).
7. **Models log with bare `print()`.** This deviates from the Wingman repo standard (everything should
   go through the `Printr` singleton). The models have no `Printr` handle by design (they're
   host-agnostic). Acceptable as-is; if you modernize, thread a logger/printr callable into `Model`
   rather than importing Wingman internals into the model layer.
8. **`Ores.get_ores(filter_name=…)` is effectively dead.** The skill resolves names itself via
   `resolve_ore`, so that parameter path is unused. Don't rely on it; prefer `resolve_ore`.
9. **Rate limit & attribution.** Upstream allows 120 requests / 60 s per key and asks that you credit
   "data from celd.space" when surfacing data publicly. Caching keeps us far under the limit — don't
   add polling/loops that would change that.

---

## Platform Constraints & Token Budget

This is a Wingman AI skill, so the host platform's rules apply. The authoritative references are
`skills/AGENTS.md` and `skills/README.md` in the **Core** repo. The essentials:

- **Tool schemas cost tokens on every LLM call while the skill is active.** This skill already has
  **five** tools (above the recommended 1–3). Adding more needs real justification; consider merging
  behavior into an existing tool instead.
- **Tool returns cost tokens too.** Always summarize server-side and cap list sizes. This skill's
  compact `System > Type > Location` formatting exists for exactly this reason — preserve it.
- **`discoverable_by_default: false`** (in `default_config.yaml`) keeps the skill off by default
  (progressive disclosure). Don't flip it on without reason.
- **You can't restart Core.** After changing any `@tool` signature, `default_config.yaml`, or the
  skill's public surface, **stop and ask the user to reload the skill** so the new schema is picked
  up.

---

## Testing & Debugging

- **Inspect the cache** to see exactly what the API returned:
  `…/WingmanAI/generated_files/StrataMiningHelper/cache/*.json`. Filenames are the sanitized URLs.
- **Force a refresh:** delete the relevant cache file (or all of them), or change the detected game
  version.
- **Unit-test a model in isolation** — no Wingman runtime needed:

  ```python
  from strata_mining_helper.cache_handler import CacheHandler
  from strata_mining_helper.models.ores import Ores

  ores = Ores(CacheHandler("/tmp/strata-cache"), lambda: "celd_<key>")
  ores.load()
  print(ores.resolve_ore("recite"))   # → (matched_ore_dict, alternatives)
  ```

- **Reproduce fuzzy matching** by calling `resolve_ore` / `resolve_location` directly with messy
  input; tune `cutoff` in `find_matches` if results are too strict or too loose.

---

## Quick Map: "I want to change X → edit Y"

| Goal | Edit |
| --- | --- |
| Add/adjust an AI tool | `main.py` (`@tool` methods) |
| Change how ore/location names are matched | `models/model.py` → `find_matches` |
| Add a new API endpoint | new file in `models/`, wire into `main.py` |
| Change request/auth/caching behavior | `models/model.py` (`load`/`__fetch`/headers) |
| Change cache TTL or invalidation | `cache_handler.py`, `prepare()` in `main.py` |
| Change combo-solver logic | `verify_scan_signature` in `main.py` |
| Change skill metadata / discovery | `default_config.yaml` |
