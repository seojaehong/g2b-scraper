# G2B Scraper 설정 가이드

## 1. 기본 설정

`.env` 파일에 API 키 설정:

```
G2B_API_KEY=your_decoding_key_here
```

## 2. Google Sheets 연동 (선택)

### 서비스 계정 생성
1. [Google Cloud Console](https://console.cloud.google.com/) → 새 프로젝트 생성
2. **Google Sheets API** + **Google Drive API** 활성화
3. **서비스 계정** 생성 → JSON 키 다운로드

### 스프레드시트 준비
1. Google Sheets에서 새 스프레드시트 생성
2. 서비스 계정 이메일(`xxx@xxx.iam.gserviceaccount.com`)에 **편집자** 권한 공유
3. 스프레드시트 URL에서 ID 복사 (`/d/{이 부분}/edit`)

### 환경변수
```
GOOGLE_SHEET_ID=your_spreadsheet_id
```

**로컬**: JSON 키 파일을 `credentials.json`으로 저장 (또는 `GOOGLE_CREDENTIALS_FILE` 지정)

**GitHub Actions**: `GOOGLE_CREDENTIALS_JSON` 시크릿에 JSON 내용 전체 붙여넣기

## 3. Notion 연동 (선택)

### 통합 생성
1. [Notion Integrations](https://www.notion.so/my-integrations) → 새 통합 생성
2. **Internal Integration** 선택, 토큰 복사

### 데이터베이스 준비
Notion에서 데이터베이스 생성 후 아래 속성 추가:

| 속성명 | 타입 |
|--------|------|
| 공고명 | Title |
| 공고번호 | Rich text |
| 공고기관 | Rich text |
| 수요기관 | Rich text |
| 공고일시 | Rich text |
| 마감일시 | Rich text |
| 배정예산 | Rich text |
| 계약방법 | Rich text |
| 용역구분 | Rich text |
| 수집일 | Rich text |
| 링크 | URL |

데이터베이스 페이지에서 통합을 **연결(Connect)** 하고, URL에서 DB ID 복사.

### 환경변수
```
NOTION_TOKEN=secret_xxx
NOTION_DATABASE_ID=your_database_id
```

## 4. GitHub Actions

Repository Settings → Secrets에 필요한 값 추가:

| Secret | 필수 | 설명 |
|--------|------|------|
| `G2B_API_KEY` | O | 공공데이터포털 Decoding 키 |
| `GOOGLE_SHEET_ID` | - | 스프레드시트 ID |
| `GOOGLE_CREDENTIALS_JSON` | - | 서비스 계정 JSON 전체 |
| `NOTION_TOKEN` | - | Notion 통합 토큰 |
| `NOTION_DATABASE_ID` | - | Notion DB ID |

매일 KST 07:00에 자동 실행됩니다. Actions 탭에서 수동 실행도 가능합니다.
