"""
나라장터(G2B) 용역 입찰공고 자동 수집 스크립트
API: getBidPblancListInfoServcPPSSrch (나라장터검색조건에 의한 입찰공고용역조회)
참고: 조달청_OpenAPI참고자료_나라장터_입찰공고정보서비스_1.1.docx
"""
import sys
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

import requests
import pandas as pd
from dotenv import load_dotenv

from integrations.google_sheets import push_to_sheets
from integrations.notion_db import push_to_notion

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv()

# ── 설정 ──────────────────────────────────────────────
API_KEY = os.getenv("G2B_API_KEY")
BASE_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcPPSSrch"
KEYWORDS = ["성희롱", "성폭력", "여성폭력", "여성", "여성노동", "성평등", "고용평등", "직장 내 괴롭힘", "괴롭힘", "조직문화", "조직문화 진단"]
NUM_OF_ROWS = 100
OUTPUT_DIR = Path(__file__).parent / "output" / "g2b"
DOWNLOAD_ATTACHMENTS = True  # 첨부파일 다운로드 여부

# 추출할 주요 필드
FIELDS = {
    "bidNtceNo": "입찰공고번호",
    "bidNtceOrd": "입찰공고차수",
    "bidNtceNm": "공고명",
    "ntceInsttNm": "공고기관명",
    "dminsttNm": "수요기관명",
    "bidNtceDt": "공고일시",
    "bidClseDt": "입찰마감일시",
    "asignBdgtAmt": "배정예산",
    "presmptPrce": "추정가격",
    "bidNtceDtlUrl": "상세URL",
    "bidNtceUrl": "공고URL",
    "cntrctCnclsMthdNm": "계약체결방법명",
    "sucsfbidMthdNm": "낙찰방법명",
    "ntceInsttOfclNm": "담당자명",
    "ntceInsttOfclTelNo": "담당자전화",
    "ntceInsttOfclEmailAdrs": "담당자이메일",
    "srvceDivNm": "용역구분명",
}


def get_search_period(days_ago: int = 1) -> tuple[str, str]:
    """D-N 하루를 검색 기간으로 반환 (yyyyMMddHHmm 형식)."""
    KST = timezone(timedelta(hours=9))
    target = datetime.now(KST) - timedelta(days=days_ago)
    begin = target.strftime("%Y%m%d") + "0000"
    end = target.strftime("%Y%m%d") + "2359"
    return begin, end


def fetch_page(page_no: int, begin: str, end: str) -> dict:
    """API 1페이지 호출. raise_for_status 대신 응답 내용 확인."""
    params = {
        "serviceKey": API_KEY,
        "inqryDiv": "1",  # 필수: 1=공고게시일시, 2=개찰일시
        "pageNo": str(page_no),
        "numOfRows": str(NUM_OF_ROWS),
        "type": "json",
        "inqryBgnDt": begin,
        "inqryEndDt": end,
    }
    resp = requests.get(BASE_URL, params=params, timeout=30)

    # 디버깅: 비정상 응답 처리
    if resp.status_code != 200:
        print(f"  [WARN] HTTP {resp.status_code}")
        print(f"  URL: {resp.url}")
        print(f"  Body: {resp.text[:500]}")
        resp.raise_for_status()

    # XML 에러 응답 체크 (API 키 오류 등)
    text = resp.text.strip()
    if text.startswith("<"):
        # XML 응답 = 에러
        print(f"  [ERROR] XML 에러 응답:")
        print(f"  {text[:500]}")
        raise ValueError("API가 XML 에러를 반환했습니다. 키/파라미터를 확인하세요.")

    return resp.json()


def fetch_all(begin: str, end: str) -> list[dict]:
    """모든 페이지를 순회하며 공고 목록 수집."""
    page_no = 1
    items = []
    total = 0

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
            items.append(page_items)

        if page_no * NUM_OF_ROWS >= total:
            break
        page_no += 1

    print(f"  총 {len(items)}건 조회 완료 (totalCount={total})")
    return items


def filter_by_keywords(items: list[dict]) -> list[dict]:
    """공고명에 키워드가 포함된 건만 필터링. 매칭 키워드도 기록."""
    matched = []
    for item in items:
        name = item.get("bidNtceNm", "")
        hit_keywords = [kw for kw in KEYWORDS if kw in name]
        if hit_keywords:
            item["_matched_keywords"] = hit_keywords
            matched.append(item)
    print(f"  키워드 매칭: {len(matched)}건")
    return matched


def extract_attachments(item: dict) -> list[dict]:
    """공고규격서 첨부파일 URL/파일명 추출 (최대 10개)."""
    attachments = []
    for i in range(1, 11):
        url = item.get(f"ntceSpecDocUrl{i}", "")
        name = item.get(f"ntceSpecFileNm{i}", "")
        if url and url.strip():
            attachments.append({"url": url.strip(), "filename": name.strip() or f"첨부{i}"})
    # 표준공고서
    std_url = item.get("stdNtceDocUrl", "")
    if std_url and std_url.strip():
        attachments.append({"url": std_url.strip(), "filename": "표준공고서"})
    return attachments


def extract_fields(items: list[dict]) -> list[dict]:
    """필요한 필드만 추출 + 첨부파일 정보."""
    rows = []
    for item in items:
        row = {}
        for api_key, label in FIELDS.items():
            row[label] = item.get(api_key, "")
        # 금액 포맷
        budget = row["배정예산"] or row["추정가격"]
        try:
            row["금액"] = f"{int(float(budget)):,}원" if budget else "미공개"
        except (ValueError, TypeError):
            row["금액"] = str(budget) if budget else "미공개"
        # 첨부파일
        row["첨부파일"] = extract_attachments(item)
        # 매칭 키워드
        row["매칭키워드"] = item.get("_matched_keywords", [])
        rows.append(row)
    return rows


def download_attachments(rows: list[dict], date_str: str):
    """매칭된 공고의 첨부파일 다운로드."""
    dl_dir = OUTPUT_DIR / date_str / "첨부파일"
    dl_dir.mkdir(parents=True, exist_ok=True)

    total_files = 0
    for row in rows:
        bid_no = row["입찰공고번호"]
        attachments = row.get("첨부파일", [])
        if not attachments:
            continue

        # 공고별 하위 폴더
        bid_dir = dl_dir / bid_no.replace("/", "_")
        bid_dir.mkdir(parents=True, exist_ok=True)

        for att in attachments:
            url = att["url"]
            filename = att["filename"]
            filepath = bid_dir / filename

            try:
                print(f"    다운로드: {filename}")
                resp = requests.get(url, timeout=30, stream=True)
                if resp.status_code == 200:
                    filepath.write_bytes(resp.content)
                    total_files += 1
                else:
                    print(f"    [WARN] {filename} - HTTP {resp.status_code}")
            except requests.exceptions.RequestException as e:
                print(f"    [ERROR] {filename} - {e}")

    print(f"  첨부파일 {total_files}건 다운로드 완료 → {dl_dir}")


def save_markdown(rows: list[dict], date_str: str):
    """마크다운 파일 저장."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUT_DIR / f"{date_str}_G2B_용역공고.md"

    kw_display = ", ".join(KEYWORDS)
    d = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    lines = [f"# {d} 나라장터 신규 용역 공고 (키워드 매칭)\n"]
    lines.append(f"검색 키워드: {kw_display}\n")

    if not rows:
        lines.append("\n> 해당 날짜에 매칭되는 신규 공고가 없습니다.\n")
    else:
        lines.append(f"\n총 **{len(rows)}건** 매칭\n")
        for i, row in enumerate(rows, 1):
            lines.append(f"## {i}. {row['공고명']}\n")
            lines.append(f"- **공고기관:** {row['공고기관명']} (수요기관: {row['수요기관명']})")
            lines.append(f"- **공고번호:** {row['입찰공고번호']} (차수: {row.get('입찰공고차수', '')})")
            lines.append(f"- **공고일시:** {row['공고일시']}")
            lines.append(f"- **마감일시:** {row['입찰마감일시']}")
            lines.append(f"- **배정예산:** {row['금액']}")
            lines.append(f"- **계약방법:** {row.get('계약체결방법명', '')} / {row.get('낙찰방법명', '')}")
            lines.append(f"- **용역구분:** {row.get('용역구분명', '')}")
            lines.append(f"- **담당자:** {row.get('담당자명', '')} ({row.get('담당자전화', '')})")

            url = row.get("상세URL") or row.get("공고URL") or ""
            if url:
                lines.append(f"- **링크:** {url}")

            # 첨부파일 목록
            attachments = row.get("첨부파일", [])
            if attachments:
                lines.append(f"- **첨부파일:** ({len(attachments)}건)")
                for att in attachments:
                    lines.append(f"  - [{att['filename']}]({att['url']})")

            lines.append("\n---\n")

    filepath.write_text("\n".join(lines), encoding="utf-8")
    print(f"  MD 저장: {filepath}")


def save_csv(rows: list[dict], date_str: str):
    """CSV 파일 저장."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUT_DIR / f"{date_str}_G2B_용역공고.csv"

    if rows:
        # 첨부파일은 파일명 리스트로 변환
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
        filepath.write_text("해당 날짜에 매칭되는 신규 공고가 없습니다.\n", encoding="utf-8-sig")

    print(f"  CSV 저장: {filepath}")


def main():
    if not API_KEY:
        print("[ERROR] .env 파일에 G2B_API_KEY를 설정해 주세요.")
        print("  공공데이터포털(data.go.kr)에서 Decoding 키를 복사하세요.")
        sys.exit(1)

    KST = timezone(timedelta(hours=9))
    begin, end = get_search_period(days_ago=1)
    yesterday = (datetime.now(KST) - timedelta(days=1)).strftime("%Y%m%d")
    print(f"=== G2B 용역 입찰공고 수집 ({yesterday}) ===")
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

    save_markdown(rows, yesterday)
    save_csv(rows, yesterday)

    # 첨부파일 다운로드
    if DOWNLOAD_ATTACHMENTS and rows:
        print("  첨부파일 다운로드 시작...")
        download_attachments(rows, yesterday)

    # Google Sheets 연동
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
    if sheet_id:
        print("  Google Sheets 연동...")
        try:
            push_to_sheets(rows, sheet_id, yesterday)
        except Exception as e:
            print(f"  [ERROR] Google Sheets: {e}")

    # Notion 연동
    notion_db_id = os.getenv("NOTION_DATABASE_ID", "")
    if notion_db_id:
        print("  Notion 연동...")
        try:
            push_to_notion(rows, notion_db_id, yesterday)
        except Exception as e:
            print(f"  [ERROR] Notion: {e}")

    print("=== 완료 ===")


if __name__ == "__main__":
    main()
