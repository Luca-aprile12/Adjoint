#!/usr/bin/env python3
"""
watchdog.py v4 — sorveglia adjointOptimisationFoam e ferma il run se patologico.

Revisione completa, tarata sui log del case half-car con
vincolo di bilanciamento (2 adjointSolver + updateMethod nullSpace) e
retro-compatibile con il case FW (1 adjointSolver + conjugateGradient).

PRINCIPIO DI FONDO: ogni grandezza viene letta da un BLOCCO IDENTIFICATO
PER NOME, mai da "l'ultima riga che assomiglia a...". Tre stop spuri
sono nati esattamente da quella fragilita'. E se un
parsing fallisce, il watchdog LO DICE invece di tacere.

REGOLE
  K1. "FOAM FATAL" nel log                          -> stop immediato
  K2. Merit sopra il best oltre la soglia combinata  -> stop
      soglia = max(RISE_ABS, RISE_REL * |best|)
      Il criterio puramente relativo e' inaffidabile quando la grandezza
      passa vicino allo zero.
  K3. Nessun nuovo best merit da STAGNATION_CYC cycle -> stop
  K4. Line search fallita in MAX_LS_FAILS cycle consecutivi -> stop
  K5. Mesh movement > MOVE_FACTOR * maxInitChange     -> stop
      Soglia RELATIVA: letta dal optimisationDict, cosi' resta valida
      qualunque sia la taratura del passo.
  K6. Mesh degradata                                  -> stop
      - "Failed >= 3 mesh checks" (segnale primario, mesh-indipendente)
      - skewness oltre una soglia relativa al baseline della mesh
  K7. Errore di continuita' > MAX_CONTINUITY          -> stop immediato
  K8. Ripartitore anteriore fuori dai limiti di SICUREZZA -> stop
      Non e' la tolleranza di progetto: quella la impone il vincolo
      nell'optimisationDict. Questa scatta solo se il vincolo non funziona.

Stop "gentile": stopAt writeNow -> attesa -> SIGINT -> SIGKILL.
Motivo scritto in WATCHDOG_STOP.txt.

Uso:
  python3 scripts/watchdog.py --log log_solve/04_adjointOpt --pid <PID> [--case .]
"""

import argparse
import os
import re
import signal
import time
from pathlib import Path

# ----------------------------------------------------------------------------
#  Nomi usati per agganciare i blocchi nel log. Se nell'optimisationDict
#  rinomini l'adjointSolver dell'obiettivo o gli objective, aggiorna QUI.
#  Il watchdog avvisa a schermo se non riesce piu' ad agganciarli.
# ----------------------------------------------------------------------------
OBJ_SOLVER_NAME  = "adjointSolver1"   # adjointSolver dell'OBIETTIVO
OBJ_DRAG         = "drag_car"
OBJ_DOWNFORCE    = "downforce_car"
OBJ_MOMENT       = "balance_monitor"  # momento all'asse anteriore, weight 0
PRIMAL_NAME      = "primal1"

CHECK_INTERVAL   = 300     # secondi fra i controlli
GRACE_SEC        = 600     # attesa dopo lo stop gentile prima di escalare

# --- K2: merit in deriva -----------------------------------------------------
# Il dip recuperabile piu' grande mai osservato e' +12.3% (FW Phase 2, che poi
# ha raggiunto il best assoluto). RISE_REL 0.25 lascia il doppio di margine.
# RISE_ABS evita che il criterio relativo impazzisca se il merit passa vicino
# allo zero. Con i pesi calibrati (alpha_drag 1, alpha_downforce 2.5) il merit
# al baseline vale sempre circa -1.5, quindi 0.30 e' un quinto della scala.
RISE_REL         = 0.25
RISE_ABS         = 0.30

# --- K3: stagnazione ---------------------------------------------------------
# Gap massimo osservato senza nuovo best: 4 cycle (FW Phase 2). nullSpace
# avanza piu' lentamente del CG, quindi 8 invece di 6.
STAGNATION_CYC   = 8
MIN_CYC_FOR_K3   = 8       # non giudicare la stagnazione troppo presto

# --- K4: line search ---------------------------------------------------------
# half-car con nullSpace: 0 fallimenti su 3 cycle. FW Phase 2: 1 su 39.
# 3 invece di 2 perche' con un metodo vincolato non abbiamo ancora statistica.
MAX_LS_FAILS     = 3

# --- K5: mesh movement -------------------------------------------------------
# RELATIVA a maxInitChange, letto dall'optimisationDict. Osservato: movimenti
# pari a maxInitChange in condizioni sane; fino a 9.6x nei runaway del case FW
# (il CG accumula e maxInitChange fissa solo l'eta iniziale). 6x separa i due
# regimi. Il fallback serve solo se il dict non e' leggibile.
MOVE_FACTOR      = 6.0
MOVE_FALLBACK    = 0.05

# --- K6: qualita' mesh -------------------------------------------------------
MAX_FAILED_CHECK = 3
SKEW_FACTOR      = 1.6
SKEW_MARGIN      = 4.0
SKEW_FALLBACK    = 15.0

# --- K7: continuita' ---------------------------------------------------------
# Massimo sano misurato: 2.15e-8 (prime iterazioni del primal). In divergenza:
# 251. La soglia sta quattro ordini sopra il sano e sette sotto il patologico.
MAX_CONTINUITY   = 1.0e-4

# --- K8: limiti di SICUREZZA sul ripartitore ---------------------------------
# La tolleranza di progetto (+-3 punti) e' imposta dal vincolo. Questi limiti
# molto piu' larghi intercettano solo il caso in cui il vincolo non funzioni.
BALANCE_HARD_MIN = 38.0
BALANCE_HARD_MAX = 62.0


# ============================================================================
#  Lettura dei parametri dal case
# ============================================================================

def read_max_init_change(case_dir):
    """maxInitChange dall'optimisationDict, per la soglia relativa di K5."""
    p = Path(case_dir) / "system" / "optimisationDict"
    if not p.exists():
        return None
    try:
        txt = re.sub(r"//.*", "", p.read_text(errors="ignore"))
        m = re.search(r"\bmaxInitChange\s+([\d.eE+-]+)\s*;", txt)
        return float(m.group(1)) if m else None
    except Exception:
        return None


def baseline_skewness(case_dir):
    """Max skewness della mesh appena generata, per la soglia relativa di K6."""
    for name in ("log_mesh/06_checkMesh", "log_mesh/06_checkMeshBlock",
                 "log_mesh/04_checkMeshBlock", "log_checkMesh_serial"):
        p = Path(case_dir) / name
        if not p.exists():
            continue
        try:
            vals = re.findall(r"Max skewness = ([\d.eE+-]+)",
                              p.read_text(errors="ignore"))
        except Exception:
            continue
        if vals:
            return max(float(v) for v in vals)
    return None


def thresholds(case_dir):
    """Calcola le soglie che dipendono dal case. Ritorna anche i valori letti."""
    base_skew = baseline_skewness(case_dir)
    skew_thr = (max(base_skew * SKEW_FACTOR, base_skew + SKEW_MARGIN)
                if base_skew is not None else SKEW_FALLBACK)

    max_init = read_max_init_change(case_dir)
    move_thr = (max_init * MOVE_FACTOR) if max_init is not None else MOVE_FALLBACK

    return {
        "skew": skew_thr, "base_skew": base_skew,
        "move": move_thr, "max_init": max_init,
    }


# ============================================================================
#  Parsing del log
# ============================================================================

def dedup(seq):
    """Rimuove duplicati consecutivi (lo stesso valore ristampato piu' volte)."""
    out = []
    for x in seq:
        if not out or x != out[-1]:
            out.append(x)
    return out


def parse_log(text):
    # ---- merit dell'OBIETTIVO -------------------------------------------
    # Si legge la "Weighted objective" del blocco dell'adjointSolver
    # dell'obiettivo. NON si usa "Old merit function value": con
    # updateMethod nullSpace quella riga riporta la merit del problema
    # VINCOLATO, valori attorno a zero, e ha causato lo stop spurio del
    # 5 set 2026.
    merits_raw = []
    for blk in re.split(r"Adjoint solver\s+", text):
        if blk.startswith(OBJ_SOLVER_NAME):
            mm = re.search(r"Weighted objective\s*:\s*([-\d.eE+]+)", blk)
            if mm:
                merits_raw.append(float(mm.group(1)))
    merits = dedup(merits_raw)

    # ---- cycle ----------------------------------------------------------
    cycle_positions = [(m.start(), int(m.group(1))) for m in re.finditer(
        r"Optimisation cycle (\d+)", text)]
    last_cycle = cycle_positions[-1][1] if cycle_positions else 0

    # ---- line search falliti, attribuiti al cycle ------------------------
    fails_per_cycle = {}
    for m in re.finditer(r"Line search reached max\. number of iterations", text):
        cyc = None
        for cpos, cnum in cycle_positions:
            if cpos <= m.start():
                cyc = cnum
            else:
                break
        if cyc is not None:
            fails_per_cycle[cyc] = fails_per_cycle.get(cyc, 0) + 1

    # ---- mesh movement e qualita' ---------------------------------------
    moves = re.findall(r"Max mesh movement magnitude\s+([-\d.eE+]+)", text)
    last_move = float(moves[-1]) if moves else None

    failed_list = re.findall(r"Failed (\d+) mesh geometry checks", text)
    last_failed = int(failed_list[-1]) if failed_list else 0
    skew_list = re.findall(r"Max skewness = ([\d.eE+-]+)", text)
    last_skew = float(skew_list[-1]) if skew_list else None

    scaled = re.findall(
        r"Max\. scaled correction of the design variables\s*=\s*([-\d.eE+]+)", text)
    last_scaled = float(scaled[-1]) if scaled else None

    # ---- continuita' (K7) ------------------------------------------------
    # Solo la coda del log, per non rileggere lo storico a ogni check.
    cont = re.findall(
        r"continuity errors : sum local = ([-\d.eE+]+)", text[-2_000_000:])
    max_cont = max((abs(float(c)) for c in cont[-200:]), default=None)

    # ---- ripartitore (K8) ------------------------------------------------
    # Il solver stampa in tre righe consecutive drag/downforce/momento, sia
    # durante il primal (valori GREZZI) sia nel riepilogo (valori PESATI, con
    # il momento a 0 perche' il suo peso e' 0). Si tengono le terne col
    # momento non nullo.
    #
    # SOLO su un primal gia' COMPLETATO: durante il transitorio il valore non
    # significa nulla (misurato: 17.6% alla prima iterazione, 44% alla 28a,
    # ~49% a convergenza). Il 4 set 2026 K8 fermo' un run leggendo 26.9% a
    # meta' transitorio.
    last_primal_end = None
    for m in re.finditer(rf"{PRIMAL_NAME} solution (?:converged|reached)", text):
        last_primal_end = m.start()

    front_pct = None
    if last_primal_end is not None:
        triples = re.findall(
            rf"{OBJ_DRAG}\s*:\s*([-\d.eE+]+)\s*\n"
            rf"\s*{OBJ_DOWNFORCE}\s*:\s*([-\d.eE+]+)\s*\n"
            rf"\s*{OBJ_MOMENT}\s*:\s*([-\d.eE+]+)",
            text[:last_primal_end])
        for _, cl_s, cm_s in reversed(triples):
            cl, cm = float(cl_s), float(cm_s)
            if abs(cm) > 1e-12 and abs(cl) > 1e-12:
                front_pct = (1.0 + cm / cl) * 100.0
                break

    # ---- diagnostica del vincolo (solo informativa, non uccide) ----------
    viol = re.findall(r"Number of flow constraints \(violated\)\s+(\d+)", text)
    n_violated = int(viol[-1]) if viol else None
    feas = re.findall(r"Feasibility\s*=\s*([-\d.eE+]+)", text)
    feasibility = float(feas[-1]) if feas else None

    return {
        "merits": merits,
        "fails_per_cycle": fails_per_cycle,
        "last_move": last_move,
        "last_failed": last_failed,
        "last_skew": last_skew,
        "last_scaled": last_scaled,
        "max_cont": max_cont,
        "front_pct": front_pct,
        "n_violated": n_violated,
        "feasibility": feasibility,
        "primal_done": last_primal_end is not None,
        "fatal": "FOAM FATAL" in text,
        "converged": "Optimisation has converged" in text,
        "last_cycle": last_cycle,
    }


class BestTracker:
    """Ricorda il best merit e il cycle dell'ultimo miglioramento."""
    def __init__(self):
        self.best = None
        self.best_cycle = 0

    def update(self, merits, last_cycle):
        if not merits:
            return
        cur_best = min(merits)          # si minimizza
        if self.best is None or cur_best < self.best - 1e-12:
            self.best = cur_best
            self.best_cycle = last_cycle


# ============================================================================
#  Regole
# ============================================================================

def check_rules(state, tracker, thr):
    if state["fatal"]:
        return True, "K1: FOAM FATAL nel log"

    # K7 per primo: se il campo non conserva la massa, merit, sensitivita' e
    # direzione di discesa sono tutti privi di significato.
    if state["max_cont"] is not None and state["max_cont"] > MAX_CONTINUITY:
        return True, (f"K7: errore di continuita' {state['max_cont']:.3g} > "
                      f"{MAX_CONTINUITY:.0e} — l'accoppiamento pressione-"
                      f"velocita' sta divergendo. Sospetti: BC adjoint "
                      f"(outlet/pareti), schemi di gradiente su celle "
                      f"degeneri, smoothing dell'ATC.")

    merits = state["merits"]

    # K2 — deriva irrecuperabile. Soglia COMBINATA: il criterio relativo da
    # solo impazzisce quando il merit passa vicino allo zero.
    if merits and tracker.best is not None:
        rise = merits[-1] - tracker.best
        limit = max(RISE_ABS, RISE_REL * abs(tracker.best))
        if rise > limit:
            return True, (f"K2: merit {merits[-1]:.5g} e' {rise:.4g} sopra il "
                          f"best {tracker.best:.5g} (soglia {limit:.4g}) — "
                          f"deriva irrecuperabile")

    # K3 — stagnazione
    if (tracker.best is not None
            and state["last_cycle"] >= MIN_CYC_FOR_K3
            and state["last_cycle"] - tracker.best_cycle >= STAGNATION_CYC):
        return True, (f"K3: nessun nuovo best merit da "
                      f"{state['last_cycle'] - tracker.best_cycle} cycle "
                      f"(best {tracker.best:.5g} al cycle "
                      f"{tracker.best_cycle}). Scaled correction attuale: "
                      f"{state['last_scaled']} — se piccola sei vicino "
                      f"all'ottimo, se grande il gradiente e' inconsistente")

    # K4 — line search bloccata
    lc = state["last_cycle"]
    fpc = state["fails_per_cycle"]
    consecutive = 0
    for c in range(lc - 1, 0, -1):      # solo cycle completati
        if fpc.get(c, 0) > 0:
            consecutive += 1
        else:
            break
    if consecutive >= MAX_LS_FAILS:
        return True, (f"K4: line search fallita in {consecutive} cycle "
                      f"consecutivi")

    # K5 — runaway del morphing (soglia relativa a maxInitChange)
    if state["last_move"] is not None and state["last_move"] > thr["move"]:
        mi = thr["max_init"]
        ref = f"{thr['move']:.4g} (= {MOVE_FACTOR:g} x maxInitChange {mi:g})" \
              if mi else f"{thr['move']:.4g} (fallback)"
        return True, (f"K5: mesh movement {state['last_move']:.4g} m > {ref}")

    # K6 — pista mesh esaurita
    if state["last_failed"] >= MAX_FAILED_CHECK:
        return True, (f"K6: mesh 'Failed {state['last_failed']} checks' dopo "
                      f"morphing (skew {state['last_skew']}) — serve remesh")
    if state["last_skew"] is not None and state["last_skew"] > thr["skew"]:
        return True, (f"K6: Max skewness {state['last_skew']:.2f} > soglia "
                      f"{thr['skew']:.2f} (relativa al baseline "
                      f"{thr['base_skew']}) — serve remesh")

    # K8 — ripartitore oltre i limiti di sicurezza
    fp = state["front_pct"]
    if fp is not None and not (BALANCE_HARD_MIN <= fp <= BALANCE_HARD_MAX):
        return True, (f"K8: ripartitore anteriore {fp:.1f}% oltre il limite "
                      f"di sicurezza [{BALANCE_HARD_MIN:.0f}, "
                      f"{BALANCE_HARD_MAX:.0f}]%. Con il vincolo attivo non "
                      f"dovrebbe accadere: verifica che l'adjointSolver del "
                      f"vincolo sia attivo e che updateMethod gestisca i "
                      f"vincoli (conjugateGradient li IGNORA).")

    return False, ""


# ============================================================================
#  Stop e utility
# ============================================================================

def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def gentle_stop(case_dir, pid, reason):
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    (case_dir / "WATCHDOG_STOP.txt").write_text(
        f"[{stamp}] WATCHDOG STOP\nMotivo: {reason}\n")
    print(f"[watchdog] STOP: {reason}", flush=True)

    cd = case_dir / "system" / "controlDict"
    try:
        content = cd.read_text()
        cd.write_text(re.sub(r"stopAt\s+\w+\s*;", "stopAt          writeNow;",
                             content, count=1))
        print(f"[watchdog] stopAt writeNow scritto, attendo {GRACE_SEC}s...",
              flush=True)
    except Exception as e:
        print(f"[watchdog] controlDict non modificabile: {e}", flush=True)

    for _ in range(GRACE_SEC // 15):
        if not pid_alive(pid):
            print("[watchdog] solver fermato in modo pulito.", flush=True)
            return
        time.sleep(15)

    print("[watchdog] invio SIGINT...", flush=True)
    try:
        os.kill(pid, signal.SIGINT)
    except ProcessLookupError:
        return
    for _ in range(GRACE_SEC // 15):
        if not pid_alive(pid):
            print("[watchdog] fermato con SIGINT.", flush=True)
            return
        time.sleep(15)

    print("[watchdog] escalation a SIGKILL.", flush=True)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


# ============================================================================
#  Main
# ============================================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--case", default=".")
    args = ap.parse_args()

    log_path = Path(args.log)
    case_dir = Path(args.case).resolve()
    tracker = BestTracker()
    thr = thresholds(case_dir)

    print(f"[watchdog v4] attivo su {log_path}, PID {args.pid}, "
          f"check ogni {CHECK_INTERVAL}s", flush=True)
    print(f"[watchdog] soglie ricavate dal case:", flush=True)
    print(f"           K5 mesh movement > {thr['move']:.4g} m "
          f"(maxInitChange letto: {thr['max_init']})", flush=True)
    print(f"           K6 skewness      > {thr['skew']:.2f} "
          f"(baseline letto: {thr['base_skew']})", flush=True)
    if thr["max_init"] is None or thr["base_skew"] is None:
        print("[watchdog] ATTENZIONE: qualche valore non e' stato letto dal "
              "case, sto usando un fallback. Verifica system/optimisationDict "
              "e log_mesh/06_checkMesh.", flush=True)

    warned_parse = False

    while True:
        time.sleep(CHECK_INTERVAL)

        if not pid_alive(args.pid):
            print("[watchdog] solver terminato da solo, esco.", flush=True)
            return
        if not log_path.exists():
            continue
        try:
            text = log_path.read_text(errors="ignore")
        except Exception:
            continue

        state = parse_log(text)
        tracker.update(state["merits"], state["last_cycle"])

        if state["converged"]:
            print("[watchdog] solver converged, esco.", flush=True)
            return

        # --- avviso di parsing: un watchdog cieco e' peggio di nessun
        #     watchdog, quindi se non aggancia le grandezze lo dice.
        if not warned_parse and state["primal_done"]:
            missing = []
            if not state["merits"]:
                missing.append(f"merit (blocco '{OBJ_SOLVER_NAME}')")
            if state["front_pct"] is None:
                missing.append(f"front% (terna {OBJ_DRAG}/{OBJ_DOWNFORCE}/"
                               f"{OBJ_MOMENT})")
            if missing:
                print("[watchdog] *** ATTENZIONE: non riesco a leggere " +
                      ", ".join(missing) + ". Le regole che ne dipendono "
                      "(K2, K3, K8) sono INATTIVE. Controlla i nomi in cima "
                      "a questo script contro l'optimisationDict.", flush=True)
            warned_parse = True

        m = state["merits"][-1] if state["merits"] else None
        print(f"[watchdog] cyc {state['last_cycle']}, merit {m}, "
              f"best {tracker.best} (cyc {tracker.best_cycle}), "
              f"move {state['last_move']}, skew {state['last_skew']}, "
              f"failed {state['last_failed']}, "
              f"contErr {state['max_cont']}, "
              f"front% {state['front_pct']}, "
              f"viol {state['n_violated']}, feas {state['feasibility']}",
              flush=True)

        kill, reason = check_rules(state, tracker, thr)
        if kill:
            gentle_stop(case_dir, args.pid, reason)
            return


if __name__ == "__main__":
    main()
