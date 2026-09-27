"""The course as the web app consumes it: `GET /api/course`, and the static showcase's course.json."""

from __future__ import annotations

from .clubs import BAG, nominal_distances
from .course import COURSE, COURSE_NAME, COURSE_PAR, COURSE_VERSION, NINES


def course_payload() -> dict:
    return {
        "name": COURSE_NAME,
        "version": COURSE_VERSION,
        "par": COURSE_PAR,
        "nines": [dict(n) for n in NINES],
        "holes": [h.to_dict() for h in COURSE],
        "clubs": [c.to_dict() | {"nominal": nominal_distances().get(c.id)} for c in BAG],
    }
