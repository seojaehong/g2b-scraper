"""
Notion 데이터베이스 연동 모듈
매일 수집된 공고를 Notion DB에 페이지로 추가
"""
import os
import json

import requests


NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def get_headers() -> dict:
    """Notion API 인증 헤더."""
    token = os.getenv("NOTION_TOKEN")
    if not token:
        raise ValueError("NOTION_TOKEN 환경변수가 설정되지 않았습니다.")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def format_amount(val) -> str:
    """금액 포맷팅."""
    if not val:
        return "미공개"
    try:
        return f"{int(float(val)):,}원"
    except (ValueError, TypeError):
        return str(val)


def build_attachment_blocks(attachments: list[dict]) -> list[dict]:
    """첨부파일을 Notion 블록(bulleted_list_item)으로 변환."""
    blocks = []
    if not attachments:
        return blocks

    # 첨부파일 헤더
    blocks.append({
        "object": "block",
        "type": "heading_3",
        "heading_3": {
            "rich_text": [{"type": "text", "text": {"content": "첨부파일"}}]
        }
    })

    for att in attachments:
        name = att.get("filename", "첨부")
        url = att.get("url", "")
        if url:
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{
                        "type": "text",
                        "text": {"content": name, "link": {"url": url}},
                    }]
                }
            })
    return blocks


def create_page(database_id: str, row: dict, date_str: str, headers: dict):
    """Notion DB에 공고 1건을 페이지로 추가."""
    attachments = row.get("첨부파일", [])
    budget = row.get("배정예산", "") or row.get("추정가격", "")
    detail_url = row.get("상세URL", "") or row.get("공고URL", "")

    properties = {
        "공고명": {
            "title": [{"text": {"content": row.get("공고명", "")}}]
        },
        "공고번호": {
            "rich_text": [{"text": {"content": row.get("입찰공고번호", "")}}]
        },
        "공고기관": {
            "rich_text": [{"text": {"content": row.get("공고기관명", "")}}]
        },
        "수요기관": {
            "rich_text": [{"text": {"content": row.get("수요기관명", "")}}]
        },
        "공고일시": {
            "rich_text": [{"text": {"content": row.get("공고일시", "")}}]
        },
        "마감일시": {
            "rich_text": [{"text": {"content": row.get("입찰마감일시", "")}}]
        },
        "배정예산": {
            "rich_text": [{"text": {"content": format_amount(budget)}}]
        },
        "계약방법": {
            "rich_text": [{"text": {"content": row.get("계약체결방법명", "")}}]
        },
        "용역구분": {
            "rich_text": [{"text": {"content": row.get("용역구분명", "")}}]
        },
        "수집일": {
            "rich_text": [{"text": {"content": date_str}}]
        },
    }

    # 상세 URL
    if detail_url:
        properties["링크"] = {"url": detail_url}

    # 페이지 본문: 기본 정보 + 첨부파일 링크
    children = []

    # 기본 정보 블록
    info_lines = [
        f"담당자: {row.get('담당자명', '')} ({row.get('담당자전화', '')})",
        f"낙찰방법: {row.get('낙찰방법명', '')}",
    ]
    for line in info_lines:
        children.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": line}}]
            }
        })

    # 첨부파일 블록
    children.extend(build_attachment_blocks(attachments))

    payload = {
        "parent": {"database_id": database_id},
        "properties": properties,
        "children": children,
    }

    resp = requests.post(f"{NOTION_API}/pages", headers=headers, json=payload, timeout=30)
    if resp.status_code != 200:
        print(f"    [ERROR] Notion 페이지 생성 실패: {resp.status_code} {resp.text[:200]}")
        return False
    return True


def push_to_notion(rows: list[dict], database_id: str, date_str: str):
    """수집 결과를 Notion DB에 누적 추가."""
    if not database_id:
        print("  [SKIP] NOTION_DATABASE_ID 미설정")
        return

    try:
        headers = get_headers()
    except ValueError as e:
        print(f"  [SKIP] {e}")
        return

    added = 0
    for row in rows:
        if create_page(database_id, row, date_str, headers):
            added += 1

    print(f"  Notion: {added}건 추가 완료")
