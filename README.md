# Aero AI — ottimizzazione aerodinamica adjoint

Ottimizzazione di forma sul modello a metà vettura, con
**OpenFOAM v2312 (ESI)** e il solutore adjoint continuo `adjointOptimisationFoam`.

- **Obiettivo**: meno resistenza e più deportanza della vettura intera (tutte le patch `DP_*`)
- **Vincolo**: ripartitore aerodinamico anteriore entro **±TOT punti** dal valore di partenza
- **Parametrizzazione**: morphing B-spline volumetrico, una scatola sulla FW e una sulla RW
- **Risultato di riferimento**: 12 cicli in ~8 h su 12 core

> **Nota sui coefficienti.** `Aref = 1`, quindi i valori stampati come "C_D" e "C_L" sono in realtà
> **C_D·A e C_L·A in m², per mezza vettura**.

---

## Struttura

```
system/            dizionari OpenFOAM
  optimisationDict   obiettivi, pesi, vincolo, metodo di ottimizzazione   <- il cuore
  fvSchemes          discretizzazione (primal + adjoint)
  fvSolution         solutori lineari e rilassamento
  snappyHexMeshDict  mesh
  meshQualityDict    soglie di qualità per snappy
  ...
constant/
  dynamicMeshDict      scatole di morphing (dove si deforma e con quanti punti di controllo)
  adjointRASProperties turbolenza nell'adjoint (congelata)
  triSurface_0deg/          geometria
orig0/             condizioni iniziali e al contorno (primal + adjoint Ua, pa)
initialConditions  numero di core e parametri del case
runMesh            genera la mesh
runOpt             lancia l'ottimizzazione + watchdog
runValidation      simulazione di verifica su mesh rigenerata
newStint           prepara lo stint successivo dal punto migliore
scripts/watchdog.py  sorveglia il run e lo ferma se qualcosa va storto
plotConvergence      grafico e CSV della storia di ottimizzazione
```

---

## Workflow in breve

| passo | comando | produce |
|---|---|---|---|
| 1. mesh (dopo preProcessor)| `./runMesh` | `constant/polyMesh` |
| 2. ottimizzazione | `./runOpt` | `log/`, `optimisation/`, geometria finale |
| 3. storia | `./plotConvergence log/04_adjointOpt --out convergenza` | `convergenza.png/.pdf/.svg/.csv` |
| 4. validazione | `./runValidation --baseline` e `./runValidation` | `validation/` | (non necessario)
| 5. stint successivo | `./newStint ...` | nuova cartella di case | (eventualmente)

---

