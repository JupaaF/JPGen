"""Portable per-contact analysis arrays; no solver or contact-history objects."""

import numpy as np


CONTACT_UNITS = {"ids": "1", "branches": "m", "normals": "1", "overlaps": "m",
                 "forces": "N", "normal_forces": "N", "tangential_forces": "N"}
FORCE_TIME_LEVELS = {"step_force_evaluation", "completed_step_reevaluation", "initial_uncomputed"}


def contact_snapshot(ids, branches, overlaps, forces, *, engine, force_time_level,
                     tangential_forces=None):
    """Canonicalize pairs: branches are first minus second, forces act on first.

    Native tangential components preserve the constitutive decomposition even
    when the force evaluation preceded the saved geometry (Kratos).
    """
    ids = np.asarray(ids, dtype=np.int64).reshape(-1, 2).copy()
    branches = np.asarray(branches, dtype=np.float64).reshape(-1, 3).copy()
    forces = np.asarray(forces, dtype=np.float64).reshape(-1, 3).copy()
    overlaps = np.asarray(overlaps, dtype=np.float64).reshape(-1)
    distances = np.linalg.norm(branches, axis=1)
    if np.any(distances <= 0):
        raise ValueError("Contact centers must be distinct.")
    normals = branches / distances[:, None]
    if tangential_forces is None:
        normal_forces = np.sum(forces * normals, axis=1)[:, None] * normals
        tangential_forces = forces - normal_forces
    else:
        tangential_forces = np.asarray(tangential_forces, dtype=np.float64).reshape(-1, 3).copy()
        normal_forces = forces - tangential_forces
    reverse = ids[:, 0] > ids[:, 1]
    ids[reverse] = ids[reverse, ::-1]
    for array in (branches, normals, forces, normal_forces, tangential_forces):
        array[reverse] *= -1
    order = np.lexsort((ids[:, 1], ids[:, 0]))
    arrays = dict(ids=ids, branches=branches, normals=normals, overlaps=overlaps,
                  forces=forces, normal_forces=normal_forces, tangential_forces=tangential_forces)
    return {"contacts": {name: array[order] for name, array in arrays.items()},
            "contact_metadata": {"engine": engine, "force_time_level": force_time_level,
                                 "geometry_time_level": "snapshot",
                                 "branch_convention": "first_minus_second_minimum_image",
                                 "force_convention": "force_on_first_by_second",
                                 "units": CONTACT_UNITS}}


def validate_contacts(contacts, metadata, particle_ids, *, positions=None, radii=None, box=None):
    if not isinstance(contacts, dict) or set(contacts) != set(CONTACT_UNITS):
        raise ValueError("Invalid contact array names.")
    if (not isinstance(metadata, dict) or not isinstance(metadata.get("engine"), str)
            or not metadata["engine"]
            or metadata.get("force_time_level") not in FORCE_TIME_LEVELS
            or metadata.get("geometry_time_level") != "snapshot"
            or metadata.get("branch_convention") != "first_minus_second_minimum_image"
            or metadata.get("force_convention") != "force_on_first_by_second"
            or metadata.get("units") != CONTACT_UNITS):
        raise ValueError("Invalid contact metadata or units.")
    ids = np.asarray(contacts["ids"])
    count = len(ids)
    for name, array in contacts.items():
        array = np.asarray(array)
        shape = (count, 2) if name == "ids" else (count,) if name == "overlaps" else (count, 3)
        dtype = np.dtype("int64" if name == "ids" else "float64")
        if (array.shape != shape or array.dtype.kind != dtype.kind
                or array.dtype.itemsize != dtype.itemsize or not np.all(np.isfinite(array))):
            raise ValueError(f"Invalid contact array: {name}.")
    if (np.any(ids[:, 0] >= ids[:, 1]) or not np.all(np.isin(ids, particle_ids))
            or len(np.unique(ids, axis=0)) != count
            or not np.array_equal(np.lexsort((ids[:, 1], ids[:, 0])), np.arange(count))):
        raise ValueError("Contact pairs must be unique ordered particle IDs.")
    branches = contacts["branches"]
    distances = np.linalg.norm(branches, axis=1)
    if np.any(distances <= 0) or not np.allclose(
            contacts["normals"], branches / distances[:, None], rtol=1e-12, atol=1e-14):
        raise ValueError("Contact normals do not match their branches.")
    if not np.allclose(contacts["forces"], contacts["normal_forces"] + contacts["tangential_forces"],
                       rtol=1e-12, atol=1e-14):
        raise ValueError("Contact force components do not sum to the total.")
    if positions is not None:
        order = np.argsort(particle_ids)
        indices = order[np.searchsorted(np.asarray(particle_ids)[order], ids)]
        expected = positions[indices[:, 0]] - positions[indices[:, 1]]
        if box["periodic"]:
            lengths = np.asarray(box["lengths"])
            expected -= lengths * np.rint(expected / lengths)
        if not np.allclose(branches, expected, rtol=1e-12, atol=1e-14):
            raise ValueError("Contact branches do not match the particle geometry.")
        overlaps = radii[indices[:, 0]] + radii[indices[:, 1]] - distances
        if not np.allclose(contacts["overlaps"], overlaps, rtol=1e-12, atol=1e-14):
            raise ValueError("Contact overlaps do not match the particle geometry.")
