"""Inspectable LIGGGHTS inputs and standalone portable worker modules."""
from dataclasses import asdict
from pathlib import Path
import shutil
import numpy as np
from ....atomic_io import atomic_json
from .library import runtime_provenance


def write_case(case, directory, options, *, retention="full"):
    inputs = directory / "backend/liggghts/input"
    inputs.mkdir(parents=True, exist_ok=False)
    (directory / "backend/liggghts/native").mkdir()
    (directory / "logs").mkdir()
    packing = case.packing
    box = packing.box
    if box.periodic and min(box.lengths) <= 4 * max(packing.radii):
        raise ValueError("Periodic cell must exceed twice the largest particle diameter.")
    # Use consecutive native IDs, preserving arbitrary portable int64 IDs separately.
    np.save(inputs / "particle_ids.npy", packing.ids, allow_pickle=False)
    with (inputs / "particles.data").open("w", encoding="utf-8") as stream:
        stream.write(f"JPGen spheres (SI)\n\n{len(packing.ids)} atoms\n1 atom types\n\n")
        for axis, letter in enumerate("xyz"):
            stream.write(f"{box.origin[axis]:.17g} {box.origin[axis] + box.lengths[axis]:.17g} {letter}lo {letter}hi\n")
        stream.write("\nAtoms # sphere\n\n")
        for index, (radius, position) in enumerate(zip(packing.radii, packing.positions), 1):
            values = " ".join(f"{value:.17g}" for value in position)
            stream.write(f"{index} 1 {2 * radius:.17g} {case.material.density:.17g} {values}\n")
        stream.write("\nVelocities\n\n")
        for index, (velocity, omega) in enumerate(zip(packing.velocities, packing.angular_velocities), 1):
            stream.write(f"{index} " + " ".join(f"{value:.17g}" for value in (*velocity, *omega)) + "\n")
    material = case.material
    commands = ["units si", "atom_style sphere", "soft_particles yes", "hard_particles yes",
        "atom_modify map array sort 0 0",
        "boundary " + ("p p p" if box.periodic else "m m m"),
        "newton off", "read_data ../input/particles.data", "communicate single vel yes",
        f"neighbor {0.1 * min(packing.radii):.17g} bin", "neigh_modify delay 0 every 1 check no",
        f"fix young all property/global youngsModulus peratomtype {material.young_modulus:.17g}",
        f"fix poisson all property/global poissonsRatio peratomtype {material.poisson_ratio:.17g}",
        f"fix restitution all property/global coefficientRestitution peratomtypepair 1 {case.contact.restitution:.17g}",
        f"fix friction all property/global coefficientFriction peratomtypepair 1 {case.contact.static_friction:.17g}",
        f"fix dynamic_friction all property/global jpgenDynamicFriction peratomtypepair 1 {case.contact.dynamic_friction:.17g}",
        f"fix friction_decay all property/global jpgenFrictionDecay peratomtypepair 1 {case.contact.friction_decay:.17g}",
        "pair_style gran model jpgen_hertz tangential jpgen_history", "pair_coeff * *",
        "fix integrator all jpgen/sphere", f"timestep {case.time_step:.17g}",
        "compute jpgen_contacts all pair/gran/local pos id force",
        "thermo 100000000", "thermo_modify lost error", "run 0"]
    gravity = np.asarray(case.gravity)
    magnitude = float(np.linalg.norm(gravity))
    if magnitude:
        commands.insert(-1, f"fix gravity all gravity {magnitude:.17g} vector " + " ".join(f"{v:.17g}" for v in gravity))
    (inputs / "in.liggghts").write_text("\n".join(commands) + "\n", encoding="utf-8")
    atomic_json(inputs / "execution.json", {"options": options, "retention": retention,
        "steps": case.steps, "dt": case.time_step, "protocol": case.protocol,
        "material": asdict(material), "contact": case.contact.to_config(),
        "gravity": list(case.gravity), "runtime": runtime_provenance(options["library"]),
        "box": {"origin": box.origin.tolist(), "lengths": box.lengths.tolist(), "periodic": box.periodic},
        "max_radius": float(max(packing.radii)), "particle_diameter_d50": float(2 * np.median(packing.radii))})
    here = Path(__file__).parent
    for source, target in ((here / "runner.py", "run.py"), (here / "library.py", "library.py"),
                            (here / "protocol_adapter.py", "protocol_adapter.py")):
        shutil.copyfile(source, inputs / target)
    for name in ("protocol.py", "density_continuation.py", "commands.py", "state_exchange.py", "output_writer.py"):
        shutil.copyfile(here.parents[1] / name, inputs / name)
    for name in ("atomic_io.py", "particle_data.py"):
        shutil.copyfile(here.parents[2] / name, inputs / name)
