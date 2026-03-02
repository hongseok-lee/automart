"""
XGBoost 모델 학습: 카니발/쏘렌토 낙찰금액 예측
X: 모델연도, 주행거리, 예정가 → Y: 낙찰금액
"""
import os
import re
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score
import xgboost as xgb

CSV_PATH = "automart_master.csv"
MODEL_DIR = "models"

TARGETS = {
    "carnival": re.compile(r"카니발|carnival|ka4", re.IGNORECASE),
    "sorento": re.compile(r"쏘렌토|sorento", re.IGNORECASE),
}

FEATURES = ["모델연도", "주행거리", "예정가"]


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


def train_one(name, df, pattern):
    sub = load_data(df, pattern)
    print(f"\n{'='*50}")
    print(f"[{name}] 학습 데이터: {len(sub)}건")
    if len(sub) < 10:
        print(f"[{name}] 데이터 부족 (< 10건), 학습 건너뜀")
        return

    X = sub[FEATURES].values
    y = sub["낙찰금액"].values

    # Split 6:2:2
    X_train, X_temp, y_train, y_temp = train_test_split(
        X, y, test_size=0.4, random_state=42
    )
    X_val, X_test, y_val, y_test = train_test_split(
        X_temp, y_temp, test_size=0.5, random_state=42
    )
    print(f"  Train: {len(X_train)}, Val: {len(X_val)}, Test: {len(X_test)}")

    model = xgb.XGBRegressor(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbosity=0,
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )

    # Metrics
    for split_name, X_s, y_s in [("Val", X_val, y_val), ("Test", X_test, y_test)]:
        pred = model.predict(X_s)
        rmse = np.sqrt(np.mean((y_s - pred) ** 2))
        mae = mean_absolute_error(y_s, pred)
        r2 = r2_score(y_s, pred)
        print(f"  {split_name} — RMSE: {rmse:,.0f}, MAE: {mae:,.0f}, R²: {r2:.4f}")

    # Save
    os.makedirs(MODEL_DIR, exist_ok=True)
    model_path = os.path.join(MODEL_DIR, f"{name}_model.json")
    model.save_model(model_path)
    print(f"  모델 저장: {model_path}")


def main():
    df = pd.read_csv(CSV_PATH, dtype=str)
    print(f"전체 데이터: {len(df)}건")

    for name, pattern in TARGETS.items():
        train_one(name, df, pattern)

    print(f"\n{'='*50}")
    print("학습 완료!")


if __name__ == "__main__":
    main()
