#!/usr/bin/env python3
"""
prepare_phase2.py
=================
Crea la cartella phase2/ come sottocartella di Phase 1, copia i file
necessari, sostituisce la geometria della FW con quella estratta dal
Phase 1 (via extract_last_sane.py), e modifica i dictionary per il
fine-tuning con steepestDescent + maxInitChange fisso piccolo.

Modifiche applicate a phase2/:
  - constant/triSurface/FW.obj             : geometria ottimizzata da Phase 1
  - constant/triSurface/attacchini_guide.obj: copiato da Phase 1 (se esiste)
  - constant/dynamicMeshDict               : lowerCpBounds Y_min = 0
  - system/optimisationDict :
      * method conjugateGradient -> steepestDescent (no sub-dict)
      * maxInitChange : valore suggerito da Phase 1 summary
  - system/controlDict : startFrom startTime, startTime 0, endTime 60
  - runOpt2 : nuovo script mesha + topoSet + adjoint (no preProcessor)

Uso:
  python3 prepare_phase2.py --phase1 /path/to/phase1 --phase2 /path/to/phase1/phase2
"""

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path


# ============================================================
#  Template del runOpt2 (scritto nel phase2/)
# ============================================================

RUNOPT2_TEMPLATE = r"""#!/bin/bash
# =============================================================================
# runOpt2 — Phase 2: rimesha sulla geometria ottimizzata di Phase 1, poi
# lancia adjointOptimisationFoam con steepestDescent per il fine-tuning
# fino a convergenza vera. CON WATCHDOG.
#
# Generato automaticamente da prepare_phase2.py.
# NON usa preProcessor.py — la geometria e' gia' nella forma finale di
# Phase 1, niente trasformazioni di pitch/roll/yaw da applicare.
#
# NOTA: niente 'set -e' — in caso di crash del solver vogliamo comunque
# eseguire reconstruction + estrazione STL di quello che esiste.
# =============================================================================

echo ""
echo "=== PHASE 2 START: $(date +%d\ %h\ %Y,\ %H:%M:%S) ==="
echo ""

# ---------- Sanity check OpenFOAM ----------
if ! command -v adjointOptimisationFoam > /dev/null 2>&1; then
    echo "ERRORE: ambiente OpenFOAM non caricato. Carica bashrc e ritenta."
    exit 1
fi

# ---------- Cores ----------
mock=$(grep 'np' initialConditions | awk '{print $2}')
np=${mock:0:${#mock}-1}
echo "Cores: $np"

# ---------- MESH GENERATION (= runAll, senza preProcessor + senza prompt) ----------
echo ""
echo "--- Mesh generation ---"
rm -fr extendedFeature* constant/triSurface/*.eMesh log_mesh
rm -fr processor* allProcessors allProcessors_mesh
rm -fr constant/polyMesh dynamicCode 0
mkdir -p log_mesh
cp -r orig0 0

echo "  surfaceFeatureExtract..."
surfaceFeatureExtract > log_mesh/01_surfaceFeatures
echo "  blockMesh..."
blockMesh > log_mesh/02_blockMesh
echo "  decomposePar..."
decomposePar -force -latestTime > log_mesh/03_decomposePar
echo "  snappyHexMesh..."
mpirun -np $np snappyHexMesh -overwrite -parallel > log_mesh/05_snappy
echo "  checkMesh..."
mpirun -np $np checkMesh -allTopology -allGeometry -parallel > log_mesh/06_checkMesh
echo "  reconstructParMesh..."
reconstructParMesh -constant -fullMatch -mergeTol 1e-10 > log_mesh/07_reconstructParMesh
reconstructPar -constant -withZero -fields '(cellLevel pointLevel nSurfaceLayers thickness thicknessFraction)' > log_mesh/08_reconstructParBC

mkdir -p allProcessors_mesh
mv processor* allProcessors_mesh/ 2>/dev/null || true

# ---------- ADJOINT OPTIMIZATION ----------
echo ""
echo "--- Adjoint optimisation (SD fine-tuning) ---"
rm -fr [0-9]* processor* log_solve postProcessing VTK Export_CAD
cp -r orig0 0
mkdir -p log_solve Export_CAD

# TOPOSET — crea frozenPoints (attacchini rigidi) + fw_wake (cellZone
# per powerDissipation). Prerequisito: constant/triSurface/attacchini_guide.obj
# gia' presente. Le zone create in constant/polyMesh/ verranno propagate
# ai processor dal successivo decomposePar.
echo "  topoSet (frozenPoints + fw_wake)..."
topoSet -case . > log_solve/00_topoSet 2>&1
if grep -q "FATAL\|ERROR" log_solve/00_topoSet; then
    echo "  --> ERROR nel topoSet, controlla log_solve/00_topoSet"
    exit 1
fi

echo "  decomposePar..."
decomposePar > log_solve/01_decomposePar
echo "  renumberMesh..."
mpirun -np $np renumberMesh -overwrite -latestTime -parallel > log_solve/02_renumberMesh
echo "  potentialFoam..."
mpirun -np $np potentialFoam -parallel > log_solve/03_potentialFoam

# ---------- ADJOINT + WATCHDOG ----------
# Il watchdog sorveglia il log e ferma il run in modo pulito se:
# merit in deriva (K2/K3), line search bloccata (K4), mesh runaway (K5),
# mesh degradata Failed>=3 o skew>9 (K6). Motivo in WATCHDOG_STOP.txt.
echo "  adjointOptimisationFoam (Phase 2 fine-tuning, con watchdog)..."
rm -f WATCHDOG_STOP.txt
mpirun -np $np adjointOptimisationFoam -parallel > log_solve/04_adjointOpt &
SOLVER_PID=$!
python3 ../scripts/watchdog.py --log log_solve/04_adjointOpt \
    --pid $SOLVER_PID --case . > log_solve/00_watchdog 2>&1 &
WATCHDOG_PID=$!
wait $SOLVER_PID
SOLVER_RC=$?
kill $WATCHDOG_PID 2>/dev/null
if [ -f WATCHDOG_STOP.txt ]; then
    echo ""
    echo "  *** PHASE 2 FERMATA DAL WATCHDOG ***"
    cat WATCHDOG_STOP.txt
fi
echo "  --> solver rc=$SOLVER_RC"

# Ripristina stopAt endTime se il watchdog l'ha cambiato
if grep -q "stopAt.*writeNow" system/controlDict; then
    sed -i 's/stopAt\s\+writeNow\s*;/stopAt          endTime;/' system/controlDict
fi

echo "  reconstructParMesh + reconstructPar..."
reconstructParMesh -constant > log_solve/05_reconstructParMesh
reconstructParMesh -fullMatch -mergeTol 1e-10 >> log_solve/05_reconstructParMesh
reconstructPar > log_solve/06_reconstructPar

# ---------- ESTRAZIONE STL FINALE ----------
echo ""
echo "--- Extract final STL ---"
T_OPT=$(foamListTimes -noFunctionObjects 2>/dev/null | sort -n | tail -1)
if [ -z "$T_OPT" ] || [ "$T_OPT" = "0" ]; then
    T_OPT=$(ls -d [0-9]*/ 2>/dev/null | sort -n | tail -1 | tr -d '/')
fi
if [ -z "$T_OPT" ] || [ "$T_OPT" = "0" ]; then
    echo "ERRORE: impossibile determinare T_OPT (no timestep ricostruiti?)"
    exit 1
fi
echo "  optimised timestep: $T_OPT"

mkdir -p Export_CAD/final_split
surfaceMeshExtract -time $T_OPT Export_CAD/final_split/full.stl \
    > log_solve/07_surfaceExport 2>&1
surfaceSplitByPatch Export_CAD/final_split/full.stl \
    >> log_solve/07_surfaceExport 2>&1

# Cerca il file della patch DP_FW
cp Export_CAD/final_split/full_DP_FW.stl Export_CAD/FrontWing_Final.stl 2>/dev/null || \
cp Export_CAD/final_split/full_6.stl Export_CAD/FrontWing_Final.stl 2>/dev/null || \
echo "WARNING: STL della FW finale non trovata, controlla Export_CAD/final_split/"

echo ""
echo "Output finale: $(pwd)/Export_CAD/FrontWing_Final.stl"

mkdir -p allProcessors
mv processor* allProcessors/ 2>/dev/null || true

touch ended.txt
echo ""
echo "=== PHASE 2 END: $(date +%d\ %h\ %Y,\ %H:%M:%S) ==="
"""


# ============================================================
#  Helpers
# ============================================================

def copy_phase1_to_phase2(phase1, phase2):
    """
    Copia da phase1/ a phase2/ TUTTO tranne:
      - timestep [0-9]*
      - processor*, allProcessors, allProcessors_mesh
      - log_solve, log_mesh
      - phase2 stesso (per evitare ricorsione)
      - constant/polyMesh (la mesh va rigenerata da snappy)
      - constant/triSurface/* (lo sostituiremo con la STL ottimizzata + attacchini)
      - preProcessor.py, setup.txt, setup_UBJ_LBJ.txt (no preProcessor in Phase 2)
      - optimisation/, Export_CAD, Mesh (output dei run precedenti)
      - runOpt, runAll (runOpt2 li rimpiazza)
      - runRestart, runResume, runQueue (non servono)

    NOTA: constant/triSurface_0deg viene copiata (non e' esclusa) come
    riferimento storico, ma in Phase 2 non viene usata (niente preProcessor).
    """
    phase2.mkdir(exist_ok=True)

    # Pattern di esclusione per shutil.ignore_patterns
    EXCLUDES = [
        "phase2", "processor*", "allProcessors*",
        "log_solve", "log_mesh",
        "polyMesh",
        "preProcessor.py", "setup.txt", "setup_UBJ_LBJ.txt",
        "optimisation", "Export_CAD", "Mesh",
        "runOpt", "runAll", "runRestart", "runResume", "runQueue",
        "ended.txt", "*.bak",
    ]

    def ignore_func(d, names):
        ignored = set()
        for name in names:
            # Escludi timestep [0-9]+
            if re.fullmatch(r"[0-9]+(\.[0-9]+)?", name):
                ignored.add(name)
                continue
            # Escludi pattern
            for pattern in EXCLUDES:
                # match esatto o glob-like
                if pattern == name:
                    ignored.add(name)
                    break
                if "*" in pattern:
                    import fnmatch
                    if fnmatch.fnmatch(name, pattern):
                        ignored.add(name)
                        break
        return ignored

    # Copia ricorsiva tutto eccetto pattern di esclusione e timestep
    for item in phase1.iterdir():
        if item.name == phase2.name and item.parent == phase2.parent:
            continue  # non copiare phase2 dentro phase2
        dst = phase2 / item.name
        # Filtri di esclusione top-level
        skip = False
        for pattern in EXCLUDES:
            import fnmatch
            if fnmatch.fnmatch(item.name, pattern):
                skip = True
                break
        if re.fullmatch(r"[0-9]+(\.[0-9]+)?", item.name):
            skip = True
        if skip:
            continue
        if item.is_dir():
            shutil.copytree(item, dst, dirs_exist_ok=True, ignore=ignore_func)
        else:
            shutil.copy2(item, dst)

    # Svuota constant/triSurface (sara' popolato con la FW.obj ottimizzata +
    # attacchini_guide.obj copiato da phase1)
    tri_dir = phase2 / "constant" / "triSurface"
    if tri_dir.exists():
        for f in tri_dir.iterdir():
            if f.is_file():
                f.unlink()
            elif f.is_dir():
                shutil.rmtree(f)
    else:
        tri_dir.mkdir(parents=True, exist_ok=True)


def install_stl_as_obj(stl_path, phase2):
    """Converte STL → OBJ con surfaceConvert e lo mette in triSurface/FW.obj.

    Inoltre rimuove le directive 'o NAME' / 'g NAME' dall'OBJ. Senza questa
    pulizia, snappyHexMesh comporrebbe il nome del patch come
    <nomeGeometria>_<nomeRegion> = 'DP_FW_DP_FW' invece del semplice 'DP_FW',
    rompendo la corrispondenza con le BC nei file 0/*.
    """
    target = phase2 / "constant" / "triSurface" / "FW.obj"
    target.parent.mkdir(parents=True, exist_ok=True)

    print(f"  surfaceConvert {stl_path} -> {target}")
    subprocess.run(
        ["surfaceConvert", str(stl_path), str(target)],
        check=True,
    )
    if not target.exists():
        raise RuntimeError(f"surfaceConvert non ha creato {target}")

    # Strippa le directive 'o'/'g' dall'OBJ per evitare patch composti
    print(f"  pulizia regioni interne dell'OBJ (evita patch 'DP_FW_DP_FW')...")
    content = target.read_text()
    n_before = len(re.findall(r"^[og]\s+\S+\s*$", content, flags=re.MULTILINE))
    content = re.sub(r"^[og]\s+\S+\s*$", "", content, flags=re.MULTILINE)
    content = re.sub(r"\n{2,}", "\n", content)
    target.write_text(content)
    print(f"    rimosse {n_before} directive o/g")

    return target


def copy_attacchini_guide(phase1, phase2):
    """
    Copia constant/triSurface/attacchini_guide.obj da Phase 1 a Phase 2.

    L'attacchini_guide.obj in Phase 1 e' gia' stato ruotato/traslato dal
    preProcessor.py (assumendo che il preProcessor sia stato modificato
    per applicare le trasformazioni anche agli attacchini). Quindi la
    posizione e' gia' quella "post-setup" e coincide con la posizione
    della FW ottimizzata estratta al cycle 27.

    NON copiamo dalla triSurface_0deg perche' quella e' la posizione
    "neutra" (0 gradi tutti gli assi) e non corrisponderebbe alla FW
    ottimizzata dopo Phase 1.
    """
    src = phase1 / "constant" / "triSurface" / "attacchini_guide.obj"
    dst = phase2 / "constant" / "triSurface" / "attacchini_guide.obj"
    if not src.exists():
        print(f"  Warning: {src} non trovato — Phase 2 NON avra' frozenPoints "
              f"(topoSet fallira' su attacchini_guide.obj mancante). Assicurati "
              f"di aver messo attacchini_guide.obj in triSurface_0deg PRIMA "
              f"di lanciare Phase 1.")
        return None
    print(f"  copio attacchini_guide.obj da Phase 1 -> Phase 2 (post-setup)")
    shutil.copy2(src, dst)
    return dst


def modify_optimisationDict(phase2, maxinit):
    """
    Sostituisce method conjugateGradient (+ sub-dict) con steepestDescent,
    aggiorna maxInitChange e rilassa il convergence criterion da 1e-4 a 1e-3
    (= 0.1% invece di 0.01%). Phase 2 con SD e' molto lento vicino al minimo:
    1e-3 evita di buttare cycle in cui il drag cambia di pochi 1e-5.
    """
    opt_path = phase2 / "system" / "optimisationDict"
    content = opt_path.read_text()

    # 1) Sostituisci maxInitChange
    content = re.sub(
        r"maxInitChange\s+[\d.eE+-]+\s*;",
        f"maxInitChange   {maxinit:.4e};   // Phase 2 — fisso da prepare_phase2.py",
        content,
        count=1,
    )

    # 1b) Rilassa convergence criterion da 1e-4 a 1e-3 (0.01% -> 0.1%)
    content = re.sub(
        r"(\bobjective\s+)1\.?e?-?0?4(\s*;)",
        r"\g<1>1.e-3\g<2>",
        content,
    )
    content = re.sub(
        r"(\bdesignVariables\s+)1\.?e?-?0?4(\s*;)",
        r"\g<1>1.e-3\g<2>",
        content,
    )

    # 2) Sostituisci updateMethod block.
    # Cerchiamo da "updateMethod\s*{" fino alla graffa di chiusura corrispondente.
    new_update = """    updateMethod
    {
        // Phase 2 — steepestDescent per fine-tuning.
        // Motivo: vicino al minimo, CG (anche PR+) e' fragile per
        // instabilita' numerica della formula di beta (|g_prev|^2 al
        // denominatore diventa piccolo, fluttuazioni FP esplodono).
        // SD non usa beta, e' lento ma garantisce stabilita'.
        method          steepestDescent;

        lineSearch
        {
            type        ArmijoConditions;
            minStep     0.05;
            maxIters    8;
            c1          1.e-4;
            ratio       0.7;
        }
    }"""

    # Trova start di "updateMethod"
    start_match = re.search(r"\bupdateMethod\s*\{", content)
    if not start_match:
        raise ValueError("Non trovo il blocco updateMethod nell'optimisationDict")
    start = start_match.start()
    # Conta graffe per trovare la chiusura
    depth = 0
    i = start
    while i < len(content):
        ch = content[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
        i += 1
    else:
        raise ValueError("graffe di updateMethod sbilanciate")

    content = content[:start] + new_update + content[end:]
    opt_path.write_text(content)


def modify_dynamicMeshDict(phase2):
    """lowerCpBounds Y_min = 0 (sul piano di simmetria)."""
    dyn_path = phase2 / "constant" / "dynamicMeshDict"
    if not dyn_path.exists():
        print(f"  (constant/dynamicMeshDict non esiste, skip)")
        return
    content = dyn_path.read_text()

    def replace_y(match):
        x_lo = match.group(1)
        z_lo = match.group(3)
        return f"lowerCpBounds       ({x_lo}  0.0  {z_lo})"

    new_content = re.sub(
        r"lowerCpBounds\s+\(\s*([\-\d.eE+]+)\s+([\-\d.eE+]+)\s+([\-\d.eE+]+)\s*\)",
        replace_y,
        content,
        count=1,
    )
    if new_content == content:
        print(f"  Warning: lowerCpBounds non trovato/modificato in dynamicMeshDict")
    dyn_path.write_text(new_content)


def modify_controlDict(phase2):
    """startFrom startTime, startTime 0, endTime 60."""
    cd_path = phase2 / "system" / "controlDict"
    content = cd_path.read_text()
    content = re.sub(r"startFrom\s+\w+\s*;", "startFrom       startTime;", content, count=1)
    content = re.sub(r"^\s*startTime\s+[\d.eE+-]+\s*;",
                     "startTime       0;", content, count=1, flags=re.MULTILINE)
    content = re.sub(r"endTime\s+[\d.eE+-]+\s*;",
                     "endTime         60;", content, count=1)
    cd_path.write_text(content)


def write_runOpt2(phase2):
    target = phase2 / "runOpt2"
    target.write_text(RUNOPT2_TEMPLATE)
    # chmod +x
    st = os.stat(target)
    os.chmod(target, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


# ============================================================
#  Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--phase1", required=True, help="Path Phase 1 case")
    parser.add_argument("--phase2", required=True, help="Path Phase 2 case (verra' creato)")
    args = parser.parse_args()

    phase1 = Path(args.phase1).resolve()
    phase2 = Path(args.phase2).resolve()

    summary_path = phase1 / "Export_CAD" / "phase1_summary.json"
    if not summary_path.exists():
        sys.exit(f"ERRORE: {summary_path} non trovato. "
                 f"Lancia prima extract_last_sane.py.")

    summary = json.loads(summary_path.read_text())
    stl_path = Path(summary["stl_path"])
    maxinit = summary["phase2_maxinit_recommended"]

    print(f"=== Prepare Phase 2 ===")
    print(f"  Phase 1: {phase1}")
    print(f"  Phase 2: {phase2}")
    print(f"  STL sorgente: {stl_path}")
    print(f"  maxInit Phase 2: {maxinit:.4e}")
    print()

    if phase2.exists() and any(phase2.iterdir()):
        ans = input(f"  {phase2} esiste e non e' vuota. Cancellare e rifare? [y/N]: ")
        if ans.strip().lower() == "y":
            shutil.rmtree(phase2)
        else:
            sys.exit("Aborto.")

    print("  Copio Phase 1 -> Phase 2 (escludendo timestep, processor, log)...")
    copy_phase1_to_phase2(phase1, phase2)

    print("  Installo STL ottimizzata come constant/triSurface/FW.obj...")
    install_stl_as_obj(stl_path, phase2)

    print("  Copio attacchini_guide.obj (per topoSet frozenPoints in Phase 2)...")
    copy_attacchini_guide(phase1, phase2)

    print("  Modifico optimisationDict (SD + maxInitChange + convergence 1e-3)...")
    modify_optimisationDict(phase2, maxinit)

    print("  Modifico dynamicMeshDict (Y_min = 0)...")
    modify_dynamicMeshDict(phase2)

    print("  Modifico controlDict (startFrom startTime, endTime 60)...")
    modify_controlDict(phase2)

    print("  Scrivo runOpt2 (con topoSet + adjoint)...")
    write_runOpt2(phase2)

    print()
    print(f"=== Phase 2 pronto in {phase2} ===")
    print(f"Avvia con:  cd {phase2} && ./runOpt2")


if __name__ == "__main__":
    main()
