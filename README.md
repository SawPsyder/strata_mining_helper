# Strata Mining Helper

A **Wingman AI** skill for **Star Citizen** that turns your wingman into a mining co-pilot. Ask it
where to mine an ore, what a scanner signature means, or what's hidden in an asteroid belt — and get
fast, accurate answers pulled live from the [Strata Mining Tools](https://strata.celd.space) database.

> Mining data is provided by **celd.space / Strata Mining Tools**. Please credit them when sharing
> results publicly.

---

## What it can do

| Ability | Ask things like… |
| --- | --- |
| **Identify scanner signatures** | *"What is scan signature 17965?"* · *"Verify these scans: 9000, 12000"* |
| **Find where to mine an ore** | *"Where can I find Laranite?"* · *"Which moons have Riccite?"* |
| **Check what's at a location** | *"What can I mine around Yela?"* · *"Is there Hadanite in the Aaron Halo?"* |
| **Browse the ore catalog** | *"List all ship-mineable ores"* · *"What's the signature for Quantainium?"* |
| **Build signature cheat-sheets** | *"Give me a signature table for Laranite up to cluster size 6"* |

Highlights:

- **Scanner combo solver** — if a signature isn't a single ore, it works out the most likely
  multi-ore rock cluster (e.g. *"2× Savrilium + 3× Titanium"*).
- **Typo-tolerant** — *"recite"* → *Riccite (Ore)*, *"titan"* → *Titanium (Ore)*. Just say it
  naturally; the skill figures out what you meant.
- **Batch-friendly** — ask about several ores or locations in one go.
- **Rank & concentration aware** — tells you the *best* spots, not just any spot.

---

## Requirements

- **Wingman AI** (Core) installed and running.
- A free **Strata API key**. Get one at **https://strata.celd.space/api-keys**
  (requires Discord login, a verified email, and your real name on file).

---

## Setup

1. **Install the skill** — place the `strata_mining_helper` folder in your Wingman AI skills
   directory. (`%appdata%\ShipBit\WingmanAI\custom_skills\` on Windows).
2. **Enable it** for a wingman in the Wingman AI client.
3. **Add your API key** — the first time the skill runs it will prompt for the **`celd`** secret.
   Paste your Strata API key there. You can update it later under the wingman's secrets/keys.
4. **Start talking** — try *"Where can I find Titanium?"*

That's it. There are no other settings to configure.

---

## How it works (in brief)

- Data comes from the public Strata Mining Tools API and is **cached locally for 7 days**, so repeat
  questions are instant and you stay well under the API rate limit.
- The skill automatically **refreshes its data when Star Citizen ships a new patch**.
- Cached files live in your Wingman AI generated-files folder under
  `generated_files/StrataMiningHelper/cache/`. Deleting them simply forces a fresh download.

---

## Troubleshooting

| Problem | Fix |
| --- | --- |
| *"Missing secret 'celd'"* or no data returned | Add a valid Strata API key (the `celd` secret). Get one at https://strata.celd.space/api-keys |
| *"…still loading, please try again in a bit"* | Location data is fetched on demand the first time. Just ask again a moment later. |
| Data looks out of date | Delete the files in `generated_files/StrataMiningHelper/cache/` to force a refresh. |
| An ore/location isn't found | Check the spelling; the skill suggests close matches. Brand-new patch content may not be in the database yet. |

---

## Credits & links

- **Data:** [Strata Mining Tools — celd.space](https://strata.celd.space)
- **Game version source:** [UEXcorp](https://uexcorp.space)
- **Author:** JayMatthew

Modifying or extending the skill? See [`AGENTS.md`](AGENTS.md) for a full developer/agent guide to
the codebase.

