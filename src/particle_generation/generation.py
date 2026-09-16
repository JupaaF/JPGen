"""Coordinate geometry, packing, restart streams and initial velocities."""

import numpy as np

from .domain import GenerationMetadata, ParticleSet
from .packing import PackingRequest
from .packing.geometry import audit_packing
from .progress import (
    ExpectedParticleCount,
    GenerationAttemptFailed,
    GenerationAttemptStarted,
    emit,
)
from .sampling import GenerationError, stream, vectors
from .strategies import solid_volume


class ParticleGenerator:
    """Generate one validated particle aggregate from normalized configuration."""

    def generate(self, plan, observer=None):
        cfg = plan.config
        strategy = plan.geometry_strategy
        packing_strategy = plan.packing_strategy
        packing_constraints = plan.packing_constraints
        last_error = None
        for restart in range(cfg["restarts"] + 1):
            emit(observer, GenerationAttemptStarted(restart + 1, cfg["restarts"] + 1))
            try:
                box, radii = strategy.prepare(cfg, stream(cfg["seed"], restart, 0))
                if "count" not in cfg:
                    emit(observer, ExpectedParticleCount(len(radii)))
                volume = solid_volume(radii)
                fraction = volume / box.volume
                if "target_solid_fraction" in cfg and abs(fraction - cfg["target_solid_fraction"]) > cfg["solid_fraction_tolerance"] + 1e-14:
                    raise GenerationError(f"Sample solid fraction {fraction:.9g} is outside the requested tolerance.")
                packing = packing_strategy.pack(
                    PackingRequest(
                        box=box,
                        radii=radii,
                        constraints=packing_constraints,
                        rng=stream(cfg["seed"], restart, 1),
                    ),
                    observer,
                )
                # Every algorithm must satisfy the final geometry, not just its internal stopping rule.
                audit = audit_packing(
                    packing.positions,
                    radii,
                    box,
                    packing_constraints.max_overlap,
                    packing_strategy.overlap_tolerance,
                )
                positions = packing.positions
                count = len(radii)
                return ParticleSet(
                    np.arange(1, count + 1, dtype=np.int64), positions, radii,
                    vectors(cfg["velocity"], count, stream(cfg["seed"], restart, 2), stream(cfg["seed"], restart, 3)),
                    vectors(cfg["angular_velocity"], count, stream(cfg["seed"], restart, 4), stream(cfg["seed"], restart, 5)),
                    box,
                    GenerationMetadata(
                        seed=cfg["seed"],
                        successful_restart=restart,
                        packing_method=packing_strategy.method,
                        packing=packing.statistics,
                        audit=audit,
                        solid_fraction=fraction,
                        count=count,
                        rng="PCG64",
                        stream_scheme="SeedSequence(seed, spawn_key=(restart, role)); roles: radii=0, packing=1, speed=2, direction=3, angular_speed=4, angular_direction=5",
                    ),
                )
            except GenerationError as error:
                last_error = error
                emit(observer, GenerationAttemptFailed(restart + 1, str(error)))
        raise GenerationError(f"Generation failed after {cfg['restarts'] + 1} attempts. {last_error}")
