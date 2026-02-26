# G2B 나라장터 용역 입찰공고 자동 수집 봇

공공데이터포털 '조달청 나라장터 입찰공고정보서비스' API를 활용하여,
여성노동법률지원센터 관련 키워드의 용역 입찰 공고를 매일 자동 수집합니다.

## 검색 키워드
성희롱, 성폭력, 여성폭력, 여성, 여성노동, 성평등, 조직문화 진단, 조직문화

## 설치 및 실행

```bash
pip install -r requirements.txt
cp .env.example .env
# .env 파일에 공공데이터포털 Decoding 키 입력
python g2b_scraper.py
```

## 출력
- `output/g2b/YYYYMMDD_G2B_용역공고.md`
- `output/g2b/YYYYMMDD_G2B_용역공고.csv`
