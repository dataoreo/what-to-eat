
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv


BASE_URL = "https://openapi.foodsafetykorea.go.kr/api"
SERVICE_ID = "COOKRCP01"

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"

# .env 파일에서 API 인증키 불러오기
load_dotenv(BASE_DIR / ".env")
API_KEY = os.getenv("RECIPE_API_KEY")


def fetch_recipes(start, end, api_key):
    if not api_key:
        raise ValueError("API 인증키가 없습니다.")

    url = (
        f"{BASE_URL}/{api_key}/{SERVICE_ID}"
        f"/json/{start}/{end}"
    )

    response = requests.get(url, timeout=20)
    response.raise_for_status()  # HTTP 응답 오류 시 예외 발생

    data = response.json()
    result = data.get(SERVICE_ID, {})

    if "row" not in result:
        raise ValueError(f"API 응답 오류: {data}")

    return result


def fetch_all_recipes(api_key, page_size=1000):
    if not 1 <= page_size <= 1000:
        raise ValueError(
            "page_size는 1에서 1000 사이의 값이어야 합니다."
        )

    all_recipes = []

    # 첫 번째 페이지 요청
    result = fetch_recipes(1, page_size, api_key)

    total_count = int(result["total_count"])
    print(f"총 레시피 수: {total_count}")

    all_recipes.extend(result["row"])
    print(f"수집 진행: {len(all_recipes)} / {total_count}")

    # 나머지 페이지 요청
    for start in range(page_size + 1, total_count + 1, page_size):
        end = min(start + page_size - 1, total_count)

        time.sleep(1)  # API 호출 간격

        result = fetch_recipes(start, end, api_key)
        all_recipes.extend(result["row"])

        print(f"수집 진행: {len(all_recipes)} / {total_count}")

    # 전체 수집 건수 검증
    if len(all_recipes) != total_count:
        raise ValueError(
            f"수집된 레시피 수가 예상과 다릅니다. "
            f"수집된 수: {len(all_recipes)}, "
            f"예상 수: {total_count}"
        )

    # 레시피 ID 중복 검사
    recipe_ids = [
        recipe["RCP_SEQ"] for recipe in all_recipes
    ]

    if len(recipe_ids) != len(set(recipe_ids)):
        raise ValueError("중복된 레시피 ID가 존재합니다.")

    return all_recipes


def save_recipes(recipes, filename="recipes_raw.json"):
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    file_path = RAW_DIR / filename
    temp_path = file_path.with_suffix(".tmp")

    # 임시 파일에 먼저 저장
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(recipes, f, ensure_ascii=False, indent=4)

    temp_path.replace(file_path)

    print(f"\n저장 완료: {file_path}")
    print(f"수집 레시피 수: {len(recipes)}개")


if __name__ == "__main__":
    recipes = fetch_all_recipes(API_KEY)
    save_recipes(recipes)