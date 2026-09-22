"""Translate the supported physical case into explicit Kratos inputs."""

import json
import shutil
from pathlib import Path

import numpy as np

from ....packing.exporters.kratos import KratosExporter
from ...protocol import required_observables, STRESS_OBSERVABLES

TRANSLATION_SCHEMES = {"symplectic_euler": "Symplectic_Euler"}
ROTATION_SCHEMES = {"direct": "Direct_Integration"}

CONTACT_LAWS = {"hertz_viscous_coulomb": "DEM_D_Hertz_viscous_Coulomb"}


def write_case(case, directory):
    directory.mkdir(parents=True, exist_ok=False)
    inputs = directory / "input"
    inputs.mkdir()
    (directory / "logs").mkdir()
    (directory / "native_results").mkdir()
    KratosExporter().export(inputs / "particlesDEM.mdpa", case.packing)
    material = case.material
    contact = case.contact
    materials = {
        "materials": [{"material_name": "particles", "material_id": 1, "Variables": {
            "PARTICLE_DENSITY": material.density,
            "YOUNG_MODULUS": material.young_modulus,
            "POISSON_RATIO": material.poisson_ratio,
        }}],
        "material_relations": [{"material_ids_list": [1, 1], "Variables": {
            "DEM_DISCONTINUUM_CONSTITUTIVE_LAW_NAME": CONTACT_LAWS[contact.model],
            "STATIC_FRICTION": contact.static_friction,
            "DYNAMIC_FRICTION": contact.dynamic_friction,
            "FRICTION_DECAY": contact.friction_decay,
            "COEFFICIENT_OF_RESTITUTION": contact.restitution,
        }}],
        "material_assignation_table": [["SpheresPart", "particles"]],
    }
    needs_stress = bool(case.protocol and required_observables(case.protocol["stages"]) & STRESS_OBSERVABLES)
    particle_diameter_d50 = float(2 * np.median(case.packing.radii))
    parameters = {
        "problem_name": "particles", "FinalTime": case.end_time,
        "MaxTimeStep": case.time_step, "AutomaticTimestep": False,
        "TranslationalIntegrationScheme": TRANSLATION_SCHEMES[case.integration.translation],
        "RotationalIntegrationScheme": ROTATION_SCHEMES[case.integration.rotation],
        "RotationOption": True, "RollingFrictionOption": False,
        "GlobalDamping": 0.0, "dem_inlet_option": False,
        "ElementType": "SphericParticle3D",
        "PeriodicDomainOption": case.boundary == "periodic",
        "BoundingBoxOption": case.boundary == "periodic", "AutomaticBoundingBoxOption": False,
        "BoundingBoxStartTime": 0.0, "BoundingBoxStopTime": case.end_time,
        "do_print_results_option": False, "post_gid_option": False,
        "NeighbourSearchFrequency": 5,
        "ContactMeshOption": needs_stress, "PostStressStrainOption": needs_stress,
        "ComputeStressTensorOption": needs_stress,
        "BoundingBoxMoveOptionDetail": [1, 1, 1, 1, 1, 1],
        "solver_settings": {
            "strategy": "sphere_strategy",
            "model_import_settings": {"input_type": "mdpa", "input_filename": "particles"},
            "material_import_settings": {"materials_filename": "../input/MaterialsDEM.json"},
        },
    }
    for axis, letter in enumerate("XYZ"):
        parameters[f"Gravity{letter}"] = case.gravity[axis]
        parameters[f"BoundingBoxMin{letter}"] = float(case.packing.box.origin[axis])
        parameters[f"BoundingBoxMax{letter}"] = float(case.packing.box.origin[axis] + case.packing.box.lengths[axis])
    for name, value in (("ProjectParametersDEM.json", parameters), ("MaterialsDEM.json", materials),
                        ("execution.json", {"steps": case.steps, "protocol": case.protocol,
                                             "density": case.material.density, "boundary": case.boundary,
                                             "particle_diameter_d50": particle_diameter_d50,
                                             "young_modulus": material.young_modulus, "poisson_ratio": material.poisson_ratio,
                                             "max_radius": float(np.max(case.packing.radii)),
                                             "end_time": case.end_time})):
        (inputs / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(Path(__file__).with_name("runner.py"), inputs / "run.py")

    shutil.copyfile(Path(__file__).parents[2] / "protocol.py", inputs / "protocol.py")
    shutil.copyfile(Path(__file__).with_name("protocol_adapter.py"), inputs / "protocol_adapter.py")
    shutil.copyfile(Path(__file__).parents[2] / "commands.py", inputs / "commands.py")
    shutil.copyfile(Path(__file__).parents[2] / "state_exchange.py", inputs / "state_exchange.py")
