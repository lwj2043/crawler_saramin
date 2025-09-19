import asyncio
import pandas as pd
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import re
import os
from PIL import Image
import pytesseract

# --- 설정 ---
KEYWORDS = ['IT', '자율주행', '모빌리티']
SCREENSHOT_DIR = "screenshots"

# --- Tesseract 설정 (오타 수정) ---
# 1. Tesseract 실행 파일 경로 지정 (경로 앞 공백 제거)
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
# 2. Tesseract 언어 데이터 경로(tessdata) 설정 (경로 앞 공백 제거)
tessdata_dir_config = r'--tessdata-dir "C:\Program Files\Tesseract-OCR\tessdata"'


def clean_text(text):
    """텍스트에서 불필요한 공백, 특수문자, 머리글 기호를 정리하고 항목별로 분리합니다."""
    text = re.sub(r'^(담당업무|자격요건|지원자격|우대사항)\s*', '', text).strip()
    text = re.sub(r'[\s\t]*[ㆍ■※●]\s*|[-]\s*', '\n- ', text)
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    cleaned_lines = [re.sub(r'^\s*-\s*', '', line).strip() for line in lines]
    return cleaned_lines

def perform_ocr(image_path):
    """주어진 이미지 파일 경로에 대해 OCR을 수행합니다."""
    try:
        print(f"[INFO] '{image_path}'에 대해 OCR을 수행합니다...")
        text = pytesseract.image_to_string(Image.open(image_path), lang='kor', config=tessdata_dir_config)
        print("[INFO] OCR 완료.")
        return text
    except Exception as e:
        print(f"[ERROR] OCR 처리 중 오류 발생: {e}")
        return ""

async def get_job_details_from_html(page_or_frame):
    """채용 공고 상세 페이지(또는 프레임)의 HTML에서 구조화된 데이터를 추출합니다."""
    details = {"responsibilities": [], "qualifications": [], "preferred": []}
    content_element = None

    try:
        # 1. 기본 컨텐츠 영역 시도
        await page_or_frame.wait_for_selector("div.job_definition", timeout=5000)
        content_element = page_or_frame.locator("div.job_definition")
    except Exception:
        # 2. 실패 시 body 전체를 대상
        print("[INFO] 'div.job_definition'을 찾을 수 없어 body 전체를 파싱합니다.")
        content_element = page_or_frame.locator('body')

    try:
        body_html = await content_element.inner_html()
        text = re.sub(r'<h[2-5].*?>|<strong>|<b>', r'|', body_html, flags=re.IGNORECASE)
        text = re.sub(r'<.*?>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        sections = [s.strip() for s in text.split('|') if s.strip()]

        if sections:
            for section in sections:
                if "담당업무" in section[:10]: details["responsibilities"] = clean_text(section)
                elif "자격요건" in section[:10] or "지원자격" in section[:10]: details["qualifications"] = clean_text(section)
                elif "우대사항" in section[:10]: details["preferred"] = clean_text(section)
        
        # 3. 그래도 내용이 없으면, 보이는 텍스트 전체라도 수집
        if not any(details.values()):
            full_text = await content_element.inner_text()
            details["responsibilities"] = clean_text(full_text)

    except Exception as e:
        print(f"[ERROR] HTML 파싱 중 최종 오류: {e}")
    return details


async def scrape_saramin(page, keyword):
    """사람인에서 특정 키워드로 채용 공고를 스크레이핑합니다."""
    print(f"\n사람인에서 '{keyword}' 키워드로 검색을 시작합니다.")
    url = f"https://www.saramin.co.kr/zf_user/search?search_area=main&search_done=y&search_optional_item=n&searchType=search&searchword={keyword}"
    await page.goto(url, wait_until="domcontentloaded")

    try:
        await page.wait_for_selector(".item_recruit", timeout=10000)
    except PlaywrightTimeoutError:
        print(f"[WARN] 사람인에서 '{keyword}'에 대한 검색 결과가 없거나 로딩에 실패했습니다.")
        return []

    job_listings = await page.locator(".item_recruit").all()
    jobs = []
    print(f"사람인에서 {len(job_listings)}개의 공고를 찾았습니다. 상위 5개 공고의 상세 내용을 수집합니다.")

    for i, job_listing in enumerate(job_listings[:5]):
        print(f"--- {i+1}번째 공고 처리 시작 ---")
        try:
            title_element = job_listing.locator('.job_tit a')
            title = await title_element.inner_text()
            link = await title_element.get_attribute('href')
            full_link = "https://www.saramin.co.kr" + link if link and not link.startswith('http') else link

            company_element = job_listing.locator('.corp_name a')
            company = await company_element.inner_text()
            
            location = "N/A"
            try:
                location_element = job_listing.locator('.job_condition span').first
                location = await location_element.inner_text()
            except Exception:
                pass

            await page.goto(full_link, wait_until="domcontentloaded", timeout=30000)

            content_context = None
            try:
                await page.wait_for_selector("iframe#iframe_content_0", timeout=5000)
                print("[INFO] Iframe을 발견하여 내부 컨텐츠를 처리합니다.")
                content_context = page.frame("iframe_content_0")
                if content_context is None:
                    await page.wait_for_timeout(2000) # 프레임 로드 시간 추가 대기
                    content_context = page.frame("iframe_content_0")
                if content_context is None: raise Exception("Iframe을 찾았지만, 객체를 가져오는 데 실패했습니다.")
            except Exception:
                print("[INFO] Iframe이 없어 메인 페이지를 처리합니다.")
                content_context = page

            html_details = await get_job_details_from_html(content_context)

            screenshot_path = os.path.join(SCREENSHOT_DIR, f"{keyword.replace(' ', '_')}_{i}.png")
            ocr_text = ""
            try:
                screenshot_target = content_context.locator("div.job_definition").first
                if await screenshot_target.count() == 0:
                    screenshot_target = content_context.locator('body')
                
                await screenshot_target.wait_for(state='visible', timeout=5000)
                await screenshot_target.screenshot(path=screenshot_path)
                ocr_text = perform_ocr(screenshot_path)
            except Exception as e:
                print(f"[ERROR] 스크린샷 또는 OCR 실패: {e}")

            jobs.append({
                "source": "사람인",
                "keyword": keyword,
                "title": title.strip(),
                "company": company.strip(),
                "location": location.strip(),
                "link": full_link,
                "responsibilities_html": "\n".join(html_details["responsibilities"]),
                "qualifications_html": "\n".join(html_details["qualifications"]),
                "preferred_html": "\n".join(html_details["preferred"]),
                "ocr_text": ocr_text.strip(),
            })
            
            await page.go_back()
            await page.wait_for_selector(".item_recruit", timeout=10000)

        except Exception as e:
            print(f"[ERROR] 처리 중 오류 발생: {repr(e)}")
            try:
                await page.goto(url, wait_until="domcontentloaded")
            except Exception as recovery_e:
                print(f"[ERROR] 복구 중 오류 발생: {repr(recovery_e)}")
                break
    return jobs


async def main():
    """메인 실행 함수"""
    if not os.path.exists(SCREENSHOT_DIR):
        os.makedirs(SCREENSHOT_DIR)
        print(f"'{SCREENSHOT_DIR}' 폴더를 생성했습니다.")

    all_jobs = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            device_scale_factor=2
        )
        page = await context.new_page()

        for keyword in KEYWORDS:
            saramin_jobs = await scrape_saramin(page, keyword)
            all_jobs.extend(saramin_jobs)

        await browser.close()

    if all_jobs:
        df = pd.DataFrame(all_jobs)
        df = df[[
            "source", "keyword", "title", "company", "location", 
            "responsibilities_html", "qualifications_html", "preferred_html", 
            "ocr_text", "link"
        ]]
        output_filename = "saramin_job_results.csv"
        df.to_csv(output_filename, index=False, encoding="utf-8-sig")
        print(f"\n스크레이핑 및 정제 완료! '{output_filename}' 파일에 총 {len(all_jobs)}개의 공고가 저장되었습니다.")
    else:
        print("\n수집된 채용 공고가 없습니다.")


if __name__ == "__main__":
    asyncio.run(main())