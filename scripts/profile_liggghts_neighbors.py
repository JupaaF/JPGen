#!/usr/bin/env python3
"""Profile native neighbor policies against identical initial DEM inputs."""
import argparse
import ctypes as C
from datetime import datetime, timezone
import hashlib
import itertools
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

import numpy as np
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/jpgen/dem"))
sys.path.insert(0, str(ROOT / "src/jpgen/dem/backends/liggghts"))
from library import Library, runtime_provenance
from protocol_adapter import LiggghtsProtocolAdapter


def policies():
    result = [(0.1, 1, "no", 0)]
    result += list(itertools.product((0.05, 0.1, 0.2), (1, 5, 20), ("no", "yes"), (0,)))
    result += [(0.4, 1, check, 0) for check in ("no", "yes")]
    result += [(0.1, 100, check, 0) for check in ("no", "yes")]
    result += [(0.1, 5, check, 10) for check in ("no", "yes")]
    return list(dict.fromkeys(result))


def key(policy):
    skin, every, check, delay = policy
    return f"skin{skin:g}_every{every}_check{check}_delay{delay}"


def contact_keys(contacts, count):
    ids = np.sort(contacts[:, 6:8].astype(np.int64), axis=1)
    return np.unique(ids[:, 0] * (count + 1) + ids[:, 1])


def geometric_contacts(positions, radii, lengths):
    # Independent exhaustive candidate search, with periodic minimum images.
    x = positions % lengths
    pairs = cKDTree(x, boxsize=lengths).query_pairs(2 * radii.max(), output_type="ndarray")
    branch = x[pairs[:, 0]] - x[pairs[:, 1]]
    branch -= lengths * np.rint(branch / lengths)
    overlap = radii[pairs[:, 0]] + radii[pairs[:, 1]] - np.linalg.norm(branch, axis=1)
    pairs = pairs[overlap > 1e-12 * radii.min()] + 1
    return np.unique(pairs[:, 0] * (len(radii) + 1) + pairs[:, 1])


def write_report(output, results):
    """Summarize medians after all repetitions, using a common scenario reference."""
    lines = ["Perfilado de vecinos de LIGGGHTS", "",
             "Tiempos del cálculo nativo, excluyendo inicialización, observaciones, "
             "búsqueda geométrica independiente y escritura. Aceleración = mediana "
             "de la referencia / mediana de la variante. Errores máximos en los pasos muestreados.", "",
             "Posición: máximo error euclídeo por partícula / radio mínimo, con imagen mínima periódica. "
             "Fuerzas: norma L2 del error / norma L2 de referencia. Presión: error relativo absoluto. "
             "Contactos distintos: diferencia simétrica de pares respecto de la referencia. "
             "Omitidos: contactos geométricos solapados ausentes en la lista observada, "
             "para la propia trayectoria de la variante.", ""]
    grouped = {}
    for result in results:
        grouped.setdefault((result["scenario"], tuple(result["policy"])), []).append(result)
    baseline = (0.1, 1, "no", 0)
    for scenario in ("fixed", "deformation"):
        base = [r["native_seconds"] for r in grouped.get((scenario, baseline), []) if not r.get("failed")]
        if not base:
            continue
        base_time = float(np.median(base))
        lines += [f"Escenario: {scenario}", "",
                  "| skin/rmin | every | check | delay | rep. | s nativos (mediana) | aceleración | reconstrucciones | error posición/rmin | error fuerzas | error presión | contactos distintos | omitidos |",
                  "|---:|---:|:---:|---:|---:|---:|---:|:---:|---:|---:|---:|---:|---:|"]
        for (scene, policy), runs in grouped.items():
            if scene != scenario:
                continue
            successful = [r for r in runs if not r.get("failed")]
            if not successful:
                lines.append(f"| {policy[0]} | {policy[1]} | {policy[2]} | {policy[3]} | 0 | FAIL | | | | | | | |")
                continue
            med = float(np.median([r["native_seconds"] for r in successful]))
            errors = {name: max(r.get("max_errors", {}).get(name, 0) for r in successful)
                      for name in ("positions_relative", "forces_relative", "pressure_relative", "contact_symmetric_difference")}
            rebuilds = [r["rebuilds"] for r in successful]
            lines.append(f"| {policy[0]:g} | {policy[1]} | {policy[2]} | {policy[3]} | {len(successful)} | "
                         f"{med:.3f} | {base_time / med:.2f}× | {min(rebuilds)}–{max(rebuilds)} | "
                         f"{errors['positions_relative']:.3e} | {errors['forces_relative']:.3e} | "
                         f"{errors['pressure_relative']:.3e} | {errors['contact_symmetric_difference']} | "
                         f"{max(r['max_missing_contacts'] for r in successful)} |")
        lines += [""]
    lines += ["La referencia inicial tiene errores cero por definición. Las repeticiones posteriores "
              "de la referencia se comparan también contra su primera ejecución. "
              "Ausencia de contactos omitidos en las muestras no descarta omisiones entre muestras. "
              "La deformación prescrita comprime a −2 s⁻¹ durante el primer 75 % de pasos y "
              "expande a +2 s⁻¹ después. Este perfilado no demuestra equivalencia en otros estados "
              "ni en servos con realimentación.", ""]
    (output / "report.md").write_text("\n".join(lines))


def worker(args):
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    execution = json.loads(args.input.joinpath("execution.json").read_text())
    execution["options"]["threads"] = args.threads
    library_path = Path(execution["options"]["library"])
    skin, every, check, delay = json.loads(args.policy)
    original = args.input.joinpath("in.liggghts").read_text()
    original_skin = float(re.search(r"^neighbor (\S+) bin", original, re.M)[1])
    skin_value = original_skin * skin / 0.1
    commands = re.sub(r"^neighbor .*", f"neighbor {skin_value:.17g} bin", original, flags=re.M)
    commands = re.sub(r"^neigh_modify .*", f"neigh_modify delay {delay} every {every} check {check}", commands, flags=re.M)
    commands = commands.replace("../input/particles.data", f'"{args.input / "particles.data"}"')
    folder.joinpath("in.liggghts").write_text(commands)
    library = Library(library_path, args.threads, log=str(folder / "liggghts.log"))
    for line in commands.splitlines():
        if line.strip():
            library.command(line)
    library.expected_count = library.count()
    adapter = LiggghtsProtocolAdapter(library, execution, np.load(args.input / "particle_ids.npy"))
    ago = C.cast(library.lib.lammps_extract_global(library.handle, b"ago"), C.POINTER(C.c_int))
    reference = np.load(args.reference) if args.reference else None
    samples, snapshots, native_seconds, observation_seconds = [], {}, 0.0, 0.0
    rebuilds, max_age = 0, 0
    requested = {"pressure", "kinetic_energy", "mean_coordination_number", "unbalanced_force", "thermal_conductivity"}
    start = time.perf_counter()
    for step in range(1, args.steps + 1):
        # Prescribed compression followed by unloading: same cell path in all trials.
        if args.scenario == "deformation":
            rate = -2.0 if step <= args.steps * 3 // 4 else 2.0
            lengths = adapter.lengths * np.exp(rate * execution["dt"])
            origin = adapter.origin + (adapter.lengths - lengths) / 2
            adapter.library.set_cell(origin, lengths)
            adapter.origin, adapter.lengths = origin, lengths
        tick = time.perf_counter()
        library.advance()
        native_seconds += time.perf_counter() - tick
        rebuilds += int(ago[0] == 0)
        max_age = max(max_age, ago[0])
        if step % args.sample_every and step != args.steps:
            continue
        tick = time.perf_counter()
        arrays = dict(adapter.arrays())
        order = np.argsort(library.atom("id", integer=True))
        arrays["forces"] = library.atom("f", columns=3)[order].copy()
        arrays["torques"] = library.atom("torque", columns=3)[order].copy()
        obs = adapter.observe(requested)
        contacts = contact_keys(library.contacts(), library.count())
        geometric = geometric_contacts(arrays["positions"], arrays["radii"], adapter.lengths)
        sample = {"step": step, "observables": obs,
                  "geometric_contacts": len(geometric),
                  "missing_geometric_contacts": len(np.setdiff1d(geometric, contacts)),
                  "native_contacts": len(contacts), "errors": {}}
        if reference is None:
            for name in ("positions", "velocities", "angular_velocities", "forces", "torques"):
                snapshots[f"{step}_{name}"] = arrays[name]
            snapshots[f"{step}_contacts"] = contacts
            snapshots[f"{step}_lengths"] = adapter.lengths.copy()
            snapshots[f"{step}_observables"] = np.array([obs["pressure"], obs["kinetic_energy"], obs["mean_coordination_number"], obs["unbalanced_force"], *np.ravel(obs["thermal_conductivity"])])
        else:
            errors = sample["errors"]
            for name in ("positions", "velocities", "angular_velocities", "forces", "torques"):
                ref = reference[f"{step}_{name}"]
                diff = arrays[name] - ref
                if name == "positions":
                    diff -= adapter.lengths * np.rint(diff / adapter.lengths)
                errors[name + "_max_abs"] = float(np.max(np.abs(diff)))
                scale = arrays["radii"].min() if name == "positions" else max(float(np.linalg.norm(ref)), 1e-30)
                errors[name + "_relative"] = float(np.max(np.linalg.norm(diff, axis=1)) / scale) if name == "positions" else float(np.linalg.norm(diff) / scale)
            errors["contact_symmetric_difference"] = len(np.setxor1d(contacts, reference[f"{step}_contacts"]))
            actual = np.array([obs["pressure"], obs["kinetic_energy"], obs["mean_coordination_number"], obs["unbalanced_force"], *np.ravel(obs["thermal_conductivity"])])
            ref = reference[f"{step}_observables"]
            for i, name in enumerate(("pressure", "kinetic_energy", "mean_coordination_number", "unbalanced_force")):
                errors[name + "_relative"] = float(abs(actual[i] - ref[i]) / max(abs(ref[i]), 1e-30))
            errors["thermal_relative"] = float(np.linalg.norm(actual[4:] - ref[4:]) / max(np.linalg.norm(ref[4:]), 1e-30))
        samples.append(sample)
        observation_seconds += time.perf_counter() - tick
    elapsed = time.perf_counter() - start
    library.close()
    if reference is None:
        np.savez_compressed(folder / "reference.npz", **snapshots)
    maxima = {name: max(s["errors"].get(name, 0) for s in samples) for name in (samples[-1]["errors"] if reference is not None else [])}
    result = {"scenario": args.scenario, "policy": [skin, every, check, delay], "skin_m": skin_value,
              "steps": args.steps, "dt": execution["dt"], "particles": len(arrays["ids"]),
              "threads": args.threads, "native_seconds": native_seconds, "loop_seconds": elapsed,
              "observation_seconds": observation_seconds, "rebuilds": rebuilds, "max_age": max_age,
              "max_missing_contacts": max(s["missing_geometric_contacts"] for s in samples),
              "max_errors": maxima, "samples": samples}
    folder.joinpath("result.json").write_text(json.dumps(result, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Existing backend/liggghts/input directory")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--sample-every", type=int, default=50)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--policies", help="Optional JSON array of [skin/rmin, every, check, delay]")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--scenario", choices=("fixed", "deformation"))
    parser.add_argument("--policy")
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    args.input = args.input.resolve()
    if min(args.steps, args.sample_every, args.threads, args.repeats) < 1:
        parser.error("steps, sample-every, threads and repeats must be positive")
    if args.worker:
        worker(args)
        return
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    selected = json.loads(args.policies) if args.policies else policies()
    baseline = [0.1, 1, "no", 0]
    selected = [baseline] + [p for p in selected if list(p) != baseline]
    manifest = {"created_utc": datetime.now(timezone.utc).isoformat(),
                "platform": platform.platform(), "python": sys.version,
                "cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
                "deformation": {"rate_per_second": [-2.0, 2.0], "switch_fraction": 0.75},
                "input": str(args.input), "steps": args.steps, "sample_every": args.sample_every,
                "threads": args.threads, "repeats": args.repeats,
                "input_hashes": {name: hashlib.sha256((args.input / name).read_bytes()).hexdigest()
                                 for name in ("in.liggghts", "particles.data", "execution.json")},
                "runtime": runtime_provenance(json.loads((args.input / "execution.json").read_text())["options"]["library"])}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    env = dict(os.environ, OMP_NUM_THREADS=str(args.threads), OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    results = []
    for scenario in ("fixed", "deformation"):
        reference = args.output / scenario / (key(baseline) + "_rep1") / "reference.npz"
        baseline_times = []
        for repetition in range(1, args.repeats + 1):
            # Alternate traversal to reduce monotonic drift in timing comparisons.
            ordered = selected if repetition % 2 else [baseline] + selected[:0:-1]
            for policy in ordered:
                dest = args.output / scenario / (key(policy) + f"_rep{repetition}")
                command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--input", str(args.input),
                           "--output", str(dest), "--steps", str(args.steps), "--sample-every", str(args.sample_every),
                           "--threads", str(args.threads), "--scenario", scenario, "--policy", json.dumps(policy)]
                if list(policy) != baseline or repetition != 1:
                    command += ["--reference", str(reference)]
                tick = time.perf_counter()
                process = subprocess.run(command, env=env, capture_output=True, text=True)
                if process.returncode:
                    dest.mkdir(parents=True, exist_ok=True)
                    (dest / "failure.log").write_text(process.stdout + process.stderr)
                    result = {"scenario": scenario, "policy": policy, "repetition": repetition,
                              "failed": True, "returncode": process.returncode}
                else:
                    result = json.loads((dest / "result.json").read_text())
                    result["repetition"] = repetition
                    if list(policy) == baseline:
                        baseline_times.append(result["native_seconds"])
                    result["speedup"] = float(np.median(baseline_times)) / result["native_seconds"]
                results.append(result)
                (args.output / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
                print(f"{scenario} {key(policy)} rep{repetition}: "
                      f"{process.returncode=}, elapsed={time.perf_counter()-tick:.2f}s, "
                      f"native={result.get('native_seconds', 0):.2f}s, "
                      f"rebuilds={result.get('rebuilds')}, missing={result.get('max_missing_contacts')}", flush=True)
    write_report(args.output, results)


if __name__ == "__main__":
    main()
