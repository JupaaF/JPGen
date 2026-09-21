"""Stream VTK XML PolyData with bounded temporary memory."""

from xml.sax.saxutils import quoteattr

import numpy as np


BLOCK_SIZE = 4096


def _blocks(values, scale=1):
    values = np.asarray(values)
    for start in range(0, len(values), BLOCK_SIZE):
        block = values[start:start + BLOCK_SIZE]
        yield block if scale == 1 else block * scale


def _indices(count, offset):
    for start in range(0, count, BLOCK_SIZE):
        yield np.arange(start + offset, min(start + BLOCK_SIZE, count) + offset, dtype=np.int64)


def _write_data_array(stream, name, blocks, kind="Float64", components=1, *, field=False):
    attributes = dict(type=kind, Name=name, NumberOfComponents=str(components), format="ascii")
    if field:
        attributes["NumberOfTuples"] = "1"
    stream.write("<DataArray " + " ".join(f"{key}={quoteattr(value)}" for key, value in attributes.items()) + ">\n")
    formatter = str if kind == "Int64" else lambda value: format(value, ".17g")
    for block in blocks:
        stream.write(" ".join(formatter(value) for value in block.ravel()))
        stream.write("\n")
    stream.write("</DataArray>\n")


class VtkExporter:
    filename = "particles.vtp"

    def export(self, path, packing):
        count = len(packing.ids)
        with open(path, "w", encoding="utf-8", newline="\n") as stream:
            stream.write('<?xml version="1.0" encoding="utf-8"?>\n'
                         '<VTKFile type="PolyData" version="0.1" byte_order="LittleEndian">\n'
                         '<PolyData>\n<FieldData>\n')
            _write_data_array(stream, "box_origin", _blocks(packing.box.origin), components=3, field=True)
            _write_data_array(stream, "box_lengths", _blocks(packing.box.lengths), components=3, field=True)
            _write_data_array(stream, "periodic", _blocks([int(packing.box.periodic)]), "Int64", field=True)
            stream.write('</FieldData>\n'
                         f'<Piece NumberOfPoints="{count}" NumberOfVerts="{count}" NumberOfLines="0" NumberOfStrips="0" NumberOfPolys="0">\n'
                         '<PointData Scalars="radius" Vectors="velocity">\n')
            for name, values, kind, components, scale in (
                ("id", packing.ids, "Int64", 1, 1),
                ("radius", packing.radii, "Float64", 1, 1),
                ("diameter", packing.radii, "Float64", 1, 2),
                ("velocity", packing.velocities, "Float64", 3, 1),
                ("angular_velocity", packing.angular_velocities, "Float64", 3, 1),
            ):
                _write_data_array(stream, name, _blocks(values, scale), kind, components)
            stream.write('</PointData>\n<Points>\n')
            _write_data_array(stream, "position", _blocks(packing.positions), components=3)
            stream.write('</Points>\n<Verts>\n')
            _write_data_array(stream, "connectivity", _indices(count, 0), "Int64")
            _write_data_array(stream, "offsets", _indices(count, 1), "Int64")
            stream.write('</Verts>\n</Piece>\n</PolyData>\n</VTKFile>\n')
