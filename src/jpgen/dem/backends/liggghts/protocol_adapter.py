"""Live single-process LIGGGHTS cell and observation port for portable protocols."""
import math
import numpy as np
from commands import NoActuation, CellStrainRate, SymmetricWallVelocity
from protocol import STRESS_OBSERVABLES
from overlap import OVERLAP_OBSERVABLES, measure_overlap


class LiggghtsProtocolAdapter:
    def __init__(self, library, execution, ids):
        self.library = library
        self.execution = execution
        self.ids = ids
        self.origin = np.array(execution["box"]["origin"], dtype=float)
        self.lengths = np.array(execution["box"]["lengths"], dtype=float)
        self.periodic = execution["box"]["periodic"]
        self.solid_volume = float(4 * np.pi / 3 * np.sum(library.atom("radius")**3))

    def box(self):
        return {"origin": self.origin.tolist(), "lengths": self.lengths.tolist(), "periodic": self.periodic}

    def control_context(self, dt):
        return {"dt": dt, "particle_diameter_d50": self.execution["particle_diameter_d50"],
                "young_modulus": self.execution["material"]["young_modulus"]}

    def apply(self, command, dt):
        if isinstance(command, NoActuation):
            return
        if not isinstance(command, (CellStrainRate, SymmetricWallVelocity)):
            raise ValueError(f"Unsupported actuator command: {command!r}")
        if not self.periodic:
            raise ValueError("Cell deformation requires periodic boundaries")
        if isinstance(command, CellStrainRate):
            scales = np.exp(np.array(command.values) * dt)
        else:
            scales = 1 - 2 * np.array(command.values) * dt / self.lengths
        if not np.all(np.isfinite(scales)) or np.any(scales <= 0) or np.any(abs(np.log(scales)) > 0.01):
            raise ValueError("Cell actuator exceeds 1% strain or collapses the cell")
        if np.all(scales == 1):
            return
        lengths = self.lengths * scales
        if min(lengths) <= 4 * self.execution["max_radius"]:
            raise ValueError("Periodic cell must exceed twice the largest particle diameter")
        origin = self.origin + (self.lengths - lengths) / 2
        self.library.set_cell(origin, lengths)
        self.origin, self.lengths = origin, lengths

    def arrays(self):
        native_ids = self.library.atom("id", integer=True).copy()
        order = np.argsort(native_ids)
        if not np.array_equal(native_ids[order], np.arange(1, len(self.ids) + 1)):
            raise ValueError("LIGGGHTS changed particle IDs/population")
        yield "ids", self.ids.copy()
        positions = self.library.atom("x", columns=3)[order].copy()
        if self.periodic:
            positions = self.origin + (positions - self.origin) % self.lengths
        yield "positions", positions
        yield "radii", self.library.atom("radius")[order].copy()
        yield "velocities", self.library.atom("v", columns=3)[order].copy()
        yield "angular_velocities", self.library.atom("omega", columns=3)[order].copy()

    def observe(self, requested):
        result = {}
        volume = float(np.prod(self.lengths))
        if requested & {"kinetic_energy", "normalized_kinetic_energy"}:
            mass = self.library.atom("rmass")
            radii = self.library.atom("radius")
            v = self.library.atom("v", columns=3)
            w = self.library.atom("omega", columns=3)
            result["kinetic_energy"] = float(np.sum(0.5 * mass * np.sum(v*v, axis=1)
                                                   + 0.2 * mass * radii*radii * np.sum(w*w, axis=1)))
        if requested & {"solid_fraction", "bulk_density"}:
            result["solid_fraction"] = self.solid_volume / volume
            result["bulk_density"] = result["solid_fraction"] * self.execution["material"]["density"]
        if requested & (STRESS_OBSERVABLES | OVERLAP_OBSERVABLES | {"normalized_kinetic_energy", "unbalanced_force", "mean_coordination_number", "fabric_tensor", "thermal_conductivity"}):
            contacts = self.library.contacts()
            branch = contacts[:, :3] - contacts[:, 3:6]
            if self.periodic:
                branch = branch - self.lengths * np.rint(branch / self.lengths)
            force = contacts[:, 9:12]
            if requested & OVERLAP_OBSERVABLES:
                # Native rows may use either orientation; count each particle pair once.
                pairs = np.sort(contacts[:, 6:8].astype(np.int64), axis=1)
                _, unique = np.unique(pairs, axis=0, return_index=True)
                unique = unique[pairs[unique, 0] != pairs[unique, 1]]
                radii = np.empty(len(self.ids) + 1)
                radii[self.library.atom("id", integer=True)] = self.library.atom("radius")
                result.update(measure_overlap(
                    radii[pairs[unique, 0]], radii[pairs[unique, 1]],
                    np.linalg.norm(branch[unique], axis=1),
                    cell_volume=volume if self.periodic else None))
            if requested & (STRESS_OBSERVABLES | {"normalized_kinetic_energy"}):
                stress = force.T @ branch / volume
                for i, j, suffix in ((0,0,"xx"),(1,1,"yy"),(2,2,"zz"),(0,1,"xy"),(0,2,"xz"),(1,2,"yz")):
                    result["stress_" + suffix] = float(stress[i,j])
                result["pressure"] = float(np.trace(stress) / 3)
            if "unbalanced_force" in requested:
                denominator = float(np.mean(np.sum(force*force, axis=1))) if len(contacts) else 0
                # Both RMS reductions use this completed-step force evaluation.
                # atom.f still contains forces used before the velocity kick.
                native_ids = self.library.atom("id", integer=True)
                particle_force = np.zeros((len(self.ids) + 1, 3))
                np.add.at(particle_force, contacts[:, 6].astype(np.int64), force)
                np.add.at(particle_force, contacts[:, 7].astype(np.int64), -force)
                particle_force = particle_force[native_ids]
                particle_force += self.library.atom("rmass")[:, None] * np.asarray(self.execution["gravity"])
                result["unbalanced_force"] = math.sqrt(float(np.mean(np.sum(particle_force**2, axis=1))) / denominator) if denominator else 0.0
            if "mean_coordination_number" in requested:
                # Kratos includes all particles in the denominator, including rattlers.
                result["mean_coordination_number"] = 2 * len(contacts) / len(self.ids)
            if "fabric_tensor" in requested:
                distances = np.linalg.norm(branch, axis=1)
                directions = branch[distances > 0] / distances[distances > 0, None]
                fabric = directions.T @ directions / len(directions) if len(directions) else np.zeros((3,3))
                deviator = 7.5 * (fabric - np.eye(3) / 3)
                result["fabric_tensor"] = fabric.tolist()
                result["fabric_second_invariant"] = float(np.sqrt(0.5 * np.sum(deviator**2)))
            if "thermal_conductivity" in requested and self.periodic:
                # Match Kratos's dimensionless contact-geometry tensor, using
                # intersection-circle areas rather than forces or temperatures.
                radii = np.empty(len(self.ids) + 1)
                radii[self.library.atom("id", integer=True)] = self.library.atom("radius")
                first = radii[contacts[:, 6].astype(np.int64)]
                second = radii[contacts[:, 7].astype(np.int64)]
                distances = np.linalg.norm(branch, axis=1)
                active = (distances > 0) & (distances <= first + second)
                distances = distances[active]
                first, second = first[active], second[active]
                directions = branch[active] / distances[:, None]
                argument = 4 * first**2 * distances**2 - (first**2 + distances**2 - second**2)**2
                areas = np.pi * np.maximum(argument, 0) / (4 * distances**2)
                tensor = (directions.T * (areas * distances)) @ directions / volume
                result["thermal_conductivity"] = tensor.tolist()
                result["thermal_conductivity_trace"] = float(np.trace(tensor) / 3)
        if "normalized_kinetic_energy" in requested and result["pressure"] > 0:
            result["normalized_kinetic_energy"] = result["kinetic_energy"] / (result["pressure"] * volume)
        if any(not np.all(np.isfinite(value)) for value in result.values()):
            raise ValueError("Nonfinite LIGGGHTS observable")
        return result
