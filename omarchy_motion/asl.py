"""Small offline ASL handshape vocabulary, with optional local templates.

Geometric rules are a starting point, not a full ASL language model. Distances
and joint bends are rotation/scale invariant. Occluded M/T benefit from samples.
"""
from dataclasses import dataclass
from math import dist, sqrt, isfinite

COMMANDS = ("W", "M", "F", "T")
DIGITS = tuple(str(n) for n in range(10))
LEFT_SYMBOLS = DIGITS + ("O", "o")
FEATURE_COUNT = 16


def canonical_symbol(symbol):
    return "0" if symbol in ("O", "o") else symbol


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def bend(a, b, c):
    u, v = sub(b, a), sub(c, b)
    return (1 + dot(u, v) / max(1e-9, sqrt(dot(u, u) * dot(v, v)))) / 2


def features(points):
    if len(points) != 21 or any(len(p) not in (2, 3) or len(p) != len(points[0]) or not all(isfinite(v) for v in p) for p in points):
        return None
    palm = dist(points[5], points[17])
    if palm < 1e-5:
        return None
    # Straightness and wrist reach of the four non-thumb fingers.
    bends = [min(bend(points[t - 3], points[t - 2], points[t - 1]),
                 bend(points[t - 2], points[t - 1], points[t])) for t in (8, 12, 16, 20)]
    reaches = [dist(points[t], points[0]) / max(1e-6, dist(points[t - 2], points[0])) for t in (8, 12, 16, 20)]
    contacts = [dist(points[4], points[t]) / palm for t in (8, 12, 16, 20)]
    across = sub(points[17], points[5])
    thumb_x = dot(sub(points[4], points[5]), across) / (palm * palm)
    thumb_open = dist(points[4], points[9]) / palm
    thumb_bend = bend(points[2], points[3], points[4])
    cluster = max(dist(points[a], points[b]) / palm for a in (8, 12, 16, 20) for b in (8, 12, 16, 20))
    return bends + reaches + contacts + [thumb_x, thumb_open, thumb_bend, cluster]


@dataclass(frozen=True)
class Prediction:
    symbol: str | None = None
    source: str = "unknown"


def rule(vector, hand):
    straight = [vector[i] > 0.80 and vector[i + 4] > 1.08 for i in range(4)]
    folded = [vector[i] < 0.65 or vector[i + 4] < 0.97 for i in range(4)]
    contacts = vector[8:12]
    thumb_x, thumb_open, thumb_bend, cluster = vector[12:]
    thumb_out = thumb_open > 1.25 and thumb_bend > 0.8 and thumb_x < -0.1

    def pattern(up):
        return all(straight[i] if i in up else folded[i] for i in range(4))

    # Contact signs: F/9, 8, 7, W/6. The remaining three fingers must be straight.
    touched = [i for i in range(4) if contacts[i] < 0.35 and all(straight[j] for j in range(4) if j != i)]
    if len(touched) == 1:
        i = touched[0]
        return ({0: "F", 3: "W"}.get(i) if hand == "Right" else str(9 - i))
    if hand == "Right":
        if pattern({0, 1, 2}) and not thumb_out:
            return "W"
        if all(folded) and not thumb_out:
            # T: thumb between index/middle; M: thumb beyond ring. Reject the
            # middle N/S region. Local templates handle individual variants.
            if 0.05 < thumb_x < 0.30:
                return "T"
            if 0.72 < thumb_x < 1.05:
                return "M"
        return None
    if all(folded) and max(contacts) < 0.55 and cluster < 0.55:
        return "0"
    # A rounded O need not meet the tight-fist folded thresholds. Require a
    # closed thumb/index loop and clustered, curved fingers, not an open C or 9.
    if (not thumb_out and all(v < 0.90 for v in vector[:4])
            and contacts[0] < 0.40 and max(contacts) < 0.85 and cluster < 0.70):
        return "0"
    if pattern({0}):
        return "1" if not thumb_out else None
    if pattern({0, 1}):
        return "3" if thumb_out else "2"
    if all(straight):
        return "5" if thumb_out else "4"
    return None


def feature_distance(a, b):
    # Joint bends have more influence than distances that vary with foreshortening.
    scales = [1] * 4 + [1.5] * 4 + [2] * 4 + [1, 2, 1, 2]
    return sqrt(sum(((x - y) / s) ** 2 for x, y, s in zip(a, b, scales)) / FEATURE_COUNT)


class Recognizer:
    def __init__(self, samples=None):
        self.samples = samples or {}

    def predict(self, vector, hand):
        if vector is None:
            return Prediction()
        # Templates can teach variants and explicitly override a rule. Ambiguous
        # template matches are rejected rather than resolving to a random class.
        classes = {}
        for symbol, samples in self.samples.get(hand, {}).items():
            symbol = canonical_symbol(symbol) if hand == "Left" else symbol
            classes.setdefault(symbol, []).extend(samples)
        ranked = sorted((min(feature_distance(vector, sample) for sample in samples), symbol)
                        for symbol, samples in classes.items() if samples)
        if ranked and ranked[0][0] < 0.12:
            if len(ranked) > 1 and ranked[1][0] - ranked[0][0] < 0.025:
                return Prediction()
            return Prediction(ranked[0][1], "calibrated")
        symbol = rule(vector, hand)
        # Once calibrated, require a sample match for that symbol.
        if symbol in classes:
            return Prediction()
        return Prediction(symbol, "geometry" if symbol else "unknown")
