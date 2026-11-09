# make check: what CI runs on a PR, before it is opened (owner's order 7, 2026-11-03: no PR opens red).
# The whole suite and the offline policy check, then the mutants of the files changed against BASE (scripts/mutar_pr.py).
# The mutants split into SHARDS that run in parallel with make -j; on the 16-thread test server:
#   make -j16 check SHARDS=16
# Changed files come from git, so commit first: an uncommitted file is tested but does not pick its mutants.
PYTHON ?= python
BASE ?= origin/main
SHARDS ?= 1

.PHONY: check suite

# mutants-0 always runs: a SHARDS that is not a whole number of at least 1 reaches scripts/mutar.py as 0/<SHARDS>,
# which refuses it, instead of leaving check with no mutants to run.
check: mutants-0 $(addprefix mutants-,$(shell seq 1 1 $$(( $(SHARDS) - 1 )) 2>/dev/null))

suite:
	$(PYTHON) -m unittest discover -s tests -t .
	$(PYTHON) -m rg.openclaw_policy substrate/openclaw.json

mutants-%: suite
	RG_SHARD=$*/$(SHARDS) RG_MUT_BASE=$(BASE) $(PYTHON) scripts/mutar_pr.py
