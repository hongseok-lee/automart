"""
추론 + SWA 블렌딩: 카니발/쏘렌토 낙찰금액 예측
- Top-5 ensemble: 모델 5개 로드 → 각각 predict → 평균
- Fallback: top 모델 없으면 기존 단일 모델로 동작
- SWA: swa_pred = (swa_n * old_pred + new_pred) / (swa_n + 1)
- CSV에 '예측낙찰금액' 컬럼 추가
"""
import os
import re
import json
import pandas as pd
import numpy as np
import xgboost as xgb

CSV_PATH = "automart_master.csv"
MODEL_DIR = "models"
SWA_PATH = os.path.join(MODEL_DIR, "swa_state.json")

TARGETS = {
    "carnival": re.compile(r"카니발|carnival|ka4", re.IGNORECASE),
    "sorento": re.compile(r"쏘렌토|sorento", re.IGNORECASE),
}

FEATURES = ["모델연도", "주행거리", "예정가"]


def parse_num(s):
    if pd.isna(s):
        return 0
    return int(re.sub(r"[^0-9]", "", str(s)) or 0)


def row_key(row):
    return f"{row['차량번호']}_{row['경매일시']}"


def load_swa_state():
    if os.path.exists(SWA_PATH):
        with open(SWA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_swa_state(state):
    os.makedirs(MODEL_DIR, exist_ok=True)
    with open(SWA_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)


def main():
    df = pd.read_csv(CSV_PATH, dtype=str)
    print(f"전체 데이터: {len(df)}건")

    swa_state = load_swa_state()

    # Initialize prediction column
    if "예측낙찰금액" not in df.columns:
        df["예측낙찰금액"] = ""

    total_predicted = 0

    for name, pattern in TARGETS.items():
        # Load ensemble models (top 0~4), fallback to single model
        models = []
        for rank in range(5):
            top_path = os.path.join(MODEL_DIR, f"{name}_top{rank}.json")
            if os.path.exists(top_path):
                m = xgb.XGBRegressor()
                m.load_model(top_path)
                models.append(m)

        if not models:
            # Fallback: 기존 단일 모델
            single_path = os.path.join(MODEL_DIR, f"{name}_model.json")
            if os.path.exists(single_path):
                m = xgb.XGBRegressor()
                m.load_model(single_path)
                models.append(m)

        if not models:
            print(f"[{name}] 모델 파일 없음")
            continue

        print(f"[{name}] {len(models)}개 모델 로드 (ensemble)")

        mask = df["차량모델"].str.contains(pattern, na=False)
        indices = df[mask].index

        # Prepare features
        feat_df = df.loc[indices, FEATURES].copy()
        for col in FEATURES:
            feat_df[col] = feat_df[col].apply(parse_num)

        # Only predict rows with valid features (예정가 > 0)
        valid_mask = feat_df["예정가"] > 0
        valid_indices = feat_df[valid_mask].index

        if len(valid_indices) == 0:
            print(f"[{name}] 예측 가능한 행 없음")
            continue

        X = feat_df.loc[valid_indices].values

        # Ensemble: average predictions from all models
        all_preds = np.column_stack([m.predict(X) for m in models])
        raw_preds = np.mean(all_preds, axis=1)

        count = 0
        for idx, pred in zip(valid_indices, raw_preds):
            key = row_key(df.loc[idx])
            pred = max(0, float(pred))

            # SWA blending
            if key in swa_state:
                old_pred = swa_state[key]["pred"]
                swa_n = swa_state[key]["n"]
                swa_pred = (swa_n * old_pred + pred) / (swa_n + 1)
                swa_state[key] = {"pred": swa_pred, "n": swa_n + 1}
            else:
                swa_pred = pred
                swa_state[key] = {"pred": pred, "n": 1}

            # Format with commas
            df.at[idx, "예측낙찰금액"] = f"{int(round(swa_pred)):,}"
            count += 1

        total_predicted += count
        print(f"[{name}] {count}건 예측 완료 (ensemble + SWA)")

    # Save
    save_swa_state(swa_state)
    df.to_csv(CSV_PATH, index=False)
    print(f"\n총 {total_predicted}건 예측, CSV 저장 완료")


if __name__ == "__main__":
    main()
