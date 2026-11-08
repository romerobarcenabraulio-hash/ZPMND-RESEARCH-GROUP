# Medición del lead time (`scripts/lead_time.py`)

Orden 1 del dueño (2026-11-03): ningún cambio de proceso se declara exitoso sin esta medición. Por cada PR fusionado,
con lo que existía al momento del merge (un veredicto, una corrida o una re-ejecución posterior no cuentan):

```
  total         opened -> merged
  antes_head    opened -> the merged head was committed (writing, earlier rounds, rebases); 0 if the head is older
  ci            ci.yml's last attempt for the merged head started before the merge: its start -> its last job's finish
  auditoria     the head was up for review (committed, not before the PR opened) -> both PASS on that head
  espera_ci     both PASS -> CI finished, when it finished later (merge commands wait for every check)
  espera_dueno  the later of both PASS and CI finished -> merged (the owner's merge, including order waits)
  revise        REVISE verdicts before the merge, by auditor (Claude "AUDIT VERDICT", GPT "GPT REVIEW")
A verdict counts only from github-actions (auditor.yml posts them), in its exact first-line form; a PASS counts only if
it names the merged head, and a later REVISE from the same auditor on that head cancels it. The CI is ci.yml's pull_request run for the head, in its last attempt started before the merge:
complete only if that attempt's status is completed and every job the attempt itself lists (its total checked against the
listing) finished before the merge; otherwise the PR is listed in ci_incompleto and has no ci, espera_ci nor
espera_dueno (never a partial CI counted as whole). A PR merged without both PASS on its head is listed in sin_dos_pass.
The sample is the LIMIT last PRs by merge time, chosen here from a listing of every merged PR (refused if the listing
reached its own limit, since it may then be cut).
```

Los datos de cada fila de `docs/ESTADO.md` están en `lead-time-<fecha>.json` junto a este archivo, recortados a lo que
se lee, con su hora de captura y sus comandos; `tests.test_lead_time` recalcula cada fila de ellos.
