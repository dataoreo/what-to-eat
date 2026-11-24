
import json
import os
import random
import time
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types, errors
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent

RAW_PATH = BASE_DIR / "data" / "raw" / "recipes_raw.json"

# 레시피별 식재료 추출 결과
OUTPUT_PATH = (
    BASE_DIR / "data" / "processed" / "ingredients_extracted.json"
)

# 중복을 제거한 고유 식재료 목록
UNIQUE_PATH = (
    BASE_DIR / "data" / "processed" / "ingredients_unique.json"
)

load_dotenv(BASE_DIR / ".env")
API_KEY = os.getenv("GEMINI_API_KEY")

MODEL_NAME = "gemini-3.5-flash-lite"

LIMIT = None         # 테스트: 3개 / 전체: None
MAX_RETRIES = 3     # 503 오류 시 최대 3번 시도
REQUEST_INTERVAL = 5

class Ingredient(BaseModel):
    original_name: str   # 원본 재료명
    amount: str | None   # 수량 및 단위
    section: str | None  # 주재료, 양념장 등

class IngredientResult(BaseModel):
    ingredients: list[Ingredient]

def load_recipes():
    with open(RAW_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_existing_results():
    if not OUTPUT_PATH.exists():
        return []

    with open(OUTPUT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data, file_path):
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # 임시 파일에 저장한 후 최종 파일로 교체
    temp_path = file_path.with_suffix(".tmp")

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    temp_path.replace(file_path)

def transform_recipe(client, recipe):

    prompt = f"""
다음은 식품안전나라에서 수집한 레시피 데이터입니다.

레시피명: {recipe['RCP_NM']}

재료 원문:
{recipe['RCP_PARTS_DTLS']}

당신의 작업은 식재료 이름과 수량을 정확하게 추출하는 것입니다.

[추출 규칙]

1. 원문에 등장하는 모든 식재료를 추출하세요.
2. 원문에 없는 식재료를 추가하지 마세요.
3. 원문의 재료 순서를 유지하세요.
4. 같은 재료가 여러 번 등장해도 각각 추출하세요.

[재료명]

5. original_name에는 원문에 적힌 재료명을 그대로 기록하세요.
6. 재료명을 표준화하거나 다른 이름으로 바꾸지 마세요.

예시:
- 다진 마늘 → 다진 마늘
- 통마늘 → 통마늘
- 칵테일새우 → 칵테일새우
- 무염버터 → 무염버터
- 조선부추 → 조선부추
- 통깨 → 통깨

7. 다진, 볶은, 무염, 저염 등의 수식어를 제거하지 마세요.
8. 요리명이나 재료 구분 제목을 식재료로 추출하지 마세요.

[수량]

9. amount에는 원문에 적힌 수량과 단위를 그대로 기록하세요.

예시:
- 20g(5마리)
- 2g(1/2쪽)
- 7g(1⅓작은술)
- 약간

10. 수량이 없는 경우 null로 표시하세요.
11. 수량을 임의로 계산하거나 변환하지 마세요.

[재료 구분]

12. section에는 해당 재료가 속한 구분을 기록하세요.
13. 원문에 구분이 없다면 "주재료"로 지정하세요.
14. 요리명이 구분 제목으로 사용됐다면 "주재료"로 지정하세요.

[최종 확인]

15. 원문의 모든 식재료가 빠짐없이 추출되었는지 확인하세요.
16. 응답은 지정된 JSON 구조를 따르세요.
"""

    # 503 서버 혼잡 오류에 대한 자동 재시도
    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=IngredientResult,
                    temperature=0,
                ),
            )

            if response.parsed is None:
                raise ValueError("Gemini 응답 파싱 실패")

            return response.parsed.model_dump()

        except errors.ServerError as e:
            # 503 오류가 아니라면 즉시 중단
            if e.code != 503:
                raise

            if attempt == MAX_RETRIES - 1:
                raise

            # 실패할 때마다 대기 시간 증가
            wait_time = (
                2 ** (attempt + 1)
                + random.uniform(0, 1)
            )

            print(f"503 오류: {wait_time:.1f}초 후 재시도")
            time.sleep(wait_time)

def create_unique_ingredients(results):

    # 각 식재료가 몇 개의 레시피에 등장하는지 계산
    counter = Counter()

    for result in results:
        # 같은 레시피 안에 동일 재료가 여러 번 등장해도
        # 레시피 수는 한 번만 계산
        names = {
            ingredient["original_name"].strip()
            for ingredient in result["ingredients"]
            if ingredient["original_name"].strip()
        }

        counter.update(names)

    # 등장 레시피 수가 많은 순서로 정렬
    unique_ingredients = [
        {
            "name": name,
            "recipe_count": count,
        }
        for name, count in counter.most_common()
    ]

    save_json(unique_ingredients, UNIQUE_PATH)

    print(f"고유 식재료 수: {len(unique_ingredients)}개")

def main():
    if not API_KEY:
        raise ValueError("GEMINI_API_KEY가 없습니다.")

    recipes = load_recipes()

    # LIMIT=None이면 전체 레시피 처리
    target_recipes = (
        recipes[:LIMIT] if LIMIT is not None else recipes
    )

    # 이전에 처리했던 결과 불러오기
    results = load_existing_results()

    # 이미 처리한 레시피 ID
    completed_ids = {
        result["recipe_id"] for result in results
    }

    client = genai.Client(api_key=API_KEY)

    try:
        for recipe in target_recipes:
            recipe_id = recipe["RCP_SEQ"]
            recipe_name = recipe["RCP_NM"]

            # 이미 추출한 레시피라면 건너뛰기
            if recipe_id in completed_ids:
                print(f"건너뛰기: {recipe_name}")
                continue

            print(f"추출 중: {recipe_name}")

            # 재료 원문이 없는 레시피 처리
            if not recipe["RCP_PARTS_DTLS"].strip():
                print("재료 원문 없음")

                results.append({
                    "recipe_id": recipe_id,
                    "recipe_name": recipe_name,
                    "status": "missing",
                    "original_text": "",
                    "ingredients": [],
                })

                completed_ids.add(recipe_id)
                save_json(results, OUTPUT_PATH)
                continue

            try:
                # Gemini API 호출
                transformed = transform_recipe(client, recipe)

                results.append({
                    "recipe_id": recipe_id,
                    "recipe_name": recipe_name,
                    "status": "completed",
                    "original_text": recipe["RCP_PARTS_DTLS"],
                    "ingredients": transformed["ingredients"],
                })

                # 레시피 1개 처리할 때마다 저장
                save_json(results, OUTPUT_PATH)

                completed_ids.add(recipe_id)

                print(
                    f"완료: {len(transformed['ingredients'])}개 재료"
                )

                # 다음 API 호출 전 대기
                time.sleep(REQUEST_INTERVAL)

            except Exception as e:
                print(f"추출 실패 ({recipe_id}): {e}")
                break

    finally:
        client.close()

    # 현재까지 처리된 결과로 고유 식재료 목록 생성
    create_unique_ingredients(results)

    print(f"\n처리된 레시피 수: {len(results)}개")


if __name__ == "__main__":
    main()