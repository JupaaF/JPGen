"""LIGGGHTS metadata without runtime imports."""
from ..base import DemCapabilities
from ..registry import BackendDefinition

CAPABILITIES = DemCapabilities(
    boundaries=frozenset({"open", "periodic"}),
    controls=frozenset({"free_evolution", "strain_rate", "stress_servo"}),
    observables=frozenset({"kinetic_energy", "normalized_kinetic_energy", "pressure",
        "stress_xx", "stress_yy", "stress_zz", "stress_xy", "stress_xz", "stress_yz",
        "solid_fraction", "bulk_density", "unbalanced_force", "mean_coordination_number", "fabric_tensor",
        "thermal_conductivity"}),
    contact_models=frozenset({"hertz_viscous_coulomb"}),
    integration_schemes=frozenset({("symplectic_euler", "direct")}),
    actuator_commands=frozenset({"cell_strain_rate", "symmetric_wall_velocity"}),
    particle_snapshots=True,
    native_restart_export=True,
)

DEFINITION = BackendDefinition(
    label="LIGGGHTS (JPGen)",
    factory="jpgen.dem.backends.liggghts.backend:LiggghtsBackend.from_config",
    capabilities=CAPABILITIES,
    wizard="jpgen.dem.backends.liggghts.wizard:LiggghtsWizard",
    physics="Single-process LIGGGHTS with JPGen native Hertz/Thornton damping, elastic-force "
            "tangential history and Coulomb limit with exponential static/dynamic friction transition. "
            "Symplectic Euler translation, direct solid-sphere rotation, affine periodic "
            "cell deformation with live contact history. Contact/branch stress, "
            "compression positive, without kinetic stress. No rolling/global damping.",
)
