"""Score EVERY gated VALIDATION row with the auditor's row-by-row features and compare with the lab's saved scores."""
import sys, json
import numpy as np
sys.path.insert(0, '/home/user/Claude/research/lab/audit')
import indep_f4 as I
fin = I.frozen_params(0.98)
ens = I.load_model(I.LAB / fin['params']['model_file'][4:], fin['model_sha256'])
sp = fin['params']['strategy']
ds = np.load(I.LAB / 'f4' / 'dataset_validation.npz', allow_pickle=False)
saved = np.load(I.LAB / 'f4' / 'scores' / 'val_tp30_sl15_h15_gbt.npy')
mints, ci, bar = ds['mints'], ds['coin'], ds['bar']
sol = I.Sol()
coins = {}
mine = np.full(len(bar), np.nan)
gate_mismatch = 0
for k, (c, b) in enumerate(zip(ci, bar)):
    m = str(mints[c])
    cn = coins.setdefault(m, I.load_coin(m))
    now = cn['ts'][b] + cn['dur'][b]
    s_now = sol.at(now)
    f, v10, gi = I.feature_row(cn, int(b), s_now)
    if not I.gate_ok(f, v10, cn['c'][b] * 1e9 / s_now, sp['max_age_min'], sp['min_vol10_usd'], sp['min_mcap_sol']):
        gate_mismatch += 1
    X = np.array([[f[n] for n in I.NAMES]])
    X = np.clip(np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0), -50, 50)[:, ens.cols]
    mine[k] = np.mean([mm.predict_proba(X)[0, 1] for mm in ens.models])
d = np.abs(mine - saved)
res = {'rows': int(len(bar)), 'coins': int(len(set(ci.tolist()))), 'max_abs_diff': float(np.nanmax(d)),
       'rows_diff_gt_1e-9': int((d > 1e-9).sum()), 'rows_failing_independent_gate': gate_mismatch,
       'rows_above_threshold_lab': int((saved > sp['threshold']).sum()), 'rows_above_threshold_mine': int((mine > sp['threshold']).sum())}
print(json.dumps(res))
(I.OUT / 'rowcheck_validation.json').write_text(json.dumps(res, indent=1))
