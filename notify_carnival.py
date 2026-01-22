#!/usr/bin/env python3
"""
카니발 KA4 (2020-2023년식) 신규 등록 알림 스크립트
새로 추가된 카니발이 있으면 ntfy.sh로 푸시 알림 전송
- TBD(경매예정) 포함
"""

import pandas as pd
import urllib.request
import sys
import os

NTFY_TOPIC = os.environ.get('NTFY_TOPIC', 'automart-carnival-d8e8afda')
TARGET_YEARS = [2020, 2021, 2022, 2023]

def get_carnival_ka4(df):
    """카니발 KA4 (2020-2023년식) 필터링"""
    carnival = df[df['차량모델'].str.contains('카니발', case=False, na=False)]
    ka4 = carnival[carnival['모델연도'].isin(TARGET_YEARS)]
    return ka4

def find_new_entries(old_csv, new_csv):
    """새로 추가된 카니발 KA4 찾기"""
    try:
        old_df = pd.read_csv(old_csv)
    except:
        old_df = pd.DataFrame()

    new_df = pd.read_csv(new_csv)

    old_ka4 = get_carnival_ka4(old_df)
    new_ka4 = get_carnival_ka4(new_df)

    if old_ka4.empty:
        return new_ka4

    # 고유키: 차량번호 + 경매일시
    old_keys = set(zip(old_ka4['차량번호'], old_ka4['경매일시']))

    new_entries = []
    for _, row in new_ka4.iterrows():
        key = (row['차량번호'], row['경매일시'])
        if key not in old_keys:
            new_entries.append(row)

    return pd.DataFrame(new_entries)

def send_notification(cars_df):
    """ntfy.sh로 알림 전송"""
    if cars_df.empty:
        print("새로운 카니발 KA4 없음")
        return

    count = len(cars_df)

    # 메시지 구성
    lines = [f"카니발 KA4 {count}대 신규!\n"]

    for _, car in cars_df.iterrows():
        year = int(car['모델연도'])
        model = car['차량모델'][:25]

        # 낙찰금액 파싱
        bid_str = str(car['낙찰금액']).strip()
        if bid_str == 'TBD' or bid_str == '':
            price_str = "경매예정"
        else:
            try:
                price = int(bid_str.replace(',', '')) // 10000
                price_str = f"{price:,}만원"
            except:
                price_str = "가격미정"

        # 주행거리
        try:
            km = str(car['주행거리'])
            km_str = f"{km}km"
        except:
            km_str = ""

        lines.append(f"[{year}년] {model}")
        lines.append(f"{price_str} / {km_str}")
        lines.append(f"{car.get('상세URL', '')}\n")

    message = "\n".join(lines)

    # ntfy.sh 전송 (urllib 사용)
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode('utf-8'),
        headers={"Priority": "high", "Tags": "car"}
    )

    try:
        with urllib.request.urlopen(req) as resp:
            if resp.status == 200:
                print(f"✅ 알림 전송 성공: 카니발 KA4 {count}대")
            else:
                print(f"❌ 알림 전송 실패: {resp.status}")
                sys.exit(1)
    except Exception as e:
        print(f"❌ 알림 전송 에러: {e}")
        sys.exit(1)

def main():
    old_csv = "automart_master_backup.csv"
    new_csv = "automart_master.csv"

    new_cars = find_new_entries(old_csv, new_csv)
    send_notification(new_cars)

if __name__ == "__main__":
    main()
