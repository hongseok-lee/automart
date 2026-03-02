"""
Best 5 모델 선택: search_results/*/metrics.json에서 val_rmse 기준 top 5 선택.
선택된 모델을 models/{name}_top{0-4}.json으로 복사.
"""
import glob
import json
import os
import shutil

SEARCH_DIR = "search_results"
MODEL_DIR = "models"
TARGETS = ["carnival", "sorento"]
TOP_K = 5


def main():
    # Load all metrics
    pattern = os.path.join(SEARCH_DIR, "*", "metrics.json")
    metric_files = sorted(glob.glob(pattern))
    print(f"발견된 metrics 파일: {len(metric_files)}개")

    if not metric_files:
        print("metrics 파일 없음, 종료")
        return

    all_metrics = []
    for mf in metric_files:
        with open(mf) as f:
            data = json.load(f)
        all_metrics.append(data)

    os.makedirs(MODEL_DIR, exist_ok=True)
    best_configs = {}

    for name in TARGETS:
        # Filter configs that have metrics for this target
        candidates = []
        for m in all_metrics:
            if name in m and "val_rmse" in m[name]:
                candidates.append({
                    "config_id": m["config_id"],
                    "config": m["config"],
                    "val_rmse": m[name]["val_rmse"],
                    "val_mae": m[name]["val_mae"],
                    "val_r2": m[name]["val_r2"],
                    "test_rmse": m[name].get("test_rmse"),
                    "test_r2": m[name].get("test_r2"),
                })

        if not candidates:
            print(f"[{name}] 후보 없음")
            continue

        # Sort by val_rmse ascending → top K
        candidates.sort(key=lambda x: x["val_rmse"])
        top = candidates[:TOP_K]

        print(f"\n[{name}] Top {len(top)} configs (by val_rmse):")
        for rank, c in enumerate(top):
            cid = c["config_id"]
            src = os.path.join(SEARCH_DIR, str(cid), f"{name}_model.json")
            dst = os.path.join(MODEL_DIR, f"{name}_top{rank}.json")

            if os.path.exists(src):
                shutil.copy2(src, dst)
                print(f"  #{rank} config={cid} val_rmse={c['val_rmse']:,.0f} "
                      f"test_rmse={c.get('test_rmse', 0):,.0f} → {dst}")
            else:
                print(f"  #{rank} config={cid} 모델 파일 없음: {src}")

        best_configs[name] = top

    # Save best configs record
    best_path = os.path.join(MODEL_DIR, "best_configs.json")
    with open(best_path, "w") as f:
        json.dump(best_configs, f, indent=2)
    print(f"\nBest configs 저장: {best_path}")


if __name__ == "__main__":
    main()
