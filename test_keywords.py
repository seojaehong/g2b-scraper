"""
키워드 매칭 테스트 스크립트
2025.01 ~ 2026.01 월별 × 키워드별 API 서버 측 검색(bidNtceNm)으로 빠르게 분석
"""
import sys
import os
import time
from pathlib import Path

import requests
import pandas as pd
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv()

API_KEY = os.getenv("G2B_API_KEY")
BASE_URL = "http://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcPPSSrch"
OUTPUT_DIR = Path(__file__).parent / "output" / "test"

KEYWORDS = ["성희롱", "성폭력", "여성폭력", "여성", "여성노동", "성평등", "조직문화 진단", "조직문화"]

TEST_PERIODS = [
    ("202501010000", "202501312359", "2025-01"),
    ("202502010000", "202502282359", "2025-02"),
    ("202503010000", "202503312359", "2025-03"),
    ("202504010000", "202504302359", "2025-04"),
    ("202505010000", "202505312359", "2025-05"),
    ("202506010000", "202506302359", "2025-06"),
    ("202507010000", "202507312359", "2025-07"),
    ("202508010000", "202508312359", "2025-08"),
    ("202509010000", "202509302359", "2025-09"),
    ("202510010000", "202510312359", "2025-10"),
    ("202511010000", "202511302359", "2025-11"),
    ("202512010000", "202512312359", "2025-12"),
    ("202601010000", "202601312359", "2026-01"),
]


def fetch_by_keyword(begin: str, end: str, keyword: str) -> list[dict]:
    """API의 bidNtceNm 파라미터로 서버 측 검색."""
    page_no = 1
    items = []

    while True:
        params = {
            "serviceKey": API_KEY,
            "inqryDiv": "1",
            "pageNo": str(page_no),
            "numOfRows": "100",
            "type": "json",
            "inqryBgnDt": begin,
            "inqryEndDt": end,
            "bidNtceNm": keyword,
        }
        try:
            resp = requests.get(BASE_URL, params=params, timeout=60)
            if resp.status_code != 200 or resp.text.strip().startswith("<"):
                break
            data = resp.json()
        except Exception as e:
            print(f"      [ERROR] {e}")
            break

        body = data.get("response", {}).get("body", {})
        total = int(body.get("totalCount", 0))
        if total == 0:
            break

        page_items = body.get("items", [])
        if isinstance(page_items, list):
            items.extend(page_items)
        elif isinstance(page_items, dict):
            items.append(page_items)

        if page_no * 100 >= total:
            break
        page_no += 1
        time.sleep(0.2)

    return items


def main():
    if not API_KEY:
        print("[ERROR] .env 파일에 G2B_API_KEY를 설정해 주세요.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── 1단계: 키워드별 × 월별 수집 ──────────────────
    all_items = []  # 중복 포함 전체
    monthly_summary = []

    print("=" * 70)
    print("G2B 키워드 매칭 테스트 (2025.01 ~ 2026.01)")
    print("키워드별 API 서버 측 검색 (bidNtceNm 파라미터)")
    print("=" * 70)

    for begin, end, label in TEST_PERIODS:
        print(f"\n[{label}]")
        row = {"월": label}

        for kw in KEYWORDS:
            items = fetch_by_keyword(begin, end, kw)
            row[kw] = len(items)

            for item in items:
                all_items.append({
                    "월": label,
                    "검색키워드": kw,
                    "공고번호": item.get("bidNtceNo", ""),
                    "공고명": item.get("bidNtceNm", ""),
                    "공고기관": item.get("ntceInsttNm", ""),
                    "수요기관": item.get("dminsttNm", ""),
                    "배정예산": item.get("asignBdgtAmt", ""),
                    "추정가격": item.get("presmptPrce", ""),
                    "용역구분": item.get("srvceDivNm", ""),
                    "공고일시": item.get("bidNtceDt", ""),
                })

            if len(items) > 0:
                print(f"  {kw}: {len(items)}건")
            time.sleep(0.3)

        monthly_summary.append(row)

    # ── 2단계: 중복 제거 및 분석 ──────────────────────
    df_all = pd.DataFrame(all_items)
    if df_all.empty:
        print("\n매칭 결과 없음")
        return

    # 공고번호 기준 중복 제거 (어떤 키워드로 매칭됐는지 병합)
    grouped = df_all.groupby("공고번호").agg({
        "월": "first",
        "검색키워드": lambda x: ", ".join(sorted(set(x))),
        "공고명": "first",
        "공고기관": "first",
        "수요기관": "first",
        "배정예산": "first",
        "추정가격": "first",
        "용역구분": "first",
        "공고일시": "first",
    }).reset_index()

    # "여성" 단독 매칭 = 오탐 후보 분석
    specific_kws = ["성희롱", "성폭력", "여성폭력", "여성노동", "성평등"]
    org_culture_kws = ["조직문화 진단", "조직문화"]

    def classify(row):
        kws = row["검색키워드"]
        name = row["공고명"]
        # 구체적 키워드에 매칭되면 정탐
        if any(sk in kws for sk in specific_kws):
            return "정탐(구체키워드)"
        if any(ok in kws for ok in org_culture_kws):
            # 조직문화 관련
            if "진단" in name or "성평등" in name or "성희롱" in name or "인권" in name:
                return "정탐(조직문화)"
            return "검토필요(조직문화)"
        if "여성" in kws:
            # "여성"만 매칭 - 공고명 분석
            relevant = ["노동", "폭력", "인권", "상담", "지원센터", "법률", "성희롱",
                        "성폭력", "성평등", "고용평등", "차별", "괴롭힘", "권익"]
            if any(r in name for r in relevant):
                return "정탐(여성+관련어)"
            return "오탐후보(여성단독)"
        return "미분류"

    grouped["분류"] = grouped.apply(classify, axis=1)

    # ── 3단계: 결과 저장 ──────────────────────────────
    # 월별 요약
    df_summary = pd.DataFrame(monthly_summary)
    df_summary.to_csv(OUTPUT_DIR / "월별_키워드별_건수.csv", index=False, encoding="utf-8-sig")

    # 전체 매칭 건 (중복 제거)
    grouped.to_csv(OUTPUT_DIR / "전체_매칭_공고_중복제거.csv", index=False, encoding="utf-8-sig")

    # 분류별 저장
    for cls in grouped["분류"].unique():
        subset = grouped[grouped["분류"] == cls]
        safe_name = cls.replace("(", "_").replace(")", "")
        subset.to_csv(OUTPUT_DIR / f"분류_{safe_name}.csv", index=False, encoding="utf-8-sig")

    # ── 4단계: 최종 분석 출력 ─────────────────────────
    print("\n" + "=" * 70)
    print("월별 키워드 매칭 건수")
    print("=" * 70)
    print(df_summary.to_string(index=False))

    print(f"\n총 매칭 (중복 포함): {len(df_all)}건")
    print(f"총 매칭 (중복 제거): {len(grouped)}건")

    print("\n" + "=" * 70)
    print("분류별 건수")
    print("=" * 70)
    cls_counts = grouped["분류"].value_counts()
    for cls, cnt in cls_counts.items():
        print(f"  {cls}: {cnt}건")

    print("\n" + "=" * 70)
    print("오탐 후보 공고명 (여성 단독 매칭)")
    print("=" * 70)
    fp = grouped[grouped["분류"] == "오탐후보(여성단독)"]
    if len(fp) > 0:
        for _, row in fp.head(30).iterrows():
            print(f"  [{row['월']}] {row['공고명'][:70]}")
        if len(fp) > 30:
            print(f"  ... 외 {len(fp) - 30}건")
    else:
        print("  오탐 후보 없음")

    print("\n" + "=" * 70)
    print("검토필요 공고명 (조직문화)")
    print("=" * 70)
    oc = grouped[grouped["분류"] == "검토필요(조직문화)"]
    if len(oc) > 0:
        for _, row in oc.head(20).iterrows():
            print(f"  [{row['월']}] {row['공고명'][:70]}")
    else:
        print("  검토필요 건 없음")

    print("\n=== 테스트 완료 ===")
    print(f"결과 파일: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
