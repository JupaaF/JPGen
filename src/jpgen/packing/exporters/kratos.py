"""Export a packing as a Kratos DEM particle model part."""


class KratosExporter:
    filename = "particlesDEM.mdpa"

    def export(self, path, packing):
        with open(path, "w", encoding="utf-8") as file:
            file.write("// JPGen spheres, SI units. Periodicity and box bounds require solver configuration.\n")
            file.write("// Properties 1 is an empty export placeholder. Assign materials and contact laws before simulation.\n")
            file.write("Begin ModelPartData\nEnd ModelPartData\n\nBegin Properties 1\n")
            file.write("End Properties\n\nBegin Nodes\n")
            for pid, position in zip(packing.ids, packing.positions):
                file.write(f"{pid} " + " ".join(format(v, ".17g") for v in position) + "\n")
            file.write("End Nodes\n\nBegin Elements SphericParticle3D\n")
            for pid in packing.ids:
                file.write(f"{pid} 1 {pid}\n")
            file.write("End Elements\n")
            values = {"RADIUS": packing.radii}
            for axis, letter in enumerate("XYZ"):
                values[f"VELOCITY_{letter}"] = packing.velocities[:, axis]
                values[f"ANGULAR_VELOCITY_{letter}"] = packing.angular_velocities[:, axis]
            for name, array in values.items():
                file.write(f"\nBegin NodalData {name}\n")
                for pid, value in zip(packing.ids, array):
                    file.write(f"{pid} 0 {value:.17g}\n")
                file.write("End NodalData\n")
