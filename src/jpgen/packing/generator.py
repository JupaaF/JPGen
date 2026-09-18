"""Generate a particle packing from sizing and placement strategies."""

from typing import Protocol

import numpy as np

from ..errors import PackingGenerationError
from ..progress import (
    ExpectedParticleCount,
    PackingAttemptFailed,
    PackingAttemptStarted,
    emit,
)
from .domain import PackingMetadata, ParticlePacking
from .placement import PlacementRequest
from .placement.geometry import audit_placement
from .sampling import stream, vectors
from .sizing import solid_volume


class PackingGenerationService(Protocol):
    def generate(self, plan, observer=None) -> ParticlePacking:
        """Build a validated particle packing from an executable plan."""


class PackingGenerator:
    """Generate one validated particle packing from a normalized plan."""

    def generate(self, plan, observer=None):
        cfg = plan.config
        sizing_strategy = plan.sizing_strategy
        placement_strategy = plan.placement_strategy
        placement_constraints = plan.placement_constraints
        last_error = None
        for restart in range(cfg["restarts"] + 1):
            emit(observer, PackingAttemptStarted(restart + 1, cfg["restarts"] + 1))
            try:
                box, radii = sizing_strategy.create_population(
                    cfg, stream(cfg["seed"], restart, 0)
                )
                if "count" not in cfg:
                    emit(observer, ExpectedParticleCount(len(radii)))
                volume = solid_volume(radii)
                fraction = volume / box.volume
                if "target_solid_fraction" in cfg and abs(fraction - cfg["target_solid_fraction"]) > cfg["solid_fraction_tolerance"] + 1e-14:
                    raise PackingGenerationError(f"Sample solid fraction {fraction:.9g} is outside the requested tolerance.")
                placement = placement_strategy.place(
                    PlacementRequest(
                        box=box,
                        radii=radii,
                        constraints=placement_constraints,
                        rng=stream(cfg["seed"], restart, 1),
                    ),
                    observer,
                )
                # Every algorithm must satisfy the final geometry, not just its internal stopping rule.
                audit = audit_placement(
                    placement.positions,
                    radii,
                    box,
                    placement_constraints.max_overlap,
                    placement_strategy.overlap_tolerance,
                )
                positions = placement.positions
                count = len(radii)
                return ParticlePacking(
                    np.arange(1, count + 1, dtype=np.int64), positions, radii,
                    vectors(cfg["velocity"], count, stream(cfg["seed"], restart, 2), stream(cfg["seed"], restart, 3)),
                    vectors(cfg["angular_velocity"], count, stream(cfg["seed"], restart, 4), stream(cfg["seed"], restart, 5)),
                    box,
                    PackingMetadata(
                        seed=cfg["seed"],
                        successful_restart=restart,
                        placement_method=placement_strategy.method,
                        placement=placement.statistics,
                        audit=audit,
                        solid_fraction=fraction,
                        count=count,
                        rng="PCG64",
                        stream_scheme="SeedSequence(seed, spawn_key=(restart, role)); roles: radii=0, placement=1, speed=2, direction=3, angular_speed=4, angular_direction=5",
                    ),
                )
            except PackingGenerationError as error:
                last_error = error
                emit(observer, PackingAttemptFailed(restart + 1, str(error)))
        raise PackingGenerationError(
            f"Packing generation failed after {cfg['restarts'] + 1} attempts. {last_error}"
        )
