"""Stickman skeleton + pose presets.

A Pose is a dict mapping joint name -> (x, y) offset in stickman-local
coordinates where (0, 0) is the centre of the hip. Joints get rendered
relative to a `position` (the stickman's anchor on canvas).

Joint names (canonical):
    head        -> tip of head circle (centre)
    neck
    hip          -> origin (0,0)
    l_shoulder, r_shoulder
    l_elbow,    r_elbow
    l_hand,     r_hand
    l_knee,     r_knee
    l_foot,     r_foot
"""
from __future__ import annotations

from typing import Dict, Tuple, List

Pose = Dict[str, Tuple[float, float]]

# Default neutral standing pose (hip = origin, y axis grows downward in PIL)
_STAND: Pose = {
    "head":       (0, -180),
    "neck":       (0, -130),
    "l_shoulder": (-22, -125),
    "r_shoulder": (22, -125),
    "l_elbow":    (-32, -85),
    "r_elbow":    (32, -85),
    "l_hand":     (-38, -45),
    "r_hand":     (38, -45),
    "hip":        (0, 0),
    "l_knee":     (-15, 50),
    "r_knee":     (15, 50),
    "l_foot":     (-22, 100),
    "r_foot":     (22, 100),
}


def _override(base: Pose, **changes: Tuple[float, float]) -> Pose:
    out = dict(base)
    out.update(changes)
    return out


# ── Pose library ────────────────────────────────────────────────────────────
POSES: Dict[str, Pose] = {
    "stand": _STAND,
    "wave_left": _override(
        _STAND,
        l_elbow=(-30, -150),
        l_hand=(-50, -195),
    ),
    "wave_right": _override(
        _STAND,
        r_elbow=(30, -150),
        r_hand=(50, -195),
    ),
    "arms_up": _override(
        _STAND,
        l_elbow=(-25, -160),
        r_elbow=(25, -160),
        l_hand=(-30, -210),
        r_hand=(30, -210),
    ),
    "walk_a": _override(
        _STAND,
        l_elbow=(-32, -100),
        r_elbow=(32, -70),
        l_hand=(-30, -55),
        r_hand=(40, -25),
        l_knee=(-10, 50),
        r_knee=(20, 45),
        l_foot=(-5, 100),
        r_foot=(35, 95),
    ),
    "walk_b": _override(
        _STAND,
        l_elbow=(-32, -70),
        r_elbow=(32, -100),
        l_hand=(-40, -25),
        r_hand=(30, -55),
        l_knee=(-20, 45),
        r_knee=(10, 50),
        l_foot=(-35, 95),
        r_foot=(5, 100),
    ),
    "jump_up": _override(
        _STAND,
        head=(0, -200),
        neck=(0, -150),
        l_shoulder=(-22, -145),
        r_shoulder=(22, -145),
        l_elbow=(-30, -180),
        r_elbow=(30, -180),
        l_hand=(-35, -225),
        r_hand=(35, -225),
        hip=(0, -20),
        l_knee=(-18, 25),
        r_knee=(18, 25),
        l_foot=(-25, 70),
        r_foot=(25, 70),
    ),
    "sit": _override(
        _STAND,
        head=(0, -130),
        neck=(0, -80),
        l_shoulder=(-22, -75),
        r_shoulder=(22, -75),
        l_elbow=(-32, -35),
        r_elbow=(32, -35),
        l_hand=(-38, 5),
        r_hand=(38, 5),
        hip=(0, 50),
        l_knee=(-30, 60),
        r_knee=(30, 60),
        l_foot=(-30, 105),
        r_foot=(30, 105),
    ),
    "think": _override(
        _STAND,
        r_elbow=(20, -120),
        r_hand=(10, -160),
    ),
    "cheer": _override(
        _STAND,
        l_elbow=(-30, -155),
        r_elbow=(30, -155),
        l_hand=(-55, -210),
        r_hand=(55, -210),
    ),
    "point_right": _override(
        _STAND,
        r_elbow=(40, -120),
        r_hand=(75, -120),
    ),
    "point_left": _override(
        _STAND,
        l_elbow=(-40, -120),
        l_hand=(-75, -120),
    ),
}


# Bone connections: (joint_a, joint_b, width_multiplier)
BONES: List[Tuple[str, str, float]] = [
    ("neck", "hip", 1.2),
    ("neck", "l_shoulder", 1.0),
    ("neck", "r_shoulder", 1.0),
    ("l_shoulder", "l_elbow", 1.0),
    ("l_elbow", "l_hand", 1.0),
    ("r_shoulder", "r_elbow", 1.0),
    ("r_elbow", "r_hand", 1.0),
    ("hip", "l_knee", 1.1),
    ("l_knee", "l_foot", 1.0),
    ("hip", "r_knee", 1.1),
    ("r_knee", "r_foot", 1.0),
]


def list_poses() -> List[str]:
    """Return all pose names available."""
    return list(POSES.keys())


def get_pose(name: str) -> Pose:
    """Return pose by name, fallback to 'stand' if unknown."""
    return POSES.get(name) or POSES["stand"]
