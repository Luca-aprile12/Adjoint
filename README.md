# DP16_case

Caso CFD OpenFOAM per l'auto DP16. Questo repository contiene gli script di pre-processing, i dizionari di mesh/solutore e gli strumenti di post-processing necessari per generare la mesh, avviare la simulazione e gestire i riavvii.

## Requisiti

- Linux con OpenFOAM installato e configurato (assicurati di aver fatto `source <path>/OpenFOAM-<ver>/etc/bashrc` nel tuo `.bashrc` o nel terminale corrente)
- Python 3 per gli script di pre-processing (`preProcessor*.py`)
- ParaView per i file di scena `.pvsm` (facoltativo per la visualizzazione)

Nota: non viene forzata una versione specifica di OpenFOAM. Usa la tua versione abituale e adatta eventuali differenze di sintassi nei dizionari se necessario.

## Struttura del repository (essenziale)

- `system/`: dizionari di controllo, schemi, solutori, funzioni; include anche `functions/` per post-processing automatico e una sottocartella `region0/` se necessaria per casi multi-regione.
- `constant/`: proprietà fisiche (`transportProperties`, `turbulenceProperties`), superfici CAD in `triSurface_0deg/` e curve ventola (`fanCurve_*.txt`).
- `orig0/`: condizioni iniziali di riferimento (campi `U`, `p`, `k`, `omega`, `nut`).
- `initialConditions/`: condizioni iniziali generate o personalizzate (può essere popolata dagli script di pre-processing).
- `DP.foam`: file di progetto per aprire il caso in ParaView.
- Script Python di pre-processing: `preProcessor.py`, `preProcessor_whole_car.py`, `backup_preProcessor.py`.
- Script bash di utilità: `runMesh`, `runSolve`, `runAll`, `runClean`, `runRestart`, `runResume`.
- File di setup: `setup.txt`, `setup_UBJ_LBJ.txt` per parametri del caso/pre-processing.

## Flusso di lavoro consigliato

1) (Facoltativo) Pre-processing e setup
- Modifica `setup.txt` e, se pertinente, `setup_UBJ_LBJ.txt` con i parametri del caso (condizioni al contorno, opzioni geometriche, ventole, ecc.).
- Esegui lo script di pre-processing più adatto:

```bash
# Esempi (scegline uno in base al tuo scenario)
python3 preProcessor.py
python3 preProcessor_whole_car.py
# In caso di necessità, esiste anche: backup_preProcessor.py
```

Questi script aggiornano dizionari e/o condizioni iniziali in base ai file di setup.

2) Generazione mesh

```bash
./runMesh
```

Lo script esegue la pipeline di mesh (es. blockMesh, surfaceFeatureExtract, snappyHexMesh, ecc.) secondo i dizionari in `system/`.

3) Avvio simulazione

```bash
./runSolve
```

Questo avvia il solutore definito in `system/controlDict` con le opzioni di `fvSchemes`, `fvSolution` e le funzioni in `system/functions/` (residui, piani di taglio, iso-superfici, yPlus, ecc.).

4) Workflow completo (mesh + solve)

```bash
./runAll
```

5) Pulizia

```bash
./runClean
```

Rimuove risultati temporanei/di calcolo mantenendo i file necessari per ricostruire.

6) Riavvio/Resume

```bash
./runRestart   # prepara un riavvio pulito da uno stato salvato (time directory)
./runResume    # prosegue una simulazione già avviata
./runQueue     # mette in coda una simulazione, in attesa che termini la precedente.


```

## Personalizzazione del caso

- `setup.txt`: parametri principali del caso (es. velocità d’ingresso, attivazione ventole, opzioni di estrazione campi). Gli script Python lo leggono per aggiornare `system/` e `initialConditions/`.
- `setup_UBJ_LBJ.txt`: configurazioni specifiche di componenti/sottoassiemi (ad es. bracci sospensione). Usalo quando lavori con geometrie complete (whole car).
- `constant/fanCurve_*.txt`: curve caratteristiche delle ventole (batteria, radiatore). Aggiornale per riflettere la componentistica reale.
- `constant/triSurface_0deg/`: inserisci/aggiorna i file CAD (`*.obj`) necessari a `snappyHexMesh`.


## Suggerimenti e troubleshooting

- Assicurati che il tuo terminale abbia caricato l’ambiente OpenFOAM (controlla che i comandi tipo `blockMesh` siano disponibili).
- Se `snappyHexMesh` fallisce: verifica i CAD in `constant/triSurface_0deg/` e i parametri in `system/snappyHexMeshDict`.
- Se il solutore non parte: controlla `system/controlDict` (startFrom, stopAt, writeInterval) e i campi in `0/` o `initialConditions/`.
- Ventole: se presenti modelli porosi o fan curves, verifica i file in `constant/` e le opzioni in `system/fvOptions`.
- Multi-regione: se si usa `region0/`, verifica i dizionari duplicati in `system/region0/` (schemi/soluzione dedicati).

## Modifica del poroso 

Le perdite concentrate o modelli di ventola/mesh porosa sono tipicamente configurati in `system/fvOptions` tramite una voce di tipo Darcy-Forchheimer (o simili). Passi tipici:

1) Identifica/crea la `cellZone` interessata:
	 - Definisci i volumi da rendere porosi in `system/snappyHexMeshDict` usando `refinementRegions` con `mode cellZone` e `cellZone <nomeZona>` oppure crea la zona via `topoSet`/`setSet` dopo la mesh.
	 - Verifica la presenza della zona in `constant/polyMesh/cellZones` dopo `snappyHexMesh`.

2) Configura `system/fvOptions`:
	 - Aggiungi/modifica un blocco del tipo:
		 - `type            porousZone;`
		 - `selectionMode   cellZone;`
		 - `cellZone        <nomeZona>;`
		 - `coeffs { DarcyForchheimerCoeffs { d [0 -2 0 0 0 0 0] ...; f [0 -1 0 0 0 0 0] ...; } }`
	 - I coefficienti `d` (Darcy) e `f` (Forchheimer) vanno calibrati in base alla resistenza desiderata. Se hai curve ventola, tienile allineate con i file `constant/fanCurve_*.txt` o con eventuali `actuationDiskSource` se usati.

3) Validazione rapida:
	 - Esegui `./runMesh` (se hai cambiato le zone) e poi `./runSolve` e controlla i log per l’attivazione dell’opzione porosa.

Suggerimenti:
- Mantieni nomi coerenti per `cellZone` tra `snappyHexMeshDict` e `fvOptions`.
- Se il campo non reagisce, verifica che la zona non sia vuota (numero celle > 0) e che la dimensione fisica sia corretta.

# Comandi utili per paraview
## Visualizzazione delle facce non ortogonali:
foamToVTK -faceSet nonOrthoFaces -time 0
checkMesh -allGeometry -allTopology -writeAllFields -writeSets vtk


checkMesh -allGeometry -allTopology -writeAllFields -writeSets vtk
