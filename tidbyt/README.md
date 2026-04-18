# Raccoon Index — Tidbyt app

A tiny Tidbyt (64×32 pixel LED matrix) app that fetches the current Toronto
Raccoon Activity Index tier from `https://raccoonindex.ca` and displays it.

## Install Pixlet

```sh
brew install tidbyt/tidbyt/pixlet
```

## Preview locally

Opens a browser window rendering the app at 64×32 on a loop:

```sh
pixlet serve raccoon_index.star
```

## Push to your Tidbyt

1. Find your device ID:
   ```sh
   pixlet devices
   ```
2. Push the app (replace `<device-id>`):
   ```sh
   pixlet push <device-id> raccoon_index.star
   ```
3. Open the Tidbyt mobile app to enable and rotate the custom app into your schedule.

## What it shows

```
LVL 4
BIN BREACH
CITY 1.16x
```

- `LVL N` — the current city-wide alert tier (1 DEN DORMANCY → 5 PANDAMONIUM)
- Tier name — in the tier's color (matches the website)
- `CITY Nx` — seasonal ratio (1.00× = average; >1 = elevated; <1 = quieter)

The tier name scrolls left-to-right if it doesn't fit (PANDAMONIUM is the
longest at 11 characters).

## Data source

The app polls `https://raccoonindex.ca/data/index_summary.json` every ~15 min.
Pixlet's `ttl_seconds` handles caching server-side so the Tidbyt fleet doesn't
hammer the origin.

## Contributing upstream

This app can be submitted to the
[tidbyt/community](https://github.com/tidbyt/community) repo so anyone with a
Tidbyt can install it. Follow the
[app submission guidelines](https://github.com/tidbyt/community/blob/main/CONTRIBUTING.md).
