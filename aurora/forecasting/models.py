"""Probabilistic 48 h forecasters (FR-04..FR-08).

Load and heat: gradient-boosted quantile regression (scikit-learn HistGradientBoosting,
the same tree method as LightGBM without its native OpenMP dependency).
PV and wind: physics model on the weather forecast plus a quantile ML correction.
Storm risk: probability that forecast wind exceeds the Storm Mode threshold, from the
lead-time-dependent forecast spread.
"""
from __future__ import annotations

import logging
import pickle
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.ensemble import HistGradientBoostingRegressor

from aurora.config import DATA_DIR, Station
from aurora.forecasting.features import (LOAD_FEATURES, REN_FEATURES, demand_features, nwp,
                                         perturb_for_training, renewable_physics, sigma_logwind)

log = logging.getLogger(__name__)
QUANTILES = (0.1, 0.5, 0.9)
TARGETS = ("load", "heat", "pv", "wind")


def _model(q: float) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(loss="quantile", quantile=q, max_iter=300, learning_rate=0.06,
                                         max_leaf_nodes=31, min_samples_leaf=40, random_state=0)


@dataclass
class Forecaster:
    station: str
    train_years: tuple[int, ...]
    models: dict = field(default_factory=dict)       # (target, q) -> model
    reference: dict = field(default_factory=dict)    # median feature values for explanations
    margins: dict = field(default_factory=dict)      # conformal widening per (target, lead bin), kW
    calib_year: int | None = None

    # ---------- training ----------
    @classmethod
    def train(cls, twin, years: tuple[int, ...], seed: int = 0) -> "Forecaster":
        st = twin.st
        rng = np.random.default_rng(seed)
        mask = np.isin(twin.index.year, years)
        steps = np.flatnonzero(mask)
        steps = steps[steps >= int(168 / st.dt_h)]  # need weekly lag
        wx = twin.wx.iloc[steps]
        lead = rng.uniform(st.dt_h, 48, len(steps))
        pert = perturb_for_training(st, wx, lead, rng)
        f = cls(station=st.key, train_years=tuple(years))
        targets = {"load": twin.el_fixed, "heat": twin.heat}
        for name, arr in targets.items():
            X = demand_features(twin, steps, lead, pert["temp"], pert["wind10"], arr)[LOAD_FEATURES]
            y = arr[steps]
            for q in QUANTILES:
                f.models[(name, q)] = _model(q).fit(X, y)
            f.reference[name] = X.median()
        pv, wd, hub, elev, kt, clear = renewable_physics(twin, steps, pert["temp"], pert["wind10"], pert["ghi"])
        for name, phys, actual in (("pv", pv, twin.pv_avail), ("wind", wd, twin.wind_avail)):
            X = pd.DataFrame({"physics_kw": phys, "elevation": elev, "kt_fc": kt, "temp": pert["temp"],
                              "wind10": pert["wind10"], "hub_fc": hub, "lead_h": lead, "panel_clear": clear})[REN_FEATURES]
            for q in QUANTILES:
                f.models[(name, q)] = _model(q).fit(X, actual[steps])
        return f

    # ---------- inference ----------
    def forecast(self, twin, t0: np.ndarray | int, horizon: int = 192, stride: int = 1, seed: int = 0) -> dict:
        """Forecasts for each issue step in t0: arrays shaped (n_issue, horizon)."""
        st = twin.st
        t0 = np.atleast_1d(np.asarray(t0, dtype=int))
        w = nwp(twin, t0, horizon, stride, seed)
        shape = w["idx"].shape
        out = {"idx": w["idx"], "lead_h": w["lead_h"], "temp": w["temp"], "wind10": w["wind10"]}
        for name, arr in (("load", twin.el_fixed), ("heat", twin.heat)):
            # lags must not look past the issue time: mask any lag newer than t0
            X = demand_features(twin, w["idx"], w["lead_h"], w["temp"], w["wind10"], arr)[LOAD_FEATURES]
            for lag_h in (48, 168):
                lag_t = w["idx"].ravel() - int(lag_h / st.dt_h)
                future = lag_t > np.repeat(t0, shape[1])
                X.loc[future, f"lag{lag_h}"] = np.nan
            preds = np.sort(np.stack([self.models[(name, q)].predict(X) for q in QUANTILES]), axis=0)
            preds[0] -= self._margin(name, w["lead_h"].ravel())
            preds[2] += self._margin(name, w["lead_h"].ravel())
            for q, p in zip(QUANTILES, preds):
                out[f"{name}_p{int(q * 100)}"] = np.maximum(p, 0).reshape(shape)
        pv, wd, hub, elev, kt, clear = renewable_physics(twin, w["idx"], w["temp"], w["wind10"], w["ghi"])
        cap = {"pv": st.pv.kwp * 1.05, "wind": st.wind.total_kw}
        for name, phys in (("pv", pv), ("wind", wd)):
            X = pd.DataFrame({"physics_kw": phys, "elevation": elev, "kt_fc": kt, "temp": w["temp"].ravel(),
                              "wind10": w["wind10"].ravel(), "hub_fc": hub, "lead_h": w["lead_h"].ravel(),
                              "panel_clear": clear})[REN_FEATURES]
            preds = np.sort(np.stack([self.models[(name, q)].predict(X) for q in QUANTILES]), axis=0)
            preds[0] -= self._margin(name, w["lead_h"].ravel())
            preds[2] += self._margin(name, w["lead_h"].ravel())
            preds = np.clip(preds, 0, cap[name])
            if name == "pv":
                preds = np.where(elev > 0.5, preds, 0.0)
            else:
                preds = np.where(hub >= st.wind.cut_out_ms, 0.0, preds)  # planned cut-out
            for q, p in zip(QUANTILES, preds):
                out[f"{name}_p{int(q * 100)}"] = p.reshape(shape)
        s = sigma_logwind(w["lead_h"])
        thr = st.control.storm_wind_ms
        out["storm_prob"] = 1 - norm.cdf((np.log(thr) - np.log(np.maximum(w["wind10"], 0.1)) - 0.5 * s ** 2) / s)
        out["hub_wind"] = hub.reshape(shape)
        return out

    LEAD_BINS = (0, 6, 12, 24, 36, 48.01)

    def _margin(self, target: str, lead_h: np.ndarray) -> np.ndarray:
        m = self.margins.get(target)
        if m is None:
            return np.zeros_like(lead_h)
        b = np.clip(np.digitize(lead_h, self.LEAD_BINS) - 1, 0, len(m) - 1)
        return np.asarray(m)[b]

    def calibrate(self, twin, year: int, coverage: float = 0.8, every_h: float = 6) -> dict:
        """Split-conformal widening of the P10-P90 band on a held-out year, per lead-time bin."""
        st = twin.st
        H = int(48 / st.dt_h)
        steps = np.flatnonzero(twin.index.year == year)
        t0 = steps[steps < twin.n - H - 1][:: int(every_h / st.dt_h)]
        self.margins = {}
        outs = [self.forecast(twin, t0[i:i + 120], H, 1, seed=year + 1) for i in range(0, len(t0), 120)]
        cat = lambda k: np.concatenate([o[k] for o in outs])
        idx, lead = cat("idx"), cat("lead_h")
        b = np.clip(np.digitize(lead, self.LEAD_BINS) - 1, 0, len(self.LEAD_BINS) - 2)
        truth = {"load": twin.el_fixed, "heat": twin.heat, "pv": twin.pv_avail, "wind": twin.wind_avail}
        margins = {}
        for name, arr in truth.items():
            y = arr[idx]
            score = np.maximum(cat(f"{name}_p10") - y, y - cat(f"{name}_p90"))
            margins[name] = [float(max(0.0, np.quantile(score[b == i], coverage))) if np.any(b == i) else 0.0
                             for i in range(len(self.LEAD_BINS) - 1)]
        self.margins = margins
        self.calib_year = year
        return margins

    def forecast_frame(self, twin, t0: int, horizon: int = 192, stride: int = 1, seed: int = 0) -> pd.DataFrame:
        f = self.forecast(twin, t0, horizon, stride, seed)
        cols = {k: v[0] for k, v in f.items() if isinstance(v, np.ndarray) and v.ndim == 2 and k != "idx"}
        return pd.DataFrame(cols, index=twin.index[f["idx"][0]]).assign(step=f["idx"][0])

    # ---------- explanations (FR-26, PRD §8.5) ----------
    GROUPS = {
        "weather": ["temp", "wind10", "wind_chill", "hdd_wind"],
        "crew": ["crew"],
        "experiments": ["experiment_kw"],
        "time of day": ["hs1", "hc1", "hs2", "hc2", "meal"],
        "recent load": ["lag48", "lag168"],
    }

    def drivers(self, twin, t0: int, target: str = "load", hours: float = 24) -> dict[str, float]:
        """kW each feature group adds to the mean P50 forecast vs a typical reference (ablation)."""
        st = twin.st
        n = int(hours / st.dt_h)
        w = nwp(twin, np.array([t0]), n, 1)
        arr = twin.el_fixed if target == "load" else twin.heat
        X = demand_features(twin, w["idx"], w["lead_h"], w["temp"], w["wind10"], arr)[LOAD_FEATURES]
        m = self.models[(target, 0.5)]
        base = m.predict(X).mean()
        out = {}
        for g, cols in self.GROUPS.items():
            Xr = X.copy()
            for c in cols:
                Xr[c] = self.reference[target][c]
            out[g] = float(base - m.predict(Xr).mean())
        out["forecast_mean_kw"] = float(base)
        out["temp_fc_c"] = float(np.mean(w["temp"]))
        out["wind_chill_fc_c"] = float(np.mean(X["wind_chill"]))
        out["crew"] = float(X["crew"].mean())
        out["crew_ref"] = float(self.reference[target]["crew"])
        return out

    # ---------- persistence ----------
    def save(self, path=None):
        path = path or DATA_DIR / "processed" / f"forecaster_{self.station}.pkl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as fh:
            pickle.dump(self, fh)
        return path


def load_or_train(twin, retrain: bool = False) -> Forecaster:
    """Operational forecaster: train on the training year, conformal-calibrate on the validation year.

    `twin` must cover all weather years (Twin(st) with no start/end)."""
    st = twin.st
    path = DATA_DIR / "processed" / f"forecaster_{st.key}.pkl"
    if path.exists() and not retrain:
        with open(path, "rb") as fh:
            return pickle.load(fh)
    log.info("training forecaster for %s on %s, calibrating on %s", st.key, st.train_year, st.val_year)
    f = Forecaster.train(twin, (st.train_year,))
    f.calibrate(twin, st.val_year)
    f.save(path)
    return f
