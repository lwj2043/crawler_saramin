import asyncio
import pandas as pd
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import re
from bs4 import BeautifulSoup
import emoji

# --- 설정 ---
KEYWORDS = ['IT', '자율주행', '모빌리티']
TARGET_JOB_COUNT = 100  # 키워드별 수집할 목표 공고 개수

# --- 텍스트 정제 함수 (preprocessed.py 통합) ---
def clean_text(text):
    """모든 이모지 제거 + 글머리 기호 정리 + 가독성 향상"""
    if pd.isna(text) or not text:
        return ""

    # 1. 모든 이모지 제거
    text = emoji.replace_emoji(text, replace='')

    # 2. 글머리 기호 줄바꿈
    text = re.sub(r'\s*[•\-\·]\s*', r'\n- ', text)

    # 3. 연속 공백 제거
    text = re.sub(r'\s{2,}', ' ', text)

    # 4. 특수문자 정리
    text = re.sub(r'[|※]', ' ', text)

    # 5. 문장부호 정리
    text = re.sub(r'\.{2,}', '…', text)
    text = re.sub(r',,', ',', text)
    text = re.sub(r'\?{2,}', '?', text)

    # 6. 주요 키워드 구분선
    keywords = ["자격요건", "주요업무", "우대사항", "복리후생", "근무조건", "모집부문", "전형절차"]
    for kw in keywords:
        text = re.sub(rf'\s*{kw}', f'\n\n=== {kw} ===', text)

    # 7. 한글-영어 띄어쓰기
    text = re.sub(r'([가-힣])([A-Za-z])', r'\1 \2', text)
    text = re.sub(r'([A-Za-z])([가-힣])', r'\1 \2', text)

    # 8. 중복 줄바꿈 제거
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()

# --- 상세 내용 파싱 ---
def parse_responsibilities_robust(html_content, fallback_text):
    soup = BeautifulSoup(html_content, 'lxml')
    start_keywords = re.compile(r'담당\s*업무|주요\s*업무|업무\s*내용')
    end_keywords = re.compile(r'자격\s*요건|지원\s*자격|필수\s*역량|우대\s*사항')
    
    start_tag = soup.find(lambda tag: tag.get_text(strip=True) and start_keywords.search(tag.get_text()))
    if start_tag:
        content_parts = []
        for sibling in start_tag.find_next_siblings():
            if sibling.get_text(strip=True) and end_keywords.search(sibling.get_text()):
                break
            if sibling.get_text(strip=True):
                content_parts.append(sibling.get_text(separator='\n', strip=True))
        if content_parts:
            return '\n'.join(content_parts)

    all_text = soup.get_text()
    start_match = start_keywords.search(all_text)
    if start_match:
        text_after_start = all_text[start_match.end():]
        end_match = end_keywords.search(text_after_start)
        if end_match:
            text_after_start = text_after_start[:end_match.start()]
        if text_after_start.strip():
            return text_after_start
        
    return fallback_text

# --- 크롤링 ---
async def scrape_saramin(page, keyword):
    print(f"사람인에서 '{keyword}' 키워드 검색 시작 (목표: {TARGET_JOB_COUNT}개)")
    base_info_list = []
    current_page = 1
    
    while len(base_info_list) < TARGET_JOB_COUNT:
        page_url = f"https://www.saramin.co.kr/zf_user/search?search_area=main&search_done=y&search_optional_item=n&searchType=search&searchword={keyword}&recruitPage={current_page}"
        print(f"[{keyword}] {current_page} 페이지 수집 중... (현재 {len(base_info_list)}개)")
        await page.goto(page_url, wait_until="domcontentloaded")

        try:
            await page.wait_for_selector(".item_recruit", timeout=5000)
        except PlaywrightTimeoutError:
            print(f"[{keyword}] 더 이상 공고가 없어 중단")
            break
            
        job_listings = await page.locator(".item_recruit").all()
        for job_listing in job_listings:
            try:
                link_element = job_listing.locator('.job_tit a')
                link = await link_element.get_attribute('href')
                full_link = "https://www.saramin.co.kr" + link if link and not link.startswith('http') else link
                title = await job_listing.locator('.job_tit a').inner_text()
                company = await job_listing.locator('.corp_name a').inner_text()
                base_info_list.append({'link': full_link, 'title': title.strip(), 'company': company.strip()})
                if len(base_info_list) >= TARGET_JOB_COUNT:
                    break
            except Exception:
                pass
        if len(base_info_list) >= TARGET_JOB_COUNT:
            break
        current_page += 1

    print(f"[{keyword}] 총 {len(base_info_list)}개 공고 수집 완료. 상세 분석 시작")
    detailed_jobs = []
    
    for i, base_info in enumerate(base_info_list):
        try:
            await page.goto(base_info['link'], wait_until="domcontentloaded", timeout=30000)
            content_context = page
            try:
                await page.wait_for_selector("iframe[id^='iframe_content']", timeout=3000)
                content_context = page.frame_locator("iframe[id^='iframe_content']").first
            except PlaywrightTimeoutError:
                pass
            
            body_locator = content_context.locator('body')
            html_content = await body_locator.inner_html()
            inner_text = await body_locator.inner_text()
            
            responsibilities_raw = parse_responsibilities_robust(html_content, inner_text)
            
            # --- 최종 정제 적용 ---
            responsibilities_clean = clean_text(responsibilities_raw)
            
            base_info['source'] = "사람인"
            base_info['keyword'] = keyword
            base_info['responsibilities'] = responsibilities_clean
            detailed_jobs.append(base_info)
            print(f"[{keyword}] {i+1}번째 공고 처리 완료: {base_info['title']}")
        except Exception:
            print(f"[{keyword}] {i+1}번째 공고 처리 실패: {base_info.get('link', '알 수 없는 URL')}")

    await page.close()
    return detailed_jobs

# --- 메인 실행 ---
async def main():
    all_jobs = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
        
        tasks = []
        for keyword in KEYWORDS:
            page = await context.new_page()
            tasks.append(scrape_saramin(page, keyword))
            
        results = await asyncio.gather(*tasks)
        for result_list in results:
            all_jobs.extend(result_list)

        await browser.close()

    if all_jobs:
        df = pd.DataFrame(all_jobs)
        df = df[['source', 'keyword', 'title', 'company', 'link', 'responsibilities']]
        df.to_csv("saramin_final.csv", index=False, encoding="utf-8-sig")
        print(f"\n스크레이핑 + 정제 완료! 'saramin_final.csv' 파일에 총 {len(all_jobs)}개 공고 저장됨.")
    else:
        print("\n수집된 채용 공고 없음.")

if __name__ == "__main__":
    asyncio.run(main())
