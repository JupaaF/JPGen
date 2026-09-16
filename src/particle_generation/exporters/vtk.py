"""VTK XML PolyData: particle centers, scalar radii and vector attributes."""

import xml.etree.ElementTree as ET

import numpy as np


def data(parent, name, values, kind="Float64", components=1):
    element = ET.SubElement(parent, "DataArray", type=kind, Name=name, NumberOfComponents=str(components), format="ascii")
    formatter = str if kind == "Int64" else lambda v: format(v, ".17g")
    element.text = " ".join(formatter(v) for v in np.asarray(values).ravel())


class VtkExporter:
    filename = "particles.vtp"

    def export(self, path, particles):
        count = len(particles.ids)
        root = ET.Element("VTKFile", type="PolyData", version="0.1", byte_order="LittleEndian")
        poly = ET.SubElement(root, "PolyData")
        fields = ET.SubElement(poly, "FieldData")
        data(fields, "box_origin", particles.box.origin, components=3)
        data(fields, "box_lengths", particles.box.lengths, components=3)
        data(fields, "periodic", [int(particles.box.periodic)], "Int64")
        for element in fields:
            element.set("NumberOfTuples", "1")
        piece = ET.SubElement(poly, "Piece", NumberOfPoints=str(count), NumberOfVerts=str(count), NumberOfLines="0", NumberOfStrips="0", NumberOfPolys="0")
        point_data = ET.SubElement(piece, "PointData", Scalars="radius", Vectors="velocity")
        for name, values, kind, components in (
            ("id", particles.ids, "Int64", 1), ("radius", particles.radii, "Float64", 1),
            ("diameter", 2 * particles.radii, "Float64", 1),
            ("velocity", particles.velocities, "Float64", 3),
            ("angular_velocity", particles.angular_velocities, "Float64", 3),
        ):
            data(point_data, name, values, kind, components)
        data(ET.SubElement(piece, "Points"), "position", particles.positions, components=3)
        vertices = ET.SubElement(piece, "Verts")
        data(vertices, "connectivity", np.arange(count), "Int64")
        data(vertices, "offsets", np.arange(1, count + 1), "Int64")
        ET.indent(root)
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
