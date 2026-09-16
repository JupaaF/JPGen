"""Coordinate geometry, packing, restart streams and initial velocities."""

import numpy as np

from .domain import ParticleSet
from .packing import PackingConstraints, PackingRequest, build_packing_strategy
from .packing.geometry import validate_result
from .sampling import GenerationError, stream, vectors
from .strategies import GEOMETRY_STRATEGIES, solid_volume


def generate(cfg, report=None):
    strategy = GEOMETRY_STRATEGIES[cfg["mode"]]()
    packing_strategy = build_packing_strategy(cfg["packing"])
    last_error = None
    for restart in range(cfg["restarts"] + 1):
        if report:
            report(f"Generation attempt {restart + 1}/{cfg['restarts'] + 1}")
        try:
            box, radii = strategy.prepare(cfg, stream(cfg["seed"], restart, 0))
            if "count" not in cfg and report:
                report(f"Expected particle count: {len(radii)}")
            volume = solid_volume(radii)
            if not np.all(np.isfinite(box.lengths)) or not np.isfinite(box.volume) or box.volume <= 0:
                raise GenerationError("Generated box is not representable in float64.")
            fraction = volume / box.volume
            if "target_solid_fraction" in cfg and abs(fraction - cfg["target_solid_fraction"]) > cfg["solid_fraction_tolerance"] + 1e-14:
                raise GenerationError(f"Sample solid fraction {fraction:.9g} is outside the requested tolerance.")
            packing = packing_strategy.pack(
                PackingRequest(
                    box=box,
                    radii=radii,
                    constraints=PackingConstraints(max_overlap=cfg["max_overlap"]),
                    rng=stream(cfg["seed"], restart, 1),
                ),
                report,
            )
            # Every algorithm must satisfy the final geometry, not just its internal stopping rule.
            audit = validate_result(packing.positions, radii, box, cfg["max_overlap"],
                                    cfg["packing"].get("overlap_tolerance", 0.0))
            positions = packing.positions
            count = len(radii)
            return ParticleSet(
                np.arange(1, count + 1, dtype=np.int64), positions, radii,
                vectors(cfg["velocity"], count, stream(cfg["seed"], restart, 2), stream(cfg["seed"], restart, 3)),
                vectors(cfg["angular_velocity"], count, stream(cfg["seed"], restart, 4), stream(cfg["seed"], restart, 5)),
                box,
                {"seed": cfg["seed"], "successful_restart": restart, "packing_method": cfg["packing"]["method"],
                 "packing": packing.statistics, **audit, "solid_fraction": fraction,
                 "count": count, "rng": "PCG64", "stream_scheme": "SeedSequence(seed, spawn_key=(restart, role)); roles: radii=0, packing=1, speed=2, direction=3, angular_speed=4, angular_direction=5"},
            )
        except GenerationError as error:
            last_error = error
            if report:
                report(f"Attempt failed: {error}")
    raise GenerationError(f"Generation failed after {cfg['restarts'] + 1} attempts. {last_error}")
