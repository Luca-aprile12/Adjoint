#!/usr/bin/env python3
"""
watchdog.py v2 — sorveglia adjointOptimisationFoam e ferma il run se patologico.

REGOLE (riviste sui dati del run Phase2/39-cycle del 27 lug 2026):
  K1. "FOAM FATAL" nel log                            -> stop IMMEDIATO
  K2. Merit accettato sale > 25% rispetto al BEST     -> stop (catastrofe)
      (era 2% su singolo cycle: avrebbe ucciso il dip del 12% che poi ha
       recuperato fino al best assoluto. I dip sono recuperabili con pesi
       sani; solo derive enormi sono irrecuperabili.)
  K3. STAGNAZIONE: nessun nuovo best merit da 6 cycle -> stop
      (sostituisce "2 salite consecutive": robusto sia contro la deriva
       in salita sia contro il plateau, immune ai dip recuperabili)
  K4. Line search fallita in 2 cycle consecutivi      -> stop
  K5. Mesh movement > 0.05 m                          -> stop (runaway insensato)
      (era 0.016: ma i movimenti 0.017-0.021 osservati erano tentativi di
       line search poi gestiti. Il guardiano vero della mesh e' K6.)
  K6. Mesh degradata: "Failed >= 3 mesh checks" o     -> stop PRIMA di
      "Max skewness > 9" dopo un morphing                risolvere su mesh rotta
      (dati: skew 8 sopravvivibile, 9.86 = crash SIGFPE)

Confronta SOLO i merit ACCETTATI ("Old merit function value"), deduplicati
(il line search stampa lo stesso old-merit a ogni tentativo).

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

CHECK_INTERVAL   = 300     # secondi tra i controlli
GRACE_SEC        = 600     # attesa dopo stop gentile prima di escalare
CATASTROPHE_PCT  = 25.0    # K2: salita % rispetto al best -> kill
STAGNATION_CYC   = 6       # K3: cycle senza nuovo best -> kill
MAX_LS_FAILS     = 2       # K4: line search fallite in cycle consecutivi
MOVE_THRESHOLD   = 0.05    # K5: m (solo runaway insensati)
MAX_FAILED_CHECK = 3       # K6: Failed >= N mesh checks
MAX_SKEWNESS     = 9.0     # K6: skewness oltre cui la mesh e' spacciata


def dedup(seq):
    """Rimuove duplicati consecutivi (line search ristampa lo stesso old merit)."""
    out = []
    for x in seq:
        if not out or x != out[-1]:
            out.append(x)
    return out


def parse_log(text):
    merits_raw = [float(m) for m in re.findall(
        r"Old merit function value\s+([-\d.eE+]+)", text)]
    merits = dedup(merits_raw)

    cycle_positions = [(m.start(), int(m.group(1))) for m in re.finditer(
        r"Optimisation cycle (\d+)", text)]
    last_cycle = cycle_positions[-1][1] if cycle_positions else 0

    # line search failures attribuite ai cycle
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

    moves = re.findall(r"Max mesh movement magnitude\s+([-\d.eE+]+)", text)
    last_move = float(moves[-1]) if moves else None

    # K6: ultimo blocco di mesh check dopo morphing
    failed_list = re.findall(r"Failed (\d+) mesh geometry checks", text)
    last_failed = int(failed_list[-1]) if failed_list else 0
    skew_list = re.findall(r"Max skewness = ([\d.eE+-]+)", text)
    last_skew = float(skew_list[-1]) if skew_list else None

    scaled = re.findall(
        r"Max\. scaled correction of the design variables\s*=\s*([-\d.eE+]+)", text)
    last_scaled = float(scaled[-1]) if scaled else None

    return {
        "merits": merits,
        "fails_per_cycle": fails_per_cycle,
        "last_move": last_move,
        "last_failed": last_failed,
        "last_skew": last_skew,
        "last_scaled": last_scaled,
        "fatal": "FOAM FATAL" in text,
        "converged": "Optimisation has converged" in text,
        "last_cycle": last_cycle,
    }


class BestTracker:
    """Ricorda il best merit e a che cycle e' stato visto l'ultimo miglioramento."""
    def __init__(self):
        self.best = None
        self.best_cycle = 0

    def update(self, merits, last_cycle):
        if not merits:
            return
        cur_best = min(merits)          # minimizziamo
        if self.best is None or cur_best < self.best - 1e-12:
            self.best = cur_best
            self.best_cycle = last_cycle


def check_rules(state, tracker):
    if state["fatal"]:
        return True, "K1: FOAM FATAL nel log"

    merits = state["merits"]

    # K2 — catastrofe: ultimo merit accettato molto sopra il best
    if merits and tracker.best is not None and abs(tracker.best) > 1e-12:
        rise_pct = (merits[-1] - tracker.best) / abs(tracker.best) * 100.0
        if rise_pct > CATASTROPHE_PCT:
            return True, (f"K2: merit {merits[-1]:.5g} e' {rise_pct:.1f}% sopra "
                          f"il best {tracker.best:.5g} — deriva irrecuperabile")

    # K3 — stagnazione: nessun nuovo best da STAGNATION_CYC cycle
    if tracker.best is not None and state["last_cycle"] - tracker.best_cycle >= STAGNATION_CYC:
        return True, (f"K3: nessun nuovo best merit da "
                      f"{state['last_cycle'] - tracker.best_cycle} cycle "
                      f"(best {tracker.best:.5g} al cycle {tracker.best_cycle}). "
                      f"Scaled correction attuale: {state['last_scaled']} — "
                      f"se piccola sei vicino all'ottimo, se grande il "
                      f"gradiente e' inconsistente")

    # K4 — line search fallita in cycle consecutivi
    lc = state["last_cycle"]
    fpc = state["fails_per_cycle"]
    consecutive = 0
    for c in range(lc - 1, 0, -1):      # solo cycle completati
        if fpc.get(c, 0) > 0:
            consecutive += 1
        else:
            break
    if consecutive >= MAX_LS_FAILS:
        return True, f"K4: line search fallita in {consecutive} cycle consecutivi"

    # K5 — runaway insensato
    if state["last_move"] is not None and state["last_move"] > MOVE_THRESHOLD:
        return True, (f"K5: mesh movement {state['last_move']:.4g} m > "
                      f"{MOVE_THRESHOLD} m (runaway)")

    # K6 — mesh degradata oltre il limite di sopravvivenza
    if state["last_failed"] >= MAX_FAILED_CHECK:
        return True, (f"K6: mesh 'Failed {state['last_failed']} checks' dopo "
                      f"morphing (skew {state['last_skew']}) — pista mesh "
                      f"esaurita, serve remesh (nuova gamba di ottimizzazione)")
    if state["last_skew"] is not None and state["last_skew"] > MAX_SKEWNESS:
        return True, (f"K6: Max skewness {state['last_skew']:.2f} > "
                      f"{MAX_SKEWNESS} — pista mesh esaurita, serve remesh")

    return False, ""


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

    deadline = time.time() + GRACE_SEC
    while time.time() < deadline:
        if not pid_alive(pid):
            print("[watchdog] solver fermato in modo pulito.", flush=True)
            return
        time.sleep(15)

    print("[watchdog] invio SIGINT...", flush=True)
    try:
        os.kill(pid, signal.SIGINT)
    except ProcessLookupError:
        return
    deadline = time.time() + GRACE_SEC
    while time.time() < deadline:
        if not pid_alive(pid):
            print("[watchdog] fermato con SIGINT.", flush=True)
            return
        time.sleep(15)

    print("[watchdog] escalation a SIGKILL.", flush=True)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--case", default=".")
    args = ap.parse_args()

    log_path = Path(args.log)
    case_dir = Path(args.case).resolve()
    tracker = BestTracker()

    print(f"[watchdog v2] attivo su {log_path}, PID {args.pid}, "
          f"check ogni {CHECK_INTERVAL}s", flush=True)

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

        m = state["merits"][-1] if state["merits"] else None
        print(f"[watchdog] cyc {state['last_cycle']}, merit {m}, "
              f"best {tracker.best} (cyc {tracker.best_cycle}), "
              f"move {state['last_move']}, skew {state['last_skew']}, "
              f"failed {state['last_failed']}", flush=True)

        kill, reason = check_rules(state, tracker)
        if kill:
            gentle_stop(case_dir, args.pid, reason)
            return


if __name__ == "__main__":
    main()
