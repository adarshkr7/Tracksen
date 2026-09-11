"""Mutation check: reintroduce each historical bug and confirm a test catches it.

    python scripts/mutation_check.py

A suite that passes proves nothing on its own -- it may simply be unable to fail. Each
entry below is a real defect this project shipped at some point, re-applied to the
source so we can watch a test go red. Anything reported as ESCAPED is a test that looks
like coverage and is not.

Writing this found one: the plant-positioning test read the same constant it was
validating, so zeroing the constant relaxed the assertion too and the mutation walked
straight through. It now asserts an independent floor.

The source file is always restored, including on failure.
"""
import io, os, subprocess, sys

os.chdir(r"D:\CODE\SIH")

MUTANTS = [
    (
        "clubbing guard removed (the INFEASIBLE bug)",
        "samanvay/optimizer/cpsat.py",
        'm.Add(e <= sum(ds) - 1).OnlyEnforceIf(use[c.id])\n            m.Add(e == 0).OnlyEnforceIf(use[c.id].Not())',
        'm.Add(e <= sum(ds) - 1)',
        "tests/test_optimizer.py::test_solver_finds_a_feasible_plan",
    ),
    (
        "conformal offset disabled (P90 under-coverage)",
        "samanvay/models/duration.py",
        "self.p90_offset = float(max(0.0, residuals[rank]))",
        "self.p90_offset = 0.0",
        "tests/test_models.py::test_conformal_offset_is_applied",
    ),
    (
        "ground truth added to a feature set (leakage)",
        "samanvay/models/duration.py",
        'FEATURES = NUMERIC + CATEGORICAL',
        'FEATURES = NUMERIC + CATEGORICAL + ["actual_duration_min"]',
        "tests/test_models.py::test_no_ground_truth_in_any_feature_set",
    ),
    (
        "task durations inflated 10x (the calibration bug)",
        "samanvay/generator.py",
        "return int(max(20, round(base * noise)))",
        "return int(max(20, round(base * noise * 10)))",
        "tests/test_domain.py::test_task_durations_are_one_block_of_work",
    ),
    (
        "machine positioning buffer removed",
        "samanvay/optimizer/cpsat.py",
        "MACHINE_POSITIONING_MIN = 90",
        "MACHINE_POSITIONING_MIN = 0",
        "tests/test_optimizer.py::test_positioning_buffer_is_meaningful",
    ),
    (
        "SMMS chainage read as km instead of metres",
        "samanvay/ingestion/adapters.py",
        "km=float(raw[\"chainage_m\"]) / 1000.0,",
        "km=float(raw[\"chainage_m\"]),",
        "tests/test_ingestion.py::test_smms_chainage_is_converted_from_metres",
    ),
    (
        "SMMS priority scale not inverted",
        "samanvay/ingestion/sources.py",
        "SMMS_PRIORITY = {f\"P{i}\": 6 - i for i in range(1, 6)}",
        "SMMS_PRIORITY = {f\"P{i}\": i for i in range(1, 6)}",
        "tests/test_ingestion.py::test_smms_priority_scale_is_inverted_relative_to_tms",
    ),
]

results = []
for name, path, original, replacement, test in MUTANTS:
    src = io.open(path, encoding="utf-8").read()
    if original not in src:
        results.append((name, "SKIP", "anchor not found"))
        continue
    io.open(path, "w", encoding="utf-8").write(src.replace(original, replacement, 1))
    try:
        p = subprocess.run([sys.executable, "-m", "pytest", test, "-q", "--no-header",
                            "-p", "no:cacheprovider"],
                           capture_output=True, text=True, timeout=600)
        caught = p.returncode != 0
        results.append((name, "CAUGHT" if caught else "*** ESCAPED ***", test.split("::")[-1]))
    finally:
        io.open(path, "w", encoding="utf-8").write(src)

print(f"{'mutation':<46}{'result':<18}test")
print("-" * 96)
for name, status, test in results:
    print(f"{name:<46}{status:<18}{test}")
escaped = [r for r in results if "ESCAPED" in r[1]]
print(f"\n{len(results) - len(escaped)}/{len(results)} mutations caught")
sys.exit(1 if escaped else 0)
