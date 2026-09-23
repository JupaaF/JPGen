"""Kratos metadata; importing this module does not load the engine or its UI."""
from ..base import DemCapabilities
from ..registry import BackendDefinition
from ...protocol import OBSERVABLES

CAPABILITIES = DemCapabilities(
    boundaries=frozenset({"open", "periodic"}),
    controls=frozenset({"free_evolution", "strain_rate", "stress_servo"}),
    observables=frozenset(OBSERVABLES),
    contact_models=frozenset({"hertz_viscous_coulomb"}),
    integration_schemes=frozenset({("symplectic_euler", "direct")}),
    actuator_commands=frozenset({"cell_strain_rate", "symmetric_wall_velocity"}),
    native_controls=frozenset({"stress_servo"}),
    particle_snapshots=True,
    native_restart_export=True,
)

DEFINITION = BackendDefinition(
    label="Kratos",
    factory="jpgen.dem.backends.kratos.backend:KratosBackend.from_config",
    capabilities=CAPABILITIES,
    wizard="jpgen.dem.backends.kratos.wizard:KratosWizard",
    physics="Hertz viscous Coulomb maps to DEM_D_Hertz_viscous_Coulomb, without rolling "
            "resistance or global damping. Symplectic Euler translation and direct rotation. "
            "Stress is contact force/branch stress, compression positive, without kinetic stress. "
            "Cell deformation is affine and preserves contact history. Time stepping is fixed.",
)
