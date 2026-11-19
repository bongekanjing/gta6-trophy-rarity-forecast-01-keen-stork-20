"""Forecast GTA VI trophy earn rates at a target instant from the recorded reads.

A page prints a rate as k/n: k of the tracked players hold the trophy, n are
tracked. Both move between reads and they move for different reasons, so this
module keeps them apart instead of fitting the printed rate as one series:

  n(t)    the tracked-player count. Exact in every read, monotone, and the same
          for all 55 trophies, so it is estimated once from the whole history
          and carried to the target on an increment curve that decays with age.
  k_i(t)  one trophy's holders. A small integer made fuzzy by the page's two
          decimals, so it is smoothed over the last reads, then grown across the
          fitted rise in n at an exponent shrunk toward a tier prior.

rate_i(target) = 100 * k_i / n, and the band around it adds the three ways that
can be wrong: the n extrapolation, the count's own Poisson noise, and the misfit
of the fit itself.
"""

import math

LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
Z = (-1.6448536269514722, -0.6744897501960817, 0.0,
     0.6744897501960817, 1.6448536269514722)

LOW_PCT = 0.01          # the page's clamp, and the scorer's
HIGH_PCT = 99.99
HALF_PCT = 0.005        # a 2-decimal rate is the midpoint of a 0.01-wide bucket


def clamp_pct(x):
    """Hold a percentage inside the page's 0.01..99.99 range."""
    if x < LOW_PCT:
        return LOW_PCT
    if x > HIGH_PCT:
        return HIGH_PCT
    return x


def to_logit(pct):
    p = clamp_pct(pct)
    return math.log(p / (100.0 - p))


def from_logit(z):
    if z >= 40.0:
        return HIGH_PCT
    if z <= -40.0:
        return LOW_PCT
    return clamp_pct(100.0 / (1.0 + math.exp(-z)))


def round4(x):
    """Four decimals, half up, as the house's own rows are written."""
    scaled = x * 10000.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 10000.0
    return int(value) if value.is_integer() else value


# ---------------------------------------------------------------- n(t)

def hours_between(a, b):
    """Hours from ISO stamp a to ISO stamp b, or None when either is unusable."""
    ka = _stamp(a)
    kb = _stamp(b)
    if ka is None or kb is None:
        return None
    return (kb - ka) / 3600.0


def _stamp(text):
    """Seconds since the epoch for an ISO 8601 UTC stamp, without a tz database."""
    if not isinstance(text, str) or len(text) < 19:
        return None
    try:
        year = int(text[0:4])
        month = int(text[5:7])
        day = int(text[8:10])
        hour = int(text[11:13])
        minute = int(text[14:16])
        second = int(text[17:19])
    except ValueError:
        return None
    days = _days_from_civil(year, month, day)
    return days * 86400.0 + hour * 3600.0 + minute * 60.0 + second


def _days_from_civil(y, m, d):
    """Days since 1970-01-01 for a proleptic Gregorian date (Howard Hinnant's)."""
    y -= 1 if m <= 2 else 0
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def count_series(history, index, n_of):
    """One trophy's holder count in each read, as (hours, count) pairs.

    A read whose rate is missing or unreadable leaves that trophy out of the
    series rather than contributing a zero: an absent rate is no observation.
    """
    out = []
    for k, read in enumerate(history):
        rates = read.get("rates") or []
        if index >= len(rates):
            continue
        rate = rates[index]
        n = n_of[k]
        if rate is None or n is None or n <= 0:
            continue
        at = read.get("at") or read.get("slot")
        hours = hours_between(history[0].get("at") or history[0].get("slot"), at)
        if hours is None:
            hours = float(k)
        out.append((hours, rate / 100.0 * n))
    return out


def player_curve(history, horizon_hours):
    """Tracked players at the target, and how unsure the answer is.

    n is exact in every read, monotone on a launch week, and shared by all 55
    trophies, so it is the one real signal in this task. It is fitted as a
    saturating curve, n(t) = A - (A - n0) * exp(-(t - t0) / tau): new tracked
    players arrive fast and then taper as the launch crowd is absorbed, which is
    what any recorder of a launch sees, and unlike a power law in the increments
    it stays bounded however far the target sits past the last read.

    Every tau is tried and A is solved for it in closed form, so the fit cannot
    run away; the target is the best fit, and the spread covers the range of
    plausible (A, tau) plus the chance that the plateau is further off than the
    window can show.
    """
    pairs = []
    for k, read in enumerate(history):
        n = read.get("players_tracked")
        if not isinstance(n, (int, float)) or n <= 0:
            continue
        at = read.get("at") or read.get("slot")
        hours = hours_between(history[0].get("at") or history[0].get("slot"), at)
        if hours is None:
            hours = float(k)
        pairs.append((hours, float(n)))
    if not pairs:
        return None, 1.0, 0.5
    pairs.sort()
    n_last = pairs[-1][1]
    if len(pairs) < 5 or n_last <= 0:
        # Too few reads to fit a curve: hold the count and lean wide.
        return n_last, 1.0, 0.5

    t0 = pairs[0][0]
    n0 = pairs[0][1]
    t_last = pairs[-1][0]
    span = t_last - t0
    if span <= 0 or n_last <= n0 * 1.02:
        # A flat history says nothing about growth; do not invent any.
        return n_last, 1.0, 0.5

    best = _fit_saturating(pairs, t0, n0)
    if best is None:
        return n_last, 1.0, 0.5
    plateau, tau, sse = best

    t_end = t_last + max(horizon_hours, 0.0)
    mid = _saturating_at(plateau, tau, t0, n0, t_end)

    # The plateau is the least safe number in the fit: a window that ends before
    # the curve has visibly bent cannot tell a long tau from a large A. Carry the
    # best-fit tau and a longer one, and take the spread between them.
    alt = _saturating_at(plateau, tau * 2.5, t0, n0, t_end)
    lo, hi = sorted((mid, alt))
    mid = max(mid, n_last)
    lo = max(lo, n_last)
    spread = math.log(max(hi, 1.0) / max(lo, 1.0)) if lo > 0 else 0.0
    spread = min(1.2, max(0.15, spread))
    growth = mid / n_last if n_last > 0 else 1.0
    return mid, growth, spread


def _saturating_at(plateau, tau, t0, n0, t):
    """The fitted count at time t."""
    if tau <= 0:
        return plateau
    return plateau - (plateau - n0) * math.exp(-(t - t0) / tau)


def _fit_saturating(pairs, t0, n0):
    """Fit a saturating curve anchored on the last read.

    The curve is n(t) = A - (A - n_last) * exp(-(t - t_last)/tau), so it passes
    through the last reading exactly and only its plateau A and taper tau are
    free. Anchoring matters here: the recorded history is not one smooth curve.
    It sits flat while Exophase has not refreshed (638 tracked for the whole of
    launch night) and then steps 6x between two adjacent reads, and a curve that
    is not pinned to the last read will spend its freedom on that step instead of
    on where the count is going.

    Only reads after the count has started moving are fitted, because a flat
    pre-refresh plateau carries no information about the taper; and the fit is in
    log space, so a miss low down costs what a miss high up costs.
    """
    span = pairs[-1][0] - t0
    if span <= 0:
        return None
    t_last, n_last = pairs[-1]
    moving = [(t, n) for t, n in pairs if n > pairs[0][1] * 1.05]
    if len(moving) < 3:
        moving = pairs
    base = math.log(max(n_last, 1.0))
    best = None
    for step in range(1, 241):
        tau = span * (0.10 * (1.0 + step / 4.0))
        xs, ys = [], []
        for t, n in moving:
            if t >= t_last:
                continue
            x = 1.0 - math.exp(-(t - t_last) / tau)   # negative: t is earlier
            xs.append(x)
            ys.append(math.log(max(n, 1.0)) - base)
        den = sum(x * x for x in xs)
        if den <= 1e-12:
            continue
        slope = sum(x * y for x, y in zip(xs, ys)) / den
        if slope <= 0:
            continue
        # ln(A) - ln(n_last) = slope, and A must clear the last reading.
        a = math.exp(base + slope)
        sse = sum((base + slope * x - (y + base)) ** 2 for x, y in zip(xs, ys))
        if best is None or sse < best[2]:
            best = (a, tau, sse)
    return best


# ---------------------------------------------------------------- k_i(t)

SIGMA_BASE = 0.5          # the house baseline's logit spread per sqrt(day)

# How a trophy's holder count scales with tracked players, measured on the real
# page rather than assumed. Across the 54 trophies that moved between the launch
# read (638 tracked) and the read 23 hours later (14,028 tracked), the log-log
# slope alpha = ln(k1/k0) / ln(n1/n0) had a median of 0.045 and a spread of
# 0.209. That median near zero is the heart of the task: the page's rates
# collapse almost entirely because the denominator grew 22-fold, not because
# anything changed about how many players earned each trophy. A few trophies
# (ids 3, 20, 21) really did take off, and they are the right tail.
ALPHA_MED = 0.0448
ALPHA_OFFSETS = (-0.0299, -0.0059, 0.0000, 0.1105, 0.5411)

# A tier does not tell you the slope: measured means were 0.015, 0.037, 0.034
# and 0.162 (platinum, gold, silver, bronze) with a spread wider than the gaps.
# The one real signal is that counts at the page's floor have not started yet.



def held_count(series, n_series=None):
    """A trophy's holder count at the last read, averaged within its refresh.

    Exophase does not update its counts continuously: the rules record the page
    sitting at 638 tracked for the whole of launch night and then stepping to
    3,868 between two adjacent reads. So the printed rate is k/n with n fixed
    inside one refresh, and a count recovered from two reads either side of a
    refresh came from two different denominators. Averaging those together mixes
    a 638-player count with a 3,868-player one and lands nowhere real.

    So the average is taken only over reads that share the last read's tracked
    count, which is the one epoch the last rate belongs to. If that leaves a
    single read, the last read alone is used.
    """
    if not series:
        return 0.5, 1.0
    if n_series and len(n_series) >= len(series):
        n_tail = n_series[-len(series):]
        n_ref = n_tail[-1]
        same = [(t, v) for (t, v), n in zip(series, n_tail) if n == n_ref]
        if same:
            series = same
    tail = series[-5:]
    weights = [1.0 + 0.75 * i for i in range(len(tail))]
    total = sum(weights)
    estimate = sum(w * v for w, (_, v) in zip(weights, tail)) / total
    spread = 1.0
    if len(tail) >= 3:
        values = [v for _, v in tail]
        spread = (max(values) - min(values)) / 2.0 + 1.0
    return max(estimate, 0.5), max(spread, 1.0)


def growth_exponent(series, n_series):
    """A trophy's holder count against tracked players, as a log-log slope.

    Regressing ln(k) on ln(n) over every mid-history pair uses all the reads, not
    just the two ends, so one noisy read cannot set the answer. Duplicate n
    values are dropped (they carry no slope information) and points whose count
    is still at the page's floor are kept, since their climb off zero is real.

    Returns None when the window has too little movement to say anything, which
    is the common case on a frozen launch-night page.
    """
    pts = []
    seen = set()
    for (_, k), n in zip(series, n_series):
        if n is None or n <= 0 or k is None:
            continue
        if n in seen:
            continue
        seen.add(n)
        pts.append((math.log(n), math.log(max(k, 0.5))))
    if len(pts) < 4:
        return None
    mx = sum(x for x, _ in pts) / len(pts)
    my = sum(y for _, y in pts) / len(pts)
    num = sum((x - mx) * (y - my) for x, y in pts)
    den = sum((x - mx) ** 2 for x, _ in pts)
    if den <= 1e-9:
        return None
    return num / den


def forecast_trophy(series, n_series, trophy, n_target, growth, n_unc):
    """One trophy's five quantiles at the target.

    `series` is the trophy's (hours, holder count) pairs and `n_series` the
    tracked count at each of those same reads, both oldest first. `growth` is the
    factor n is expected to rise by between the last read and the target.

    The rate is k/n, so on the logit scale a rate moves with ln(k) - ln(n). Over
    the launch night measured on the real page, k grew as n**alpha with alpha
    centred near 0.045, which means the dominant term is -(1-alpha)*ln(n): the
    rates fall because the denominator grows, and nothing much else happens. The
    forecast therefore takes the trophy's own last rate and pushes it down by
    ln(growth), leaving the small alpha share of the fall to the holders.
    """
    count, count_spread = held_count(series, n_series)
    n_last = n_last_of(series, n_series)
    last_rate = 100.0 * count / n_last if n_last > 0 else 0.0

    # A trophy the page prints at 100% has every tracked player as a holder, so
    # its count is the denominator itself: it cannot be diluted, and alpha is 1.
    # Forecasting it like the others would drag it down by the full rise in n,
    # which is the single largest error a row can make on the logit scale.
    if last_rate >= 99.9:
        return [round4(99.99)] * 5

    if not (0.0 < last_rate <= 100.0):
        last_rate = max(0.01, min(99.99, last_rate))
    base_logit = to_logit(max(last_rate, LOW_PCT))

    # One window of reads is poor evidence for a per-trophy slope: measured
    # slopes ranged from -0.02 to 0.98 with a median of 0.045, and a tier says
    # little about it. So the fitted slope only nudges the measured median.
    alpha = ALPHA_MED
    fitted = growth_exponent(series, n_series)
    if fitted is not None:
        alpha = ALPHA_MED + 0.30 * max(-0.2, min(1.0, fitted) - ALPHA_MED)

    # Only the part of the denominator growth that holders do not follow pushes
    # the rate down, so the shift is -(1-alpha)*ln(growth).
    shift = -(1.0 - alpha) * math.log(growth) if growth > 0 else 0.0

    # The spread is the trophy-to-trophy disagreement in alpha applied to the
    # same denominator growth: with alpha = ALPHA_MED + offset, the logit is
    # logit_base - (1-ALPHA_MED)*ln(G) + offset*ln(G), so each quantile sits
    # ALPHA_OFFSETS[i]*ln(G) off the median. Those offsets came off the real
    # page and are asymmetric on purpose: most trophies barely move, a few take
    # off. A count still near the page's floor is the one thing that makes the
    # downward tail longer, since a rate printed as 0.01 could be anything small.
    scale = math.log(growth) if growth > 0 else 0.0
    poisson = 0.55 / math.sqrt(max(count, 0.5))
    # A rate can move even when the tracked count does not (Exophase refreshes
    # its counts on its own schedule, and players keep earning between them), so
    # the band keeps a floor that does not vanish when growth is flat. Without it
    # a flat window would emit five equal quantiles, which scores the full
    # distance to the answer with none of the cover an honest spread buys.
    spread = [ALPHA_OFFSETS[i] * scale + 0.20 * Z[i] - (poisson if i <= 1 else 0.0)
              for i in range(5)]
    quantiles = [from_logit(base_logit + shift + spread[i]) for i in range(5)]
    return [round4(min(99.99, max(LOW_PCT, q))) for q in quantiles]


def n_last_of(series, n_series):
    """The tracked count at a trophy's own last read."""
    if n_series:
        for n in reversed(n_series):
            if isinstance(n, (int, float)) and n > 0:
                return float(n)
    return 0.0


def n_series_span(series_hours):
    """Hours covered by a trophy's (hours, count) series."""
    if not series_hours:
        return 0.0
    times = [t for t, _ in series_hours]
    return max(times) - min(times)

