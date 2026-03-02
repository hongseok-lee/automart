"""
Hyperparameter search: 20개 config 중 하나를 받아 카니발/쏘렌토 모델 학습.
GitHub Actions matrix job에서 --config-id N 으로 호출.
출력: search_results/{config_id}/ 에 모델 + metrics.json
"""
import argparse
import json
import os
import re

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score

CSV_PATH = "automart_master.csv"
OUTPUT_DIR = "search_results"

TARGETS = {
    "carnival": re.compile(r"카니발|carnival|ka4", re.IGNORECASE),
    "sorento": re.compile(r"쏘렌토|sorento", re.IGNORECASE),
}

FEATURES = ["모델연도", "주행거리", "예정가"]

# fmt: off
CONFIGS = [
    {"n_estimators": 200, "max_depth": 4, "learning_rate": 0.10, "subsample": 0.8,  "colsample_bytree": 0.8,  "min_child_weight": 1, "gamma": 0,   "reg_alpha": 0,    "reg_lambda": 1},
    {"n_estimators": 500, "max_depth": 6, "learning_rate": 0.05, "subsample": 0.8,  "colsample_bytree": 0.8,  "min_child_weight": 1, "gamma": 0,   "reg_alpha": 0,    "reg_lambda": 1},
    {"n_estimators": 100, "max_depth": 3, "learning_rate": 0.20, "subsample": 0.9,  "colsample_bytree": 0.9,  "min_child_weight": 1, "gamma": 0,   "reg_alpha": 0,    "reg_lambda": 1},
    {"n_estimators": 300, "max_depth": 8, "learning_rate": 0.05, "subsample": 0.7,  "colsample_bytree": 0.7,  "min_child_weight": 3, "gamma": 0.1, "reg_alpha": 0.1,  "reg_lambda": 2},
    {"n_estimators": 200, "max_depth": 4, "learning_rate": 0.10, "subsample": 0.8,  "colsample_bytree": 0.8,  "min_child_weight": 5, "gamma": 0.3, "reg_alpha": 1.0,  "reg_lambda": 5},
    {"n_estimators": 200, "max_depth": 5, "learning_rate": 0.10, "subsample": 1.0,  "colsample_bytree": 1.0,  "min_child_weight": 1, "gamma": 0,   "reg_alpha": 0,    "reg_lambda": 1},
    {"n_estimators": 300, "max_depth": 4, "learning_rate": 0.10, "subsample": 1.0,  "colsample_bytree": 0.9,  "min_child_weight": 1, "gamma": 0,   "reg_alpha": 0,    "reg_lambda": 1},
    {"n_estimators": 300, "max_depth": 4, "learning_rate": 0.10, "subsample": 0.6,  "colsample_bytree": 0.6,  "min_child_weight": 1, "gamma": 0,   "reg_alpha": 0,    "reg_lambda": 1},
    {"n_estimators": 800, "max_depth": 4, "learning_rate": 0.01, "subsample": 0.8,  "colsample_bytree": 0.8,  "min_child_weight": 1, "gamma": 0,   "reg_alpha": 0,    "reg_lambda": 1},
    {"n_estimators": 200, "max_depth": 6, "learning_rate": 0.20, "subsample": 0.8,  "colsample_bytree": 0.8,  "min_child_weight": 1, "gamma": 0,   "reg_alpha": 0,    "reg_lambda": 1},
    {"n_estimators": 400, "max_depth": 5, "learning_rate": 0.05, "subsample": 0.85, "colsample_bytree": 0.85, "min_child_weight": 3, "gamma": 0.1, "reg_alpha": 0.01, "reg_lambda": 2},
    {"n_estimators": 600, "max_depth": 3, "learning_rate": 0.03, "subsample": 0.7,  "colsample_bytree": 0.8,  "min_child_weight": 5, "gamma": 0.2, "reg_alpha": 0.1,  "reg_lambda": 3},
    {"n_estimators": 150, "max_depth": 6, "learning_rate": 0.15, "subsample": 0.9,  "colsample_bytree": 0.7,  "min_child_weight": 1, "gamma": 0,   "reg_alpha": 0,    "reg_lambda": 1},
    {"n_estimators": 200, "max_depth": 4, "learning_rate": 0.10, "subsample": 0.8,  "colsample_bytree": 0.8,  "min_child_weight": 1, "gamma": 0,   "reg_alpha": 5.0,  "reg_lambda": 1},
    {"n_estimators": 200, "max_depth": 4, "learning_rate": 0.10, "subsample": 0.8,  "colsample_bytree": 0.8,  "min_child_weight": 1, "gamma": 0,   "reg_alpha": 0,    "reg_lambda": 10},
    {"n_estimators": 500, "max_depth": 3, "learning_rate": 0.03, "subsample": 0.9,  "colsample_bytree": 0.9,  "min_child_weight": 1, "gamma": 0,   "reg_alpha": 0,    "reg_lambda": 1},
    {"n_estimators": 350, "max_depth": 5, "learning_rate": 0.07, "subsample": 0.8,  "colsample_bytree": 0.9,  "min_child_weight": 2, "gamma": 0.05,"reg_alpha": 0.05, "reg_lambda": 1.5},
    {"n_estimators": 250, "max_depth": 4, "learning_rate": 0.10, "subsample": 0.9,  "colsample_bytree": 0.6,  "min_child_weight": 1, "gamma": 0,   "reg_alpha": 0,    "reg_lambda": 1},
    {"n_estimators": 300, "max_depth": 5, "learning_rate": 0.10, "subsample": 0.8,  "colsample_bytree": 0.8,  "min_child_weight": 7, "gamma": 0.1, "reg_alpha": 0,    "reg_lambda": 1},
    {"n_estimators": 200, "max_depth": 5, "learning_rate": 0.10, "subsample": 0.8,  "colsample_bytree": 0.8,  "min_child_weight": 1, "gamma": 0.5, "reg_alpha": 0,    "reg_lambda": 1},
]
# fmt: on


def parse_num(s):
    if pd.isna(s):
        return 0
    return int(re.sub(r"[^0-9]", "", str(s)) or 0)


def load_data(df, pattern):
    mask = df["차량모델"].str.contains(pattern, na=False)
    sub = df[mask].copy()
    for col in FEATURES + ["낙찰금액"]:
        sub[col] = sub[col].apply(parse_num)
    sub = sub[(sub["예정가"] > 0) & (sub["낙찰금액"] > 0)]
    return sub


def _merge_small_groups(groups):
    """그룹 내 샘플 < 2이면 가장 큰 그룹에 병합."""
    from collections import Counter
    counts = Counter(groups)
    small = {g for g, c in counts.items() if c < 2}
    if small:
        largest = counts.most_common(1)[0][0]
        groups = np.array([g if g not in small else largest for g in groups])
    return groups


def make_stratify_groups(sub):
    """모델연도 + 주행거리(4-quantile bin) 조합으로 stratify 그룹 생성."""
    km = sub["주행거리"].values
    try:
        km_bins = pd.qcut(km, q=4, labels=False, duplicates="drop")
    except ValueError:
        km_bins = np.zeros(len(km), dtype=int)

    groups = sub["모델연도"].astype(str).values + "_" + pd.Series(km_bins).astype(str).values
    return _merge_small_groups(groups)


def train_one(name, df, pattern, config, out_dir):
    sub = load_data(df, pattern)
    print(f"\n[{name}] 학습 데이터: {len(sub)}건")
    if len(sub) < 10:
        print(f"[{name}] 데이터 부족 (< 10건), 건너뜀")
        return None

    X = sub[FEATURES].values
    y = sub["낙찰금액"].values
    indices = np.arange(len(X))

    # Stratified split 6:2:2 using index tracking
    groups = make_stratify_groups(sub)
    try:
        idx_train, idx_temp = train_test_split(
            indices, test_size=0.4, random_state=42, stratify=groups
        )
    except ValueError:
        idx_train, idx_temp = train_test_split(
            indices, test_size=0.4, random_state=42
        )

    # temp → val/test
    temp_groups = groups[idx_temp]
    temp_groups = _merge_small_groups(temp_groups)
    try:
        idx_val, idx_test = train_test_split(
            idx_temp, test_size=0.5, random_state=42, stratify=temp_groups
        )
    except ValueError:
        idx_val, idx_test = train_test_split(
            idx_temp, test_size=0.5, random_state=42
        )

    X_train, y_train = X[idx_train], y[idx_train]
    X_val, y_val = X[idx_val], y[idx_val]
    X_test, y_test = X[idx_test], y[idx_test]

    print(f"  Train: {len(X_train)}, Val: {len(X_val)}, Test: {len(X_test)}")

    model = xgb.XGBRegressor(random_state=42, verbosity=0, **config)
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

    metrics = {}
    for split_name, X_s, y_s in [("val", X_val, y_val), ("test", X_test, y_test)]:
        pred = model.predict(X_s)
        rmse = float(np.sqrt(np.mean((y_s - pred) ** 2)))
        mae = float(mean_absolute_error(y_s, pred))
        r2 = float(r2_score(y_s, pred))
        metrics[f"{split_name}_rmse"] = rmse
        metrics[f"{split_name}_mae"] = mae
        metrics[f"{split_name}_r2"] = r2
        print(f"  {split_name} — RMSE: {rmse:,.0f}, MAE: {mae:,.0f}, R²: {r2:.4f}")

    # Save model
    model_path = os.path.join(out_dir, f"{name}_model.json")
    model.save_model(model_path)
    print(f"  모델 저장: {model_path}")

    return metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-id", type=int, required=True)
    args = parser.parse_args()

    cid = args.config_id
    if cid < 0 or cid >= len(CONFIGS):
        raise ValueError(f"config-id must be 0~{len(CONFIGS)-1}, got {cid}")

    config = CONFIGS[cid]
    print(f"Config #{cid}: {config}")

    out_dir = os.path.join(OUTPUT_DIR, str(cid))
    os.makedirs(out_dir, exist_ok=True)

    df = pd.read_csv(CSV_PATH, dtype=str)
    print(f"전체 데이터: {len(df)}건")

    all_metrics = {"config_id": cid, "config": config}

    for name, pattern in TARGETS.items():
        metrics = train_one(name, df, pattern, config, out_dir)
        if metrics:
            all_metrics[name] = metrics

    # Save metrics
    metrics_path = os.path.join(out_dir, "metrics.json")
    with open(metrics_path, "w") as f:
        json.dump(all_metrics, f, indent=2)
    print(f"\nMetrics 저장: {metrics_path}")


if __name__ == "__main__":
    main()
