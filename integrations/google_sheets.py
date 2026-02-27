"""
Google Sheets 연동 모듈
매일 수집된 공고를 스프레드시트에 누적 추가
"""
import os
import json
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# 시트 헤더
HEADERS = [
    "수집일", "공고번호", "차수", "공고명", "공고기관", "수요기관",
    "공고일시", "마감일시", "배정예산", "추정가격", "계약방법", "낙찰방법",
    "용역구분", "담당자", "담당자전화", "상세링크",
    "매칭키워드",
    "첨부1", "첨부2", "첨부3", "첨부4", "첨부5",
]


def get_client() -> gspread.Client:
    """서비스 계정으로 gspread 클라이언트 생성."""
    # GitHub Actions: 환경변수에 JSON 문자열
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        info = json.loads(creds_json)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        # 로컬: 파일 경로
        creds_path = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
        creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return gspread.authorize(creds)


def ensure_sheet(client: gspread.Client, spreadsheet_id: str, sheet_name: str = "공고목록"):
    """시트가 없으면 생성, 헤더 추가."""
    spreadsheet = client.open_by_key(spreadsheet_id)
    try:
        worksheet = spreadsheet.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=len(HEADERS))
        worksheet.append_row(HEADERS)
    # 헤더가 비어있으면 추가
    if not worksheet.row_values(1):
        worksheet.append_row(HEADERS)
    return worksheet


def format_attachment_links(attachments: list[dict], max_count: int = 5) -> list[str]:
    """첨부파일을 하이퍼링크 수식으로 변환."""
    links = []
    for att in attachments[:max_count]:
        name = att.get("filename", "첨부")
        url = att.get("url", "")
        if url:
            links.append(f'=HYPERLINK("{url}","{name}")')
        else:
            links.append("")
    # 나머지 빈 칸 채우기
    while len(links) < max_count:
        links.append("")
    return links


def push_to_sheets(rows: list[dict], spreadsheet_id: str, date_str: str):
    """수집 결과를 Google Sheets에 누적 추가."""
    if not spreadsheet_id:
        print("  [SKIP] GOOGLE_SHEET_ID 미설정")
        return

    client = get_client()
    worksheet = ensure_sheet(client, spreadsheet_id)

    added = 0
    for row in rows:
        attachments = row.get("첨부파일", [])
        att_links = format_attachment_links(attachments)

        sheet_row = [
            date_str,
            row.get("입찰공고번호", ""),
            row.get("입찰공고차수", ""),
            row.get("공고명", ""),
            row.get("공고기관명", ""),
            row.get("수요기관명", ""),
            row.get("공고일시", ""),
            row.get("입찰마감일시", ""),
            row.get("배정예산", ""),
            row.get("추정가격", ""),
            row.get("계약체결방법명", ""),
            row.get("낙찰방법명", ""),
            row.get("용역구분명", ""),
            row.get("담당자명", ""),
            row.get("담당자전화", ""),
            row.get("상세URL", "") or row.get("공고URL", ""),
            ", ".join(row.get("매칭키워드", [])),
        ] + att_links

        worksheet.append_row(sheet_row, value_input_option="USER_ENTERED")
        added += 1

    print(f"  Google Sheets: {added}건 추가 완료")

    # 키워드별 현황 시트 업데이트
    update_keyword_summary(client, spreadsheet_id, rows, date_str)


def update_keyword_summary(client: gspread.Client, spreadsheet_id: str, rows: list[dict], date_str: str):
    """키워드별 일별 매칭 건수 현황 시트 업데이트."""
    from collections import Counter

    KEYWORDS = [
        "성희롱", "성폭력", "여성폭력", "여성", "여성노동", "성평등",
        "고용평등", "직장 내 괴롭힘", "괴롭힘", "조직문화", "조직문화 진단",
    ]
    SUMMARY_HEADERS = ["날짜"] + KEYWORDS + ["합계"]

    spreadsheet = client.open_by_key(spreadsheet_id)
    try:
        ws = spreadsheet.worksheet("키워드별 현황")
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title="키워드별 현황", rows=500, cols=len(SUMMARY_HEADERS))
        ws.append_row(SUMMARY_HEADERS)
        ws.freeze(rows=1)
        ws.format("A1:M1", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.85, "green": 0.92, "blue": 1.0},
            "horizontalAlignment": "CENTER",
        })

    # 키워드별 카운트
    kw_count = Counter()
    for row in rows:
        for kw in row.get("매칭키워드", []):
            kw_count[kw] += 1

    date_display = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    summary_row = [date_display]
    total = 0
    for kw in KEYWORDS:
        cnt = kw_count.get(kw, 0)
        summary_row.append(cnt)
        total += cnt
    summary_row.append(len(rows))  # 합계는 실제 공고 수 (중복 키워드 제외)

    ws.append_row(summary_row)
    print(f"  키워드별 현황: {date_display} 추가 완료")
