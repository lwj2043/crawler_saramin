import pandas as pd
import re
import emoji

def clean_text(text):
    """모든 이모지 제거 + 글머리 기호 정리 + 가독성 향상"""
    if pd.isna(text):
        return text
    
    # 1. 모든 이모지 제거 (emoji 라이브러리 사용)
    text = emoji.replace_emoji(text, replace='')
    
    # 2. 글머리 기호 줄바꿈 처리 (•, -, · 등 → \n- )
    text = re.sub(r'\s*[•\-\·]\s*', r'\n- ', text)
    
    # 3. 연속 공백 제거
    text = re.sub(r'\s{2,}', ' ', text)
    
    # 4. 특수문자 정리 (불필요한 기호 제거)
    text = re.sub(r'[|※]', ' ', text)
    
    # 5. 문장부호 정리
    text = re.sub(r'\.{2,}', '…', text)   # ... -> …
    text = re.sub(r',,', ',', text)       # ,, -> ,
    text = re.sub(r'\?{2,}', '?', text)   # ?? -> ?
    
    # 6. 주요 키워드 구분선 추가
    keywords = ["자격요건", "주요업무", "우대사항", "복리후생", "근무조건", "모집부문", "전형절차"]
    for kw in keywords:
        text = re.sub(rf'\s*{kw}', f'\n\n=== {kw} ===', text)
    
    # 7. 한글-영어 사이 띄어쓰기 보정
    text = re.sub(r'([가-힣])([A-Za-z])', r'\1 \2', text)
    text = re.sub(r'([A-Za-z])([가-힣])', r'\1 \2', text)
    
    # 8. 중복 줄바꿈 제거
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()

def process_csv(input_file, output_file, target_column="responsibilities"):
    """CSV 파일을 정제하고 새로운 파일 저장"""
    df = pd.read_csv(input_file)
    df[f"{target_column}_cleaned"] = df[target_column].apply(clean_text)
    df.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"✅ 정제된 파일이 저장되었습니다: {output_file}")

if __name__ == "__main__":
    input_path = "saramin_cleaned.csv"      
    output_path = "saramin_cleaned_final.csv"  
    process_csv(input_path, output_path)
