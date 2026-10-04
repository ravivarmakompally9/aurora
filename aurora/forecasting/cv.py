"""Time-series validation (PRD §8.1): train on the past, test on the future, never shuffle."""
from __future__ import annotations

import json

import numpy as np

from aurora.config import DATA_DIR, ROOT, Station
from aurora.forecasting.models import Forecaster, QUANTILES


def pinball(y, q_pred, q):
    d = y - q_pred
    return float(np.mean(np.maximum(q * d, (q - 1) * d)))


def evaluate(f: Forecaster, twin, year: int, every_h: float = 6, horizon_h: float = 48) -> dict:
    st = twin.st
    steps = np.flatnonzero(twin.index.year == year)
    t0 = steps[steps < twin.n - int(horizon_h / st.dt_h) - 1][:: int(every_h / st.dt_h)]
    H = int(horizon_h / st.dt_h)
    res = {"year": year, "issues": int(len(t0))}
    chunks = [t0[i:i + 120] for i in range(0, len(t0), 120)]
    acc = {k: [] for k in ("idx", "lead_h", "load_p10", "load_p50", "load_p90", "heat_p10", "heat_p50", "heat_p90",
                           "pv_p50", "wind_p50", "pv_p10", "pv_p90", "wind_p10", "wind_p90")}
    for c in chunks:
        out = f.forecast(twin, c, H, 1, seed=year)
        for k in acc:
            acc[k].append(out[k])
    a = {k: np.concatenate(v) for k, v in acc.items()}
    idx = a["idx"]
    k24 = int(24 / st.dt_h) - 1
    for name, truth in (("load", twin.el_fixed), ("heat", twin.heat)):
        y = truth[idx]
        ape = np.abs(y - a[f"{name}_p50"]) / np.maximum(y, 1e-6)
        res[f"{name}_mape_24h_pct"] = float(100 * ape[:, k24].mean())
        res[f"{name}_mape_0_48h_pct"] = float(100 * ape.mean())
        persist = truth[np.maximum(idx[:, k24] - int(24 / st.dt_h), 0)]
        res[f"{name}_persistence_mape_24h_pct"] = float(100 * np.mean(np.abs(y[:, k24] - persist) / y[:, k24]))
        res[f"{name}_pinball"] = float(np.mean([pinball(y, a[f"{name}_p{int(q * 100)}"], q) for q in QUANTILES]))
        res[f"{name}_p10_p90_coverage_pct"] = float(100 * np.mean((y >= a[f"{name}_p10"]) & (y <= a[f"{name}_p90"])))
    for name, truth, cap in (("pv", twin.pv_avail, st.pv.kwp), ("wind", twin.wind_avail, st.wind.total_kw)):
        y = truth[idx]
        res[f"{name}_nmae_24h_pct"] = float(100 * np.mean(np.abs(y[:, k24] - a[f"{name}_p50"][:, k24])) / cap)
        res[f"{name}_nmae_0_48h_pct"] = float(100 * np.mean(np.abs(y - a[f"{name}_p50"])) / cap)
        res[f"{name}_p10_p90_coverage_pct"] = float(100 * np.mean((y >= a[f"{name}_p10"] - 1e-6) & (y <= a[f"{name}_p90"] + 1e-6)))
    return res


def report(st: Station, twin, forecaster: Forecaster | None = None) -> dict:
    """Train on the training year, conformal-calibrate on the validation year, report on the test year.

    Also reports the raw (uncalibrated) model on the validation year, so the effect of calibration is visible."""
    from aurora.forecasting.models import load_or_train
    f = forecaster or load_or_train(twin)
    out = {"station": st.key, "train_year": st.train_year, "calibration_year": st.val_year,
           "test_year": st.test_year, "folds": []}
    raw = Forecaster(f.station, f.train_years, f.models, f.reference)
    r = evaluate(raw, twin, st.val_year)
    r["note"] = "uncalibrated model on the validation year"
    out["folds"].append(r)
    r = evaluate(f, twin, st.test_year)
    r["note"] = "operational model (calibrated) on the held-out test year"
    out["folds"].append(r)
    out["margins_kw"] = f.margins
    path = ROOT / "docs" / f"forecast_report_{st.key}.json"
    path.write_text(json.dumps(out, indent=2))
    return out
