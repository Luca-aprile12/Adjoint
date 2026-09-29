#!/usr/bin/env python3
"""
extract_last_sane.py v2
=======================
Parsa log_solve/04_adjointOpt, identifica l'ultimo cycle sano ed estrae la
STL della front wing a quel timestep.

CRITERIO DI "ESPLOSIONE" (rivisto dopo il run Phase2/39-cycle):
  Un cycle e' esploso se:
    - mesh movement > 5 x maxInitChange   (era 2x: troppo conservativo —
      spike di 4.6x sono stati gestiti dal line search e il run e'
      proseguito per altri 20 cycle di miglioramento)
    OPPURE
    - il checkMesh post-morphing di quel cycle riporta
      "Failed >= 3 mesh geometry checks"  (mesh realmente rotta)

QUARANTENA invece di cancellazione:
  I timestep > last_sane vengono SPOSTATI in quarantine_postcrash/
  (mai piu' perdere 20 cycle di risultati per una soglia sbagliata).

Output:
  - Export_CAD/FrontWing_Optimised_phase1.stl
  - Export_CAD/phase1_summary.json  (merit_at_last_sane + maxInit Phase 2)

Uso:
  python3 extract_last_sane.py --case /path/to/case
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


# ============================================================
#  Parsing
# ============================================================

def parse_optimisationDict_maxinit(opt_dict_path):
    content = opt_dict_path.read_text()
    content = re.sub(r"//.*", "", content)
    m = re.search(r"maxInitChange\s+([\d.eE+-]+)", content)
    if not m:
        raise ValueError(f"maxInitChange non trovato in {opt_dict_path}")
    return float(m.group(1))


def parse_log(log_path):
    """
    Ritorna lista di dict per cycle:
      {cycle, mesh_movement, merit, failed_checks}
    - mesh_movement: il PRIMO movement del cycle (lo step proposto)
    - merit: primo "Weighted objective" stampato nel cycle (= valore
      convergiuto del cycle precedente / merit corrente)
    - failed_checks: max "Failed N mesh geometry checks" nel cycle
    """
    cycle_re = re.compile(r"Optimisation cycle (\d+)")
    move_re = re.compile(r"Max mesh movement magnitude\s+([\d.eE+-]+)")
    merit_re = re.compile(r"Weighted objective\s*:\s*([-\d.eE+]+)")
    failed_re = re.compile(r"Failed (\d+) mesh geometry checks")

    cycles = []
    current = None

    with open(log_path, errors="ignore") as f:
        for line in f:
            m = cycle_re.search(line)
            if m:
                if current is not None:
                    cycles.append(current)
                current = {
                    "cycle": int(m.group(1)),
                    "mesh_movement": None,
                    "merit": None,
                    "failed_checks": 0,
                }
                continue
            if current is None:
                continue
            m = move_re.search(line)
            if m and current["mesh_movement"] is None:
                current["mesh_movement"] = float(m.group(1))
                continue
            m = merit_re.search(line)
            if m and current["merit"] is None:
                current["merit"] = float(m.group(1))
                continue
            m = failed_re.search(line)
            if m:
                current["failed_checks"] = max(
                    current["failed_checks"], int(m.group(1)))

    if current is not None:
        cycles.append(current)
    return cycles


# ============================================================
#  Identificazione last sane
# ============================================================

def find_last_sane(cycles, movement_threshold, max_failed=3):
    """
    Ultimo cycle prima del primo cycle "esploso".
    Esploso = movement > threshold OPPURE failed_checks >= max_failed.
    """
    last_sane = None
    exploded_at = None
    for c in cycles:
        mov = c["mesh_movement"]
        if mov is None:
            continue  # cycle troncato (log finito a meta')
        if mov > movement_threshold or c["failed_checks"] >= max_failed:
            exploded_at = c["cycle"]
            break
        last_sane = c["cycle"]
    return last_sane, exploded_at


def find_best_sane(cycles, last_sane):
    """
    Tra i cycle sani, quello col MERIT MINIMO — non l'ultimo.

    Lezione del run 01/08: il solver puo' accettare step peggiorativi
    ("Proceeding" dopo line search fallita), quindi l'ultimo cycle sano
    puo' essere PEGGIORE di uno precedente. Il merit stampato all'inizio
    del cycle N si riferisce alla geometria salvata al timestep N-1,
    quindi: best merit al cycle N -> estrai timestep N-1.

    Ritorna (timestep_da_estrarre, merit) oppure (last_sane, None) come
    fallback se i merit non sono parsabili.
    """
    best_cycle = None
    best_merit = None
    for c in cycles:
        if c["merit"] is None:
            continue
        # la geometria corrispondente e' il timestep c["cycle"] - 1;
        # deve essere sano e >= 1 (0 = baseline, inutile estrarla)
        t_geom = c["cycle"] - 1
        if t_geom < 1 or (last_sane is not None and t_geom > last_sane):
            continue
        if best_merit is None or c["merit"] < best_merit:
            best_merit = c["merit"]
            best_cycle = t_geom
    if best_cycle is None:
        return last_sane, None
    return best_cycle, best_merit


def compute_phase2_maxinit(cycles, last_sane, n_average=5, floor=5e-4):
    sane = [c for c in cycles
            if c["cycle"] <= last_sane and c["mesh_movement"] is not None]
    last_n = sane[-n_average:] if len(sane) >= n_average else sane
    if not last_n:
        return floor
    avg = sum(c["mesh_movement"] for c in last_n) / len(last_n)
    return max(floor, 0.5 * avg)


# ============================================================
#  Quarantena timestep post-crash (NON distruttiva)
# ============================================================

def quarantine_post_crash_timesteps(case_dir, last_sane):
    """
    SPOSTA (non cancella) tutti i timestep > last_sane in
    quarantine_postcrash/<timestamp>/ preservando la struttura.
    Include root, processor*, allProcessors/processor*,
    allProcessors_mesh/processor* e i control points dei cycle esplosi.
    """
    case_dir = Path(case_dir).resolve()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    qroot = case_dir / "quarantine_postcrash" / stamp
    moved = []

    def is_post(p):
        if not p.is_dir():
            return False
        if not re.fullmatch(r"\d+(\.\d+)?", p.name):
            return False
        try:
            return float(p.name) > last_sane
        except ValueError:
            return False

    def move_to_quarantine(src):
        rel = src.relative_to(case_dir)
        dst = qroot / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        moved.append(str(rel))

    # 1) root
    for p in sorted(case_dir.iterdir()):
        if is_post(p):
            move_to_quarantine(p)

    # 2) processor dirs (attivi e archiviati)
    for pattern in ("processor*", "allProcessors/processor*",
                    "allProcessors_mesh/processor*"):
        for proc_dir in case_dir.glob(pattern):
            if not proc_dir.is_dir():
                continue
            for p in sorted(proc_dir.iterdir()):
                if is_post(p):
                    move_to_quarantine(p)

    # 3) control points dei cycle esplosi
    cps_dir = case_dir / "optimisation" / "controlPoints"
    if cps_dir.exists():
        for p in cps_dir.iterdir():
            m = re.search(r"Bsplines(\d+)", p.name)
            if m and int(m.group(1)) > last_sane:
                move_to_quarantine(p)

    return moved, qroot


# ============================================================
#  Estrazione STL
# ============================================================

def extract_stl(case_dir, t_last_good):
    case_dir = Path(case_dir).resolve()
    export_root = case_dir / "Export_CAD"
    export_dir = export_root / "phase1_last_sane"
    export_dir.mkdir(parents=True, exist_ok=True)
    full_stl = export_dir / "full.stl"

    print(f"  surfaceMeshExtract -time {t_last_good} ...")
    subprocess.run(
        ["surfaceMeshExtract", "-time", str(t_last_good), str(full_stl)],
        cwd=str(case_dir), check=True)

    print("  surfaceSplitByPatch ...")
    subprocess.run(["surfaceSplitByPatch", str(full_stl)],
                   cwd=str(case_dir), check=True)

    final_target = export_root / "FrontWing_Optimised_phase1.stl"
    candidates = list(export_dir.glob("full_*.stl"))
    for p in candidates:
        if "DP_FW" in p.name:
            shutil.copy2(p, final_target)
            return final_target
    if candidates:
        biggest = max(candidates, key=lambda p: p.stat().st_size)
        shutil.copy2(biggest, final_target)
        print(f"  Warning: 'DP_FW' non trovato, prendo il piu' grande: {biggest.name}")
        return final_target
    raise FileNotFoundError(f"Nessuna STL trovata in {export_dir}")


# ============================================================
#  Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--case", required=True)
    parser.add_argument("--log", default="log_solve/04_adjointOpt")
    parser.add_argument("--threshold_mult", type=float, default=5.0,
                        help="soglia esplosione = mult * maxInitChange (default 5)")
    parser.add_argument("--max_failed", type=int, default=3,
                        help="Failed >= N = mesh rotta (default 3)")
    args = parser.parse_args()

    case_dir = Path(args.case).resolve()
    log_path = case_dir / args.log
    opt_dict = case_dir / "system" / "optimisationDict"

    if not log_path.exists():
        sys.exit(f"ERRORE: log non trovato: {log_path}")
    if not opt_dict.exists():
        sys.exit(f"ERRORE: optimisationDict non trovato: {opt_dict}")

    maxinit = parse_optimisationDict_maxinit(opt_dict)
    threshold = args.threshold_mult * maxinit

    print(f"Case: {case_dir}")
    print(f"  maxInitChange: {maxinit:.4e} m")
    print(f"  soglia movimento: {threshold:.4e} m ({args.threshold_mult}x)")
    print(f"  soglia mesh rotta: Failed >= {args.max_failed}")

    cycles = parse_log(log_path)
    if not cycles:
        sys.exit("ERRORE: nessun cycle nel log")
    print(f"  cycle trovati: {len(cycles)}")

    last_sane, exploded_at = find_last_sane(cycles, threshold, args.max_failed)
    if last_sane is None:
        sys.exit("ERRORE: nessun cycle sano trovato")

    # BEST sane invece di LAST sane: il solver puo' accettare step
    # peggiorativi, quindi scegliamo il timestep col merit migliore.
    best_timestep, best_merit = find_best_sane(cycles, last_sane)

    print(f"  LAST SANE cycle: {last_sane}")
    print(f"  BEST timestep (merit minimo): {best_timestep} "
          f"(merit {best_merit})")
    if exploded_at:
        print(f"  esplosione rilevata al cycle {exploded_at}")
    else:
        print("  nessuna esplosione (run terminata pulita o per endTime)")
    if best_timestep != last_sane:
        print(f"  NOTA: il best ({best_timestep}) NON e' l'ultimo sano "
              f"({last_sane}) — il run ha accettato step peggiorativi dopo "
              f"il best. Estraggo il best.")

    print(f"\nQuarantena timestep > {best_timestep} (spostati, NON cancellati)...")
    moved, qroot = quarantine_post_crash_timesteps(case_dir, best_timestep)
    if moved:
        print(f"  spostati {len(moved)} elementi in {qroot}")
        for m in moved[:5]:
            print(f"    - {m}")
        if len(moved) > 5:
            print(f"    ... e altri {len(moved) - 5}")
    else:
        print("  niente da mettere in quarantena")

    print(f"\nEstraggo STL del timestep {best_timestep}...")
    stl_path = extract_stl(case_dir, best_timestep)
    print(f"  STL: {stl_path}")

    maxinit_p2 = compute_phase2_maxinit(cycles, best_timestep)
    print(f"\nmaxInit suggerito per la gamba successiva: {maxinit_p2:.4e} m")

    summary = {
        "phase1_maxinit": maxinit,
        "threshold_mesh_movement": threshold,
        "max_failed_checks": args.max_failed,
        "last_sane_cycle": last_sane,
        "best_timestep": best_timestep,
        "merit_at_best": best_merit,
        "exploded_at_cycle": exploded_at,
        "explosion_detected": exploded_at is not None,
        "phase2_maxinit_recommended": maxinit_p2,
        "stl_path": str(stl_path),
        "n_cycles_parsed": len(cycles),
        "quarantine_dir": str(qroot) if moved else None,
    }
    out = case_dir / "Export_CAD" / "phase1_summary.json"
    out.write_text(json.dumps(summary, indent=2))
    print(f"Summary: {out}")


if __name__ == "__main__":
    main()
