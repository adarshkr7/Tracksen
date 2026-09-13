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
    (
        "anyone may sanction (authority check removed)",
        "samanvay/governance/workflow.py",
        "if actor.role is not Role.DRM:",
        "if False:",
        "tests/test_governance.py::test_only_the_drm_can_sanction",
    ),
    (
        "heads may concur for other departments",
        "samanvay/governance/workflow.py",
        "if not actor.may_concur_for(department):",
        "if False:",
        "tests/test_governance.py::test_a_head_cannot_concur_for_another_department",
    ),
    (
        "audit chain verification always passes",
        "samanvay/governance/audit.py",
        "if e.compute_hash() != e.entry_hash:",
        "if False:",
        "tests/test_governance.py::test_editing_a_past_entry_breaks_the_chain",
    ),
    (
        "sanctioned plans become editable again",
        "samanvay/governance/workflow.py",
        "if a.state is PlanState.SANCTIONED:\n            self._deny(actor, Action.MODIFY",
        "if False:\n            self._deny(actor, Action.MODIFY",
        "tests/test_governance.py::test_a_sanctioned_plan_cannot_be_modified",
    ),
    (
        "corridor reverts to the para-3.0 floor as though it were the norm",
        "samanvay/network.py",
        'DEFAULT_CORRIDOR_REGIME = "single-240"',
        'DEFAULT_CORRIDOR_REGIME = "min-180"',
        "tests/test_corridor.py::test_the_default_is_the_norm_not_the_floor",
    ),
    (
        "two corridor spells placed so they overlap",
        "samanvay/network.py",
        '"split-150x2": CorridorRegime("split-150x2", ((-4, 150), (0, 150))),',
        '"split-150x2": CorridorRegime("split-150x2", ((-1, 150), (0, 150))),',
        "tests/test_corridor.py::test_spells_on_a_section_day_never_overlap",
    ),
    (
        "burst check forgets the withdrawal inside the possession",
        "samanvay/evaluate.py",
        "over = longest + overhead - b.duration_min",
        "over = longest - b.duration_min",
        "tests/test_bursting.py::test_the_withdrawal_counts_against_the_window",
    ),
    (
        "password check always passes",
        "samanvay/governance/accounts.py",
        "return hmac.compare_digest(candidate.hex(), self.password_hash)",
        "return True",
        "tests/test_identity.py::test_a_wrong_password_is_refused",
    ),
    (
        "session expiry is written but never checked",
        "samanvay/governance/sessions.py",
        "        reason = found.expiry_reason()\n        if reason:",
        "        reason = None\n        if reason:",
        "tests/test_identity.py::test_an_expired_session_is_refused",
    ),
    (
        "using a session extends its absolute lifetime",
        "samanvay/governance/sessions.py",
        "        now = _now()\n        previous = _parse(found.last_seen)",
        "        now = _now()\n        found.expires_at = _iso(now + dt.timedelta(hours=ABSOLUTE_LIFETIME_HOURS))\n"
        "        previous = _parse(found.last_seen)",
        "tests/test_identity.py::test_use_moves_the_idle_clock_but_not_the_absolute_one",
    ),
    (
        "failed sign-ins no longer lock the account",
        "samanvay/governance/accounts.py",
        "            if account.failed_attempts >= MAX_FAILED_ATTEMPTS:",
        "            if False:",
        "tests/test_identity.py::test_repeated_failures_lock_the_account",
    ),
    (
        "an unknown username is refused differently from a wrong password",
        "samanvay/governance/accounts.py",
        '            _derive(password or "", _DUMMY_SALT, SCRYPT_N, SCRYPT_R, SCRYPT_P, DK_LEN)\n'
        "            raise AuthenticationError(refusal)",
        '            _derive(password or "", _DUMMY_SALT, SCRYPT_N, SCRYPT_R, SCRYPT_P, DK_LEN)\n'
        '            raise AuthenticationError("no such user")',
        "tests/test_identity.py::test_an_unknown_user_and_a_wrong_password_are_indistinguishable",
    ),
    (
        "changing a password leaves other sessions alive",
        "samanvay/governance/identity.py",
        "        ended = self.sessions.revoke_all_for(account.username, except_token=token)",
        "        ended = 0",
        "tests/test_identity.py::test_changing_the_password_ends_every_other_session",
    ),
    (
        "monthly return reports the weekly plan's blocks",
        "samanvay/reports.py",
        '_overdue(payload, metrics, monthly.get("blocks", []), monthly["days"])',
        '_overdue(payload, metrics, payload.get("blocks", []), monthly["days"])',
        "tests/test_reports.py::test_the_monthly_return_reads_the_monthly_plan_not_the_weekly_one",
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
