"""Export a packing as VTK XML PolyData."""

import xml.etree.ElementTree as ET

import numpy as np


def _add_data_array(parent, name, values, kind="Float64", components=1):
    element = ET.SubElement(parent, "DataArray", type=kind, Name=name, NumberOfComponents=str(components), format="ascii")
    formatter = str if kind == "Int64" else lambda v: format(v, ".17g")
    element.text = " ".join(formatter(v) for v in np.asarray(values).ravel())


class VtkExporter:
    filename = "particles.vtp"

    def export(self, path, packing):
        count = len(packing.ids)
        root = ET.Element("VTKFile", type="PolyData", version="0.1", byte_order="LittleEndian")
        poly = ET.SubElement(root, "PolyData")
        fields = ET.SubElement(poly, "FieldData")
        _add_data_array(fields, "box_origin", packing.box.origin, components=3)
        _add_data_array(fields, "box_lengths", packing.box.lengths, components=3)
        _add_data_array(fields, "periodic", [int(packing.box.periodic)], "Int64")
        for element in fields:
            element.set("NumberOfTuples", "1")
        piece = ET.SubElement(poly, "Piece", NumberOfPoints=str(count), NumberOfVerts=str(count), NumberOfLines="0", NumberOfStrips="0", NumberOfPolys="0")
        point_data = ET.SubElement(piece, "PointData", Scalars="radius", Vectors="velocity")
        for name, values, kind, components in (
            ("id", packing.ids, "Int64", 1), ("radius", packing.radii, "Float64", 1),
            ("diameter", 2 * packing.radii, "Float64", 1),
            ("velocity", packing.velocities, "Float64", 3),
            ("angular_velocity", packing.angular_velocities, "Float64", 3),
        ):
            _add_data_array(point_data, name, values, kind, components)
        _add_data_array(ET.SubElement(piece, "Points"), "position", packing.positions, components=3)
        vertices = ET.SubElement(piece, "Verts")
        _add_data_array(vertices, "connectivity", np.arange(count), "Int64")
        _add_data_array(vertices, "offsets", np.arange(1, count + 1), "Int64")
        ET.indent(root)
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
