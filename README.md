# GTA VI trophy rarity forecast — keen-stork-20

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/bongekanjing/gta6-trophy-rarity-forecast-01-keen-stork-20/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/bongekanjing/gta6-trophy-rarity-forecast-01-keen-stork-20/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

Forecasts all 55 Grand Theft Auto VI PlayStation 5 trophy earn rates on Exophase
at the final case's target, 2026-11-26T00:00:00Z.

Full bounty page: https://make.fun/bounty/gta6-trophy-rarity-forecast-01

## What the task really is

The page prints each trophy's earn rate as `k/n`, holders over tracked players.
The house's own recording shows what drives it: the page sat unchanged at 638
tracked players for all of launch night, then refreshed to 3,868 with every rate
but the 100% one **lower**. Nothing had been taken away from players. The
denominator had grown 6x, so every rate fell by construction.

That is the whole mechanism, and it continues: 23 hours after launch the page
read 14,028 tracked players, a further 3.6x. Rates fall because Exophase tracks
more people, not because trophies get rarer.

So the forecast is not a trend fit on the printed rate. It models `k` and `n`
separately:

- `n` — tracked players, exact in every read and shared by all 55 trophies,
  fitted as a saturating curve anchored on the last read.
- `k` — holders, a small integer recovered from the printed rate, and the
  quantity that actually tells you something.

## The measured exponent

With `k ∝ n^α`, the rate's logit moves by `-(1-α)·ln(G)` when the denominator
grows by `G`. Measuring α across the real 638 → 14,028 transition, over the 54
trophies that moved:

| statistic | value |
|---|---|
| median α | **0.045** |
| mean α | 0.141 |
| sd | 0.209 |
| share with α < 0.1 | 67% |

A median near zero is the finding: holders barely grow at all over this window.
Rates collapse because the denominator does. A prior of α ≈ 0.5 — the intuitive
"half the tracked players earn half the trophies" — would be wrong by an order of
magnitude.

The distribution is strongly right-skewed. Most trophies sit at α ≈ 0.04 and
barely move; a few (three of the 55) really do take off. The quantiles are built
from that measured shape rather than a symmetric Gaussian, which is what the
scoring rewards: a symmetric band wide enough to cover the right tail pays for
width at every one of the 54 trophies that did not need it.

## Handling the refresh

A count recovered from two reads either side of an Exophase refresh came from two
different denominators, so averaging them blends a 638-player count with a
3,868-player one. The average is taken only within the last read's refresh epoch.

## Validation

The practice cases are frozen at 638 tracked, so they cannot tune anything: any
honest forecast there is pure persistence and scores ≈ 1.5, and only hardcoding
the rules text's 3,868 beats it. Tuning on the practice board is tuning on a
constant.

What can be checked is the real page and the final's shape.

**Real transition**, history ending at the 3,868 refresh, scored against the real
14,028 read it never saw (3.63x denominator growth):

| | loss | coverage |
|---|---|---|
| this entry | **0.795** | — |
| house baseline | 0.941 | — |

**Final-shaped worlds** — ~60h of 10-minute reads at the deadline, scored 108.5h
later, three different taper rates:

| world | n at target | this entry | house baseline |
|---|---|---|---|
| fast taper | 118,071 | **0.057** | 0.152 |
| mid | 205,927 | **0.039** | 0.141 |
| slow taper | 310,723 | **0.040** | 0.143 |

90% coverage lands at 0.93–0.96 against a nominal 0.90.

## Running it

```
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Standard library only. Reads every `*.in` in the input directory and writes one
`<id>.out` per case: `{"trophies": [{"id": n, "q": [q05, q25, q50, q75, q95]}]}`.
Runs in ~0.2s and is byte-for-byte deterministic across runs.

MIT licensed.
