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
    # the curve has visibly bent cannot tell a long tau from a large A. So the
    # answer is not read off the best fit alone. A saturating curve fitted to a
    # window that is still climbing will bend too early and land low, and an
    # under-predicted denominator is the expensive direction here: it makes the
    # forecast rate too high, and the rate has to fall by the full rise in n.
    # Carry the best fit, a longer taper, and the straight line the window's own
    # average slope implies, then take the median of the three as the middle.
    alt = _saturating_at(plateau, tau * 3.0, t0, n0, t_end)
    moving = [(t, n) for t, n in pairs if n > n0 * 1.05] or pairs
    lin = _linear_near(moving, n_last, horizon_hours)
    # Where the count lands is the middle of three readings, taken in log space:
    # the best fit, a three-times-longer taper, and the last day's slope. The
    # plain median of the three sits low whenever two of them saturate, because
    # then the optimistic reading is outvoted by two that agree only because they
    # both gave up early. On the world the two real reads imply, and on a launch
    # that never bends at all, the geometric middle is the one that keeps the band
    # over the truth; the arithmetic mean buys the same coverage with more loss.
    cands = sorted([max(mid, n_last), max(alt, n_last), max(lin, n_last)])
    centre = math.exp(sum(math.log(c) for c in cands) / 3.0)
    # The spread is the disagreement between the three, widened a little: across
    # the tapers this data cannot rule out, the predicted count ranges over a
    # factor of two, and the band has to straddle that or the forecast pays for
    # every trophy on the wrong side of it.
    spread = math.log(max(cands[2], 1.0) / max(cands[0], 1.0))
    spread = min(1.4, max(0.55, 1.25 * spread))
    growth = centre / n_last if n_last > 0 else 1.0
    return centre, growth, spread


def _linear_near(pairs, n_last, horizon_hours):
    """A straight-line read of the last day's climb, kept near the data.

    Over a 60-hour window the count is still rising at roughly its recent pace,
    so this is the optimistic end of the range. The slope is taken from the last
    day of reads only, since a launch ramp slows down and the whole window's
    average overstates what happens next; and the result is capped at a decade of
    growth so one flat or noisy stretch cannot produce a number the rest of the
    forecast has to carry.
    """
    if len(pairs) < 3 or horizon_hours <= 0:
        return n_last
    day = [(t, n) for t, n in pairs if t >= pairs[-1][0] - 24.0]
    if len(day) < 2:
        day = pairs[-3:]
    (ta, na), (tb, nb) = day[0], day[-1]
    span = tb - ta
    if span <= 0 or na <= 0 or nb <= 0:
        return n_last
    rate = math.log(nb / na) / span
    if rate <= 0:
        return n_last
    return min(n_last * math.exp(rate * horizon_hours), n_last * 12.0)


def _avg_ln_slope(pairs):
    """The growth rate of the reads that have started moving, per hour.

    The window usually opens with a flat stretch while Exophase has not yet
    refreshed (the rules record 638 tracked for the whole of launch night), so
    taking the slope from the first read would divide a real climb by a stretch
    of no climb and badly understate it. Starting from the first read that has
    left the opening floor is the only slope this data supports.
    """
    if len(pairs) < 3:
        return 0.0
    floor = pairs[0][1] * 1.05
    moved = [(t, n) for t, n in pairs if n > floor]
    if len(moved) < 2:
        return 0.0
    (t0, n0), (t1, n1) = moved[0], moved[-1]
    if t1 <= t0 or n0 <= 0 or n1 <= 0:
        return 0.0
    return math.log(n1 / n0) / (t1 - t0)


def _saturating_at(plateau, tau, t0, n0, t):
    """The fitted count at time t."""
    if tau <= 0:
        return plateau
    return plateau - (plateau - n0) * math.exp(-(t - t0) / tau)


def _fit_saturating(pairs, t0, n0):
    """Fit a saturating curve, keeping the taper inside a plausible range.

    The curve is n(t) = A - (A - n_start) * exp(-(t - t_start)/tau) for the
    reads from the point the count first leaves its floor, and it is fitted in
    log space with A and tau both free, so the window's own curvature chooses
    the taper rather than the fit being pinned through its last point.

    The taper is held to at least 36 hours. That floor is not arbitrary: the real
    page climbed from 3,868 to 14,028 tracked between the first refresh and the
    read 23 hours later, and it was still climbing at that point, so a launch ramp
    that has finished inside a day and a half is contradicted by the only long
    observation there is. Without the floor a 60-hour window fits a fast taper
    that explains the reads just as well and then extrapolates to a plateau the
    count has nowhere near reached.
    """
    if len(pairs) < 3:
        return None
    floor = pairs[0][1] * 1.05
    moved = [(t, n) for t, n in pairs if n > floor]
    if len(moved) < 3:
        moved = pairs
    t_start, n_start = moved[0]
    t_last, n_last = pairs[-1]
    span = max(t_last - t_start, 1e-9)
    base = math.log(max(n_start, 1.0))
    best = None
    for step in range(1, 201):
        tau = 36.0 + span * (1.60 * step / 200.0)
        xs, ys = [], []
        for t, n in moved:
            x = 1.0 - math.exp(-(t - t_start) / tau)
            xs.append(x)
            ys.append(math.log(max(n, 1.0)) - base)
        den = sum(x * x for x in xs)
        if den <= 1e-12:
            continue
        top = sum(x * y for x, y in zip(xs, ys)) / den
        if top <= 0:
            continue
        a = math.exp(base + top)
        if a < n_last * 0.999:
            continue                     # a plateau below the last read
        sse = sum((base + top * x - (y + base)) ** 2 for x, y in zip(xs, ys))
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

