"""
나라장터(G2B) 사전규격공개 자동 수집 스크립트
API: 사전규격정보서비스 - 나라장터 검색조건에 의한 사전규격 용역 목록 조회
End Point: https://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService
- 본공고보다 2~3주 먼저 올라오는 사전규격을 수집하여 입찰 준비 시간 확보
"""
import sys
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import pandas as pd
from dotenv import load_dotenv

from integrations.google_sheets import push_prespec_to_sheets

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv()

# ── 설정 ──────────────────────────────────────────────
API_KEY = os.getenv("G2B_API_KEY")

# HTTPS 필수 (HTTP는 403)
BASE_URL = "https://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService/getPublicPrcureThngInfoServcPPSSrch"

KEYWORDS = [
    "성희롱", "성폭력", "여성폭력", "여성", "여성노동", "성평등",
    "고용평등", "직장 내 괴롭힘", "괴롭힘", "조직문화", "조직문화 진단",
]
NUM_OF_ROWS = 100
OUTPUT_DIR = Path(__file__).parent / "output" / "g2b_prespec"

# API 응답 필드 매핑 (실제 확인된 필드)
FIELDS = {
    "bfSpecRgstNo": "사전규격등록번호",
    "refNo": "참조번호",
    "bsnsDivNm": "업무구분",
    "prdctClsfcNoNm": "품명(사업명)",
    "orderInsttNm": "발주기관명",
    "rlDminsttNm": "수요기관명",
    "asignBdgtAmt": "배정예산액",
    "rcptDt": "접수일시",
    "opninRgstClseDt": "의견등록마감일",
    "dlvrTmlmtDt": "납품기한",
    "dlvrDaynum": "납품일수",
    "rgstDt": "등록일시",
    "chgDt": "변경일시",
    "ofclNm": "담당자명",
    "ofclTelNo": "담당자전화",
    "swBizObjYn": "SW사업대상여부",
    "bidNtceNoList": "입찰공고번호목록",
}


def get_search_period(days_ago: int = 7) -> tuple[str, str]:
    """검색 기간 반환. 사전규격은 7일 범위로 수집 (본공고보다 넓게)."""
    KST = timezone(timedelta(hours=9))
    end_dt = datetime.now(KST)
    begin_dt = end_dt - timedelta(days=days_ago)
    begin = begin_dt.strftime("%Y%m%d") + "0000"
    end = end_dt.strftime("%Y%m%d") + "2359"
    return begin, end


def fetch_page(page_no: int, begin: str, end: str) -> dict:
    """API 1페이지 호출."""
    params = {
        "serviceKey": API_KEY,
        "inqryDiv": "1",  # 1=접수일시
        "pageNo": str(page_no),
        "numOfRows": str(NUM_OF_ROWS),
        "type": "json",
        "inqryBgnDt": begin,
        "inqryEndDt": end,
    }
    resp = requests.get(BASE_URL, params=params, timeout=30)

    if resp.status_code != 200:
        print(f"  [WARN] HTTP {resp.status_code}")
        resp.raise_for_status()

    text = resp.text.strip()
    if text.startswith("<"):
        print(f"  [ERROR] XML 에러 응답: {text[:500]}")
        raise ValueError("API가 XML 에러를 반환했습니다.")

    return resp.json()


def fetch_all(begin: str, end: str) -> list[dict]:
    """모든 페이지를 순회하며 사전규격 목록 수집."""
    page_no = 1
    items = []
    total = 0

    while True:
        print(f"  페이지 {page_no} 조회 중...")
        data = fetch_page(page_no, begin, end)

        body = data.get("response", {}).get("body", {})
        total = int(body.get("totalCount", 0))

        if total == 0:
            break

        page_items = body.get("items", [])
        if isinstance(page_items, list):
            items.extend(page_items)
        elif isinstance(page_items, dict):
            items.append(page_items)

        if page_no * NUM_OF_ROWS >= total:
            break
        page_no += 1

    print(f"  총 {len(items)}건 조회 완료 (totalCount={total})")
    return items


def filter_by_keywords(items: list[dict]) -> list[dict]:
    """품명(사업명)에 키워드가 포함된 건만 필터링."""
    matched = []
    for item in items:
        name = item.get("prdctClsfcNoNm", "")
        hit_keywords = [kw for kw in KEYWORDS if kw in name]
        if hit_keywords:
            item["_matched_keywords"] = hit_keywords
            matched.append(item)
    print(f"  키워드 매칭: {len(matched)}건")
    return matched


def extract_spec_docs(item: dict) -> list[dict]:
    """규격서 첨부파일 URL 추출 (specDocFileUrl1~5)."""
    attachments = []
    for i in range(1, 6):
        url = item.get(f"specDocFileUrl{i}", "")
        if url and url.strip():
            attachments.append({"url": url.strip(), "filename": f"규격서{i}"})
    return attachments


def extract_fields(items: list[dict]) -> list[dict]:
    """필요한 필드만 추출."""
    rows = []
    for item in items:
        row = {}
        for api_key, label in FIELDS.items():
            row[label] = item.get(api_key, "")
        # 금액 포맷
        budget = row.get("배정예산액", "")
        try:
            row["금액"] = f"{int(float(budget)):,}원" if budget else "미공개"
        except (ValueError, TypeError):
            row["금액"] = str(budget) if budget else "미공개"
        # 규격서 첨부파일
        row["첨부파일"] = extract_spec_docs(item)
        # 매칭 키워드
        row["매칭키워드"] = item.get("_matched_keywords", [])
        # 상세 URL: 규격서 파일이 있으면 직접 다운로드 링크, 없으면 나라장터 검색
        reg_no = row.get("사전규격등록번호", "")
        attachments = row["첨부파일"]
        if attachments:
            row["상세URL"] = attachments[0]["url"]
        elif reg_no:
            row["상세URL"] = f"https://www.g2b.go.kr/link/PRCA001_04/single/?srch=0002&befSpecRgstNo={reg_no}"
        else:
            row["상세URL"] = ""
        rows.append(row)
    return rows


def save_markdown(rows: list[dict], date_str: str):
    """마크다운 파일 저장."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUT_DIR / f"{date_str}_G2B_사전규격.md"

    kw_display = ", ".join(KEYWORDS)
    lines = [f"# {date_str} 나라장터 사전규격공개 (키워드 매칭)\n"]
    lines.append(f"검색 키워드: {kw_display}\n")

    if not rows:
        lines.append("\n> 해당 기간에 매칭되는 사전규격이 없습니다.\n")
    else:
        lines.append(f"\n총 **{len(rows)}건** 매칭\n")
        for i, row in enumerate(rows, 1):
            lines.append(f"## {i}. {row['품명(사업명)']}\n")
            lines.append(f"- **등록번호:** {row['사전규격등록번호']}")
            lines.append(f"- **참조번호:** {row['참조번호']}")
            lines.append(f"- **발주기관:** {row['발주기관명']} (수요: {row['수요기관명']})")
            lines.append(f"- **접수일시:** {row['접수일시']}")
            lines.append(f"- **의견마감:** {row['의견등록마감일']}")
            lines.append(f"- **납품기한:** {row['납품기한']}")
            lines.append(f"- **배정예산:** {row['금액']}")
            lines.append(f"- **담당자:** {row['담당자명']} ({row['담당자전화']})")

            url = row.get("상세URL", "")
            if url:
                lines.append(f"- **링크:** {url}")

            attachments = row.get("첨부파일", [])
            if attachments:
                lines.append(f"- **규격서:** ({len(attachments)}건)")
                for att in attachments:
                    lines.append(f"  - [{att['filename']}]({att['url']})")

            lines.append("\n---\n")

    filepath.write_text("\n".join(lines), encoding="utf-8")
    print(f"  MD 저장: {filepath}")


def save_csv(rows: list[dict], date_str: str):
    """CSV 파일 저장."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUT_DIR / f"{date_str}_G2B_사전규격.csv"

    if rows:
        csv_rows = []
        for row in rows:
            csv_row = {k: v for k, v in row.items() if k != "첨부파일"}
            atts = row.get("첨부파일", [])
            csv_row["첨부파일수"] = len(atts)
            csv_row["첨부파일목록"] = " | ".join(a["filename"] for a in atts)
            csv_rows.append(csv_row)
        df = pd.DataFrame(csv_rows)
        df.to_csv(filepath, index=False, encoding="utf-8-sig")
    else:
        filepath.write_text("해당 기간에 매칭되는 사전규격이 없습니다.\n", encoding="utf-8-sig")

    print(f"  CSV 저장: {filepath}")


def main():
    if not API_KEY:
        print("[ERROR] .env 파일에 G2B_API_KEY를 설정해 주세요.")
        sys.exit(1)

    KST = timezone(timedelta(hours=9))
    today = datetime.now(KST).strftime("%Y%m%d")
    begin, end = get_search_period(days_ago=7)
    print(f"=== G2B 사전규격공개 수집 ({today}) ===")
    print(f"  검색기간: {begin} ~ {end}")

    try:
        items = fetch_all(begin, end)
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] API 호출 실패: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    matched = filter_by_keywords(items)
    rows = extract_fields(matched)

    # 디버깅: 키워드 매칭 0건일 때 샘플 출력
    if items and not matched:
        print(f"  [INFO] 전체 {len(items)}건 중 키워드 매칭 0건")
        print(f"  [INFO] 샘플 사업명: {items[0].get('prdctClsfcNoNm', '')}")

    save_markdown(rows, today)
    save_csv(rows, today)

    # Google Sheets 연동
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
    if sheet_id:
        print("  Google Sheets 연동...")
        try:
            push_prespec_to_sheets(rows, sheet_id, today)
        except Exception as e:
            print(f"  [ERROR] Google Sheets: {e}")

    # Notion 연동
    notion_db_id = os.getenv("NOTION_DATABASE_ID", "")
    if notion_db_id:
        print("  Notion 연동...")
        try:
            from integrations.notion_db import push_to_notion
            push_to_notion(rows, notion_db_id, today)
        except Exception as e:
            print(f"  [ERROR] Notion: {e}")

    print("=== 완료 ===")


if __name__ == "__main__":
    main()
