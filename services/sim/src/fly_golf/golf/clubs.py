"""The fly's bag: fourteen clubs, ordered from shortest (putter) to longest (driver).

Numbers are round, amateur-to-scratch launch-monitor values (ball speed, launch angle,
backspin for a full swing), not measurements of any particular player or club. They are
inputs to `flight.py`; the carry and total distances the fly actually gets are whatever that
physics produces from them (see `nominal_distances`).

The ORDER matters: the motor channel `club_reach` in [0, 1] is decoded to an index into
`BAG` (0 = putter, 13 = driver). See docs/MOTOR_MAPPING.md.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache

CLUBS_VERSION = "bag-v1"


@dataclass(frozen=True)
class Club:
    id: str
    name: str
    short: str
    kind: str  # putter | wedge | iron | hybrid | wood | driver
    loft_deg: float
    ball_speed_mps: float  # full swing, centred strike
    launch_deg: float
    spin_rpm: float
    length_m: float  # shaft length of a real club (the fly's is scaled in the renderer)

    @property
    def is_putter(self) -> bool:
        return self.kind == "putter"

    def to_dict(self) -> dict:
        return asdict(self)


BAG: tuple[Club, ...] = (
    Club("putter", "Putter", "P", "putter", 3.0, 4.2, 0.0, 0.0, 0.86),
    Club("lw", "Lob wedge", "LW", "wedge", 60.0, 29.5, 33.0, 10500.0, 0.89),
    Club("sw", "Sand wedge", "SW", "wedge", 56.0, 34.0, 30.0, 10200.0, 0.89),
    Club("gw", "Gap wedge", "GW", "wedge", 50.0, 38.5, 27.0, 9800.0, 0.90),
    Club("pw", "Pitching wedge", "PW", "wedge", 46.0, 41.5, 24.5, 9200.0, 0.90),
    Club("9i", "9-iron", "9i", "iron", 42.0, 44.0, 22.0, 8500.0, 0.91),
    Club("8i", "8-iron", "8i", "iron", 38.0, 46.5, 19.5, 7700.0, 0.92),
    Club("7i", "7-iron", "7i", "iron", 34.0, 49.0, 17.5, 6900.0, 0.94),
    Club("6i", "6-iron", "6i", "iron", 30.0, 51.5, 15.5, 6100.0, 0.95),
    Club("5i", "5-iron", "5i", "iron", 26.0, 54.0, 14.0, 5400.0, 0.97),
    Club("4h", "4-hybrid", "4H", "hybrid", 22.0, 57.0, 13.5, 4600.0, 1.00),
    Club("5w", "5-wood", "5W", "wood", 18.0, 60.0, 12.5, 4200.0, 1.06),
    Club("3w", "3-wood", "3W", "wood", 15.0, 64.5, 11.5, 3600.0, 1.09),
    Club("driver", "Driver", "D", "driver", 10.5, 69.0, 11.0, 2700.0, 1.15),
)

CLUB_BY_ID: dict[str, Club] = {c.id: c for c in BAG}
PUTTER = BAG[0]


def club_from_reach(reach: float) -> Club:
    """Decode the `club_reach` motor channel: evenly spaced slots, 0 = putter, 1 = driver."""
    if not (0.0 <= reach <= 1.0):
        raise ValueError("club_reach must be within [0, 1]")
    return BAG[int(round(reach * (len(BAG) - 1)))]


def reach_for(club: Club) -> float:
    """The centre of `club`'s slot on the `club_reach` channel."""
    return BAG.index(club) / (len(BAG) - 1)


@lru_cache(maxsize=1)
def nominal_distances() -> dict[str, dict[str, float]]:
    """Carry / total / apex for a full, straight, centred swing on flat fairway (no wind).

    Computed from the same deterministic physics used in play, so it can never drift from
    what actually happens on the course. Used by the mock controller's caddie table, the
    docs and the UI.
    """
    from .flight import FlatTerrain, Launch, simulate_shot

    terrain = FlatTerrain()
    out: dict[str, dict[str, float]] = {}
    for club in BAG:
        if club.is_putter:
            continue
        res = simulate_shot(
            terrain,
            (0.0, 0.0),
            Launch(club.ball_speed_mps, 1.5707963267948966, club.launch_deg, club.spin_rpm, 0.0),
        )
        out[club.id] = {
            "carry_m": round(res.carry_m, 2),
            "total_m": round(res.final_position[1], 2),
            "apex_m": round(res.apex_m, 2),
        }
    return out
