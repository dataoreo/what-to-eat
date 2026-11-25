"""공공 레시피 JSON과 표준화된 식재료 JSON을 MySQL에 적재한다.

실행 위치와 무관하게 프로젝트 루트의 data/ 및 .env 경로를 사용한다.
이 파일은 what_to_eat 전용 데이터베이스의 전체 데이터를 새 JSON 기준으로 교체한다.
"""

import json
import os
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = PROJECT_ROOT / 'data/raw/recipes_raw.json'
NORMALIZED_PATH = PROJECT_ROOT / 'data/processed/ingredients_normalized.json'
ENV_PATH = PROJECT_ROOT / '.env'


def read_json(path):
    if not path.is_file():
        raise FileNotFoundError(f'파일을 찾을 수 없습니다: {path}')

    with path.open('r', encoding='utf-8') as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(f'JSON 최상위 구조가 리스트가 아닙니다: {path}')
    return data


def prepare_data(raw_recipes, normalized_recipes):
    if not raw_recipes or not normalized_recipes:
        raise ValueError('입력 JSON이 비어 있습니다. 기존 DB를 교체하지 않습니다.')

    raw_by_id = {}
    for recipe in raw_recipes:
        recipe_id = str(recipe.get('RCP_SEQ', '')).strip()
        if not recipe_id or not str(recipe.get('RCP_NM', '')).strip():
            raise ValueError(f'레시피 ID 또는 이름이 없습니다: {recipe}')
        if recipe_id in raw_by_id:
            raise ValueError(f'중복된 원본 레시피 ID: {recipe_id}')
        raw_by_id[recipe_id] = recipe

    normalized_by_id = {}
    for recipe in normalized_recipes:
        recipe_id = str(recipe.get('recipe_id', '')).strip()
        if not recipe_id or recipe_id in normalized_by_id:
            raise ValueError(f'비어 있거나 중복된 표준화 레시피 ID: {recipe_id}')
        normalized_by_id[recipe_id] = recipe

    if raw_by_id.keys() != normalized_by_id.keys():
        missing_normalized = sorted(raw_by_id.keys() - normalized_by_id.keys())
        missing_raw = sorted(normalized_by_id.keys() - raw_by_id.keys())
        raise ValueError(
            '원본/표준화 레시피 ID가 일치하지 않습니다. '
            f'표준화 누락: {missing_normalized[:10]}, 원본 누락: {missing_raw[:10]}'
        )

    recipe_rows = []
    ingredient_names = set()
    link_rows = []
    skipped = 0

    for recipe_id, raw in raw_by_id.items():
        normalized = normalized_by_id[recipe_id]

        # 빈 조리 순서는 제외하며 단계별 설명과 이미지를 같이 저장한다.
        instructions = []
        for number in range(1, 21):
            step = (raw.get(f'MANUAL{number:02d}') or '').strip()
            image = (raw.get(f'MANUAL_IMG{number:02d}') or '').strip()
            if step:
                instructions.append({'step': number, 'text': step, 'image_url': image})

        recipe_rows.append((
            recipe_id,
            raw['RCP_NM'].strip(),
            raw.get('RCP_PAT2') or None,
            raw.get('RCP_WAY2') or None,
            raw.get('ATT_FILE_NO_MAIN') or raw.get('ATT_FILE_NO_MK') or None,
            json.dumps(instructions, ensure_ascii=False),
            raw.get('RCP_PARTS_DTLS') or None,
        ))

        # 같은 식재료가 레시피에 여러 번 나와도 연결 기록은 보존한다.
        for ing in normalized.get('ingredients', []):
            canonical = ing.get('canonical_name')
            original = ing.get('original_name')
            if not isinstance(canonical, str) or not canonical.strip() or not isinstance(original, str) or not original.strip():
                skipped += 1
                continue

            canonical = canonical.strip()
            ingredient_names.add(canonical)
            link_rows.append((
                recipe_id,
                canonical,  # 실제 ingredient_id는 MySQL INSERT 후 조회해서 넣는다.
                original,
                ing.get('amount'),
                ing.get('section'),
                ing.get('mapping_type'),
            ))

    return recipe_rows, sorted(ingredient_names), link_rows, skipped


def load_to_mysql(recipe_rows, ingredient_names, link_rows):
    load_dotenv(ENV_PATH)
    password = os.getenv('DB_PASSWORD')
    if password is None:
        raise ValueError('.env에 DB_PASSWORD가 없습니다.')

    config = {
        'host': os.getenv('DB_HOST', '127.0.0.1'),
        'port': int(os.getenv('DB_PORT', '3306')),
        'user': os.getenv('DB_USER', 'root'),
        'password': password,
        'database': os.getenv('DB_NAME', 'what_to_eat'),
        'charset': 'utf8mb4',
    }

    # 실수로 다른 데이터베이스의 내용을 삭제하지 않도록 DB 이름을 확인한다.
    if config['database'] != 'what_to_eat':
        raise ValueError('이 전체 적재 스크립트는 what_to_eat 데이터베이스에서만 실행할 수 있습니다.')

    conn = mysql.connector.connect(**config)
    cursor = conn.cursor()

    try:
        # DELETE와 INSERT를 하나의 트랜잭션으로 처리한다.
        # 적재 중 실패하면 rollback으로 기존 데이터가 유지된다.
        conn.start_transaction()

        # 외래 키 관계를 고려해 연결 테이블부터 비운다.
        cursor.execute('DELETE FROM recipe_ingredients')
        cursor.execute('DELETE FROM ingredients')
        cursor.execute('DELETE FROM recipes')

        # 레시피 기본 정보 저장
        cursor.executemany('''
            INSERT INTO recipes
                (recipe_id, recipe_name, category, cooking_method, image_url, instructions, original_text)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        ''', recipe_rows)

        # 표준화된 식재료명은 한 번씩만 저장
        cursor.executemany('''
            INSERT INTO ingredients (canonical_name)
            VALUES (%s)
        ''', [(name,) for name in ingredient_names])

        # 자동 생성된 ingredient_id를 이름 기준으로 조회
        cursor.execute('SELECT ingredient_id, canonical_name FROM ingredients')
        name_to_id = {name: ingredient_id for ingredient_id, name in cursor.fetchall()}

        # 식재료명을 FK 번호로 바꾸어 연결 테이블 저장
        prepared_links = [
            (recipe_id, name_to_id[canonical], original, amount, section, mapping_type)
            for recipe_id, canonical, original, amount, section, mapping_type in link_rows
        ]

        cursor.executemany('''
            INSERT INTO recipe_ingredients
                (recipe_id, ingredient_id, original_name, amount, section, mapping_type)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', prepared_links)

        # 모든 INSERT가 성공했을 때만 DB 변경 사항을 확정한다.
        conn.commit()

        print('MySQL 적재 완료')
        print(f'레시피: {len(recipe_rows):,}개')
        print(f'표준 식재료: {len(ingredient_names):,}개')
        print(f'레시피-식재료 연결: {len(prepared_links):,}개')

    except Exception:
        # 작업 중 오류가 발생하면 해당 트랜잭션의 변경 사항을 되돌린다.
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def main():
    raw = read_json(RAW_PATH)
    normalized = read_json(NORMALIZED_PATH)
    recipes, names, links, skipped = prepare_data(raw, normalized)

    print(f'입력 검증 완료: 레시피 {len(recipes):,}개, 식재료 {len(names):,}개, 연결 {len(links):,}개')
    if skipped:
        print(f'유효하지 않은 재료명으로 제외한 항목: {skipped:,}개')

    load_to_mysql(recipes, names, links)


if __name__ == '__main__':
    main()
