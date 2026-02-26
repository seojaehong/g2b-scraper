"""
나라장터(G2B) 용역 입찰공고 자동 수집 스크립트
API: getBidPblancListInfoServcPPSSrch (나라장터검색조건에 의한 입찰공고용역조회)
"""
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

import requests
import pandas as pd
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv()

# ── 설정 ──────────────────────────────────────────────
API_KEY = os.getenv("G2B_API_KEY")
BASE_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcPPSSrch"
KEYWORDS = ["성희롱", "성폭력", "여성폭력", "여성", "여성노동", "성평등", "조직문화 진단", "조직문화"]
NUM_OF_ROWS = 100  # 페이지당 건수
OUTPUT_DIR = Path(__file__).parent / "output" / "g2b"

# 추출할 필드
FIELDS = {
    "bidNtceNo": "입찰공고번호",
    "bidNtceNm": "공고명",
    "ntceInsttNm": "공고기관명",
    "dminsttNm": "수요기관명",
    "bidNtceDt": "공고일시",
    "bidClseDt": "입찰마감일시",
    "asignBdgtAmt": "배정예산",
    "presmptPrce": "추정가격",
    "bidNtceDtlUrl": "상세URL",
}


def get_search_period() -> tuple[str, str]:
    """어제(D-1) 하루를 검색 기간으로 반환 (yyyyMMddHHmm 형식)."""
    yesterday = datetime.now() - timedelta(days=1)
    begin = yesterday.strftime("%Y%m%d") + "0000"
    end = yesterday.strftime("%Y%m%d") + "2359"
    return begin, end


def fetch_page(page_no: int, begin: str, end: str) -> dict:
    """API 1페이지 호출."""
    params = {
        "serviceKey": API_KEY,
        "pageNo": page_no,
        "numOfRows": NUM_OF_ROWS,
        "type": "json",
        "inqryBgnDt": begin,
        "inqryEndDt": end,
    }
    resp = requests.get(BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_all(begin: str, end: str) -> list[dict]:
    """모든 페이지를 순회하며 공고 목록 수집."""
    page_no = 1
    items = []

    while True:
        print(f"  페이지 {page_no} 조회 중...")
        data = fetch_page(page_no, begin, end)

        # 응답 구조 파싱
        body = data.get("response", {}).get("body", {})
        total = int(body.get("totalCount", 0))

        if total == 0:
            break

        page_items = body.get("items", [])
        if isinstance(page_items, list):
            items.extend(page_items)
        elif isinstance(page_items, dict):
            # 단건일 때 dict로 올 수 있음
            items.append(page_items)

        # 마지막 페이지 판단
        if page_no * NUM_OF_ROWS >= total:
            break
        page_no += 1

    print(f"  총 {len(items)}건 조회 완료 (totalCount={total if items else 0})")
    return items


def filter_by_keywords(items: list[dict]) -> list[dict]:
    """공고명에 키워드가 포함된 건만 필터링."""
    matched = []
    for item in items:
        name = item.get("bidNtceNm", "")
        if any(kw in name for kw in KEYWORDS):
            matched.append(item)
    print(f"  키워드 매칭: {len(matched)}건")
    return matched


def extract_fields(items: list[dict]) -> list[dict]:
    """필요한 필드만 추출."""
    rows = []
    for item in items:
        row = {}
        for api_key, label in FIELDS.items():
            row[label] = item.get(api_key, "")
        # 금액: 배정예산 우선, 없으면 추정가격
        budget = row["배정예산"] or row["추정가격"]
        row["금액"] = f"{int(budget):,}원" if budget and str(budget).isdigit() else str(budget) if budget else "미공개"
        rows.append(row)
    return rows


def format_amount(val) -> str:
    """금액 포맷팅."""
    if not val or val == "미공개":
        return "미공개"
    try:
        return f"{int(float(val)):,}원"
    except (ValueError, TypeError):
        return str(val)


def save_markdown(rows: list[dict], date_str: str):
    """마크다운 파일 저장."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUT_DIR / f"{date_str}_G2B_용역공고.md"

    kw_display = ", ".join(KEYWORDS)
    lines = [f"# {date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} 나라장터 신규 용역 공고 (키워드 매칭)\n"]
    lines.append(f"검색 키워드: {kw_display}\n")

    if not rows:
        lines.append("\n> 해당 날짜에 매칭되는 신규 공고가 없습니다.\n")
    else:
        lines.append(f"\n총 **{len(rows)}건** 매칭\n")
        for i, row in enumerate(rows, 1):
            lines.append(f"## {i}. {row['공고명']}\n")
            lines.append(f"- **공고기관:** {row['공고기관명']} (수요기관: {row['수요기관명']})")
            lines.append(f"- **공고번호:** {row['입찰공고번호']}")
            lines.append(f"- **공고일시:** {row['공고일시']}")
            lines.append(f"- **마감일시:** {row['입찰마감일시']}")
            lines.append(f"- **배정예산:** {row['금액']}")
            url = row.get("상세URL", "")
            if url:
                lines.append(f"- **링크:** {url}")
            else:
                lines.append(f"- **링크:** https://www.g2b.go.kr (나라장터에서 공고번호로 검색)")
            lines.append("\n---\n")

    filepath.write_text("\n".join(lines), encoding="utf-8")
    print(f"  MD 저장: {filepath}")


def save_csv(rows: list[dict], date_str: str):
    """CSV 파일 저장."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUT_DIR / f"{date_str}_G2B_용역공고.csv"

    if rows:
        df = pd.DataFrame(rows)
        df.to_csv(filepath, index=False, encoding="utf-8-sig")
    else:
        filepath.write_text("해당 날짜에 매칭되는 신규 공고가 없습니다.\n", encoding="utf-8-sig")

    print(f"  CSV 저장: {filepath}")


def main():
    if not API_KEY:
        print("[ERROR] .env 파일에 G2B_API_KEY를 설정해 주세요.")
        print("  공공데이터포털(data.go.kr)에서 Decoding 키를 복사하세요.")
        sys.exit(1)

    begin, end = get_search_period()
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    print(f"=== G2B 용역 입찰공고 수집 ({yesterday}) ===")
    print(f"  검색기간: {begin} ~ {end}")

    try:
        items = fetch_all(begin, end)
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] API 호출 실패: {e}")
        sys.exit(1)
    except (KeyError, ValueError) as e:
        print(f"[ERROR] 응답 파싱 실패: {e}")
        sys.exit(1)

    matched = filter_by_keywords(items)
    rows = extract_fields(matched)

    save_markdown(rows, yesterday)
    save_csv(rows, yesterday)
    print("=== 완료 ===")


if __name__ == "__main__":
    main()
