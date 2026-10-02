"""Typed ctypes access to the pinned single-process JPGen LIGGGHTS C API."""
import ctypes as C
import numpy as np


class Library:
    def __init__(self, path, threads=1):
        self.lib = C.CDLL(str(path))
        self.lib.jpgen_liggghts_api_version.restype = C.c_int
        if self.lib.jpgen_liggghts_api_version() != 3:
            raise ValueError("Rebuild LIGGGHTS with tools/build_liggghts.py (ABI 3 required)")
        self.lib.jpgen_liggghts_set_threads.argtypes = [C.c_int]
        self.lib.jpgen_liggghts_set_threads.restype = None
        self.lib.jpgen_liggghts_threads.argtypes = []
        self.lib.jpgen_liggghts_threads.restype = C.c_int
        self.lib.jpgen_liggghts_set_threads(threads)
        self.threads = self.lib.jpgen_liggghts_threads()
        if self.threads != threads:
            raise ValueError(f"Requested {threads} threads but OpenMP provided {self.threads}")
        self.lib.jpgen_liggghts_version.restype = C.c_char_p
        self.version = self.lib.jpgen_liggghts_version().decode()
        self.lib.lammps_open_no_mpi.argtypes = [C.c_int, C.POINTER(C.c_char_p), C.POINTER(C.c_void_p)]
        self.lib.lammps_open_no_mpi.restype = None
        self.lib.lammps_close.argtypes = [C.c_void_p]
        self.lib.lammps_close.restype = None
        self.lib.lammps_command.argtypes = [C.c_void_p, C.c_char_p]
        self.lib.lammps_command.restype = None
        self.lib.lammps_file.argtypes = [C.c_void_p, C.c_char_p]
        self.lib.lammps_file.restype = None
        self.lib.lammps_extract_atom.argtypes = [C.c_void_p, C.c_char_p]
        self.lib.lammps_extract_atom.restype = C.c_void_p
        self.lib.lammps_extract_global.argtypes = [C.c_void_p, C.c_char_p]
        self.lib.lammps_extract_global.restype = C.c_void_p
        self.lib.lammps_get_natoms.argtypes = [C.c_void_p]
        self.lib.lammps_get_natoms.restype = C.c_int
        self.lib.lammps_extract_compute.argtypes = [C.c_void_p, C.c_char_p, C.c_int, C.c_int]
        self.lib.lammps_extract_compute.restype = C.c_void_p
        self.lib.jpgen_liggghts_contact_rows.argtypes = [C.c_void_p]
        self.lib.jpgen_liggghts_contact_rows.restype = C.c_int
        self.lib.jpgen_liggghts_set_cell.argtypes = [C.c_void_p, C.POINTER(C.c_double), C.POINTER(C.c_double)]
        self.lib.jpgen_liggghts_set_cell.restype = None
        self.lib.jpgen_liggghts_refresh_ghosts.argtypes = [C.c_void_p]
        self.lib.jpgen_liggghts_refresh_ghosts.restype = None
        self.handle = C.c_void_p()
        args = [b"jpgen", b"-screen", b"none", b"-log", b"liggghts.log"]
        self.lib.lammps_open_no_mpi(len(args), (C.c_char_p * len(args))(*args), C.byref(self.handle))

    def close(self):
        if self.handle:
            self.lib.lammps_close(self.handle)
            self.handle = C.c_void_p()

    def command(self, command):
        self.lib.lammps_command(self.handle, command.encode())

    def file(self, path):
        self.lib.lammps_file(self.handle, str(path).encode())

    def set_cell(self, origin, lengths):
        origin, lengths = np.ascontiguousarray(origin, dtype=np.float64), np.ascontiguousarray(lengths, dtype=np.float64)
        self.lib.jpgen_liggghts_set_cell(self.handle, origin.ctypes.data_as(C.POINTER(C.c_double)),
                                       lengths.ctypes.data_as(C.POINTER(C.c_double)))

    def count(self):
        raw = self.lib.lammps_extract_global(self.handle, b"nlocal")
        count = C.cast(raw, C.POINTER(C.c_int))[0]
        if count != self.lib.lammps_get_natoms(self.handle):
            raise ValueError("JPGen requires single-process LIGGGHTS execution without lost particles")
        return count

    def atom(self, name, *, columns=1, integer=False):
        count = self.count()
        raw = self.lib.lammps_extract_atom(self.handle, name.encode())
        if not raw:
            raise ValueError(f"LIGGGHTS atom attribute unavailable: {name}")
        scalar = C.c_int if integer else C.c_double
        if columns > 1:
            raw = C.cast(raw, C.POINTER(C.POINTER(scalar)))[0]
        array = np.ctypeslib.as_array(C.cast(raw, C.POINTER(scalar)), shape=(count * columns,))
        return array.reshape(count, columns) if columns > 1 else array

    def contacts(self):
        # Symplectic Euler drifts after force calculation; update periodic ghost
        # coordinates and velocities before measuring completed-step contacts.
        self.lib.jpgen_liggghts_refresh_ghosts(self.handle)
        raw = self.lib.lammps_extract_compute(self.handle, b"jpgen_contacts", 2, 2)
        rows = self.lib.jpgen_liggghts_contact_rows(self.handle)
        if rows < 0:
            raise ValueError("LIGGGHTS contact compute is unavailable")
        if not rows:
            return np.empty((0, 12))
        if not raw:
            raise ValueError("LIGGGHTS contact array is unavailable")
        start = C.cast(raw, C.POINTER(C.POINTER(C.c_double)))[0]
        # LIGGGHTS Memory::create allocates a contiguous two-dimensional array.
        return np.ctypeslib.as_array(start, shape=(rows * 12,)).reshape(rows, 12)
