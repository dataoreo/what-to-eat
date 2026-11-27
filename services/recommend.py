"""냉장고에 보유한 식재료로 레시피를 추천한다.

프로젝트 루트에서 실행:
    python services/recommend.py

사용 예시:
    from services.recommend import recommend_recipes
    recipes = recommend_recipes(['계란', '연두부', '칵테일새우'])
"""

import os
import sys
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv


# 프로젝트 폴더를 기준으로 .env와 표준화 코드를 찾는다.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / '.env'
sys.path.insert(0, str(PROJECT_ROOT / 'etl'))
from normalize_ingredients import normalize  # noqa: E402


def normalize_user_ingredients(names):
    """사용자 입력을 DB와 동일한 표준 식재료명으로 변환한다."""
    result = []
    seen = set()

    for name in names:
        if not isinstance(name, str) or not name.strip():
            continue

        # 기존 ETL에서 사용한 표준화 규칙을 그대로 재사용한다.
        canonical, _ = normalize(name)
        if canonical and canonical not in seen:
            result.append(canonical)
            seen.add(canonical)

    return result


def get_connection():
    """.env에서 접속 정보를 읽어 MySQL 연결을 생성한다."""
    load_dotenv(ENV_PATH)
    return mysql.connector.connect(
        host=os.getenv('DB_HOST', '127.0.0.1'),
        port=int(os.getenv('DB_PORT', '3306')),
        user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME', 'what_to_eat'),
        charset='utf8mb4',
    )


def get_recipe_categories():
    """MySQL에 저장된 요리 종류를 조회하여 선택지로 반환한다."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            SELECT DISTINCT category
            FROM recipes
            WHERE category IS NOT NULL AND TRIM(category) <> ''
            ORDER BY category
        ''')
        return [row[0] for row in cursor.fetchall()]
    finally:
        cursor.close()
        conn.close()


def recommend_recipes(my_ingredients, limit=20, category=None):
    """일치율이 높은 레시피와 부족 재료 목록을 반환한다.

    - 재료명 존재 여부만 비교한다. 실제 보유 수량은 계산하지 않는다.
    - 같은 재료가 한 레시피에 여러 번 나와도 일치율은 한 번만 센다.
    - 보유한 재료가 하나도 일치하지 않는 레시피는 결과에서 제외한다.
    - category가 지정되면 해당 요리 종류만 추천한다.
    """
    names = normalize_user_ingredients(my_ingredients)
    if not names:
        return []
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError('limit은 1~100 사이의 정수여야 합니다.')

    # 사용자 입력 개수만큼 SQL 바인딩 기호(%s)를 만든다.
    # 입력값은 SQL 문자열에 직접 붙이지 않고 매개변수로 전달한다.
    placeholders = ', '.join(['%s'] * len(names))

    # '전체' 또는 None이면 모든 종류를 검색하고, 그 외에는 선택한 분류만 조회한다.
    selected_category = None if category in (None, '', '전체') else category
    category_condition = 'WHERE r.category = %s' if selected_category else ''

    # 레시피 안의 중복 재료를 제거한 뒤, 보유 재료 일치율을 계산한다.
    score_sql = f'''
        SELECT
            r.recipe_id,
            r.recipe_name,
            COUNT(*) AS total_count,
            SUM(CASE WHEN i.canonical_name IN ({placeholders}) THEN 1 ELSE 0 END) AS matched_count
        FROM (
            SELECT DISTINCT recipe_id, ingredient_id
            FROM recipe_ingredients
        ) AS req
        JOIN recipes AS r ON r.recipe_id = req.recipe_id
        JOIN ingredients AS i ON i.ingredient_id = req.ingredient_id
        {category_condition}
        GROUP BY r.recipe_id, r.recipe_name
        HAVING matched_count > 0
        ORDER BY
            matched_count / total_count DESC,
            matched_count DESC,
            total_count ASC,
            r.recipe_id ASC
        LIMIT %s
    '''

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        score_params = (*names, selected_category, limit) if selected_category else (*names, limit)
        cursor.execute(score_sql, score_params)
        scores = cursor.fetchall()
        if not scores:
            return []

        # 상위 추천 레시피들의 재료를 한 번의 쿼리로 조회한다.
        recipe_ids = [row['recipe_id'] for row in scores]
        id_placeholders = ', '.join(['%s'] * len(recipe_ids))
        detail_sql = f'''
            SELECT
                ri.recipe_id,
                i.canonical_name,
                ri.original_name,
                ri.amount,
                ri.section
            FROM recipe_ingredients AS ri
            JOIN ingredients AS i ON i.ingredient_id = ri.ingredient_id
            WHERE ri.recipe_id IN ({id_placeholders})
            ORDER BY ri.id
        '''
        cursor.execute(detail_sql, tuple(recipe_ids))
        detail_rows = cursor.fetchall()

    finally:
        cursor.close()
        conn.close()

    owned = set(names)
    recipes = {}

    for row in scores:
        recipe_id = row['recipe_id']
        total = int(row['total_count'])
        matched = int(row['matched_count'])
        recipes[recipe_id] = {
            'recipe_id': recipe_id,
            'recipe_name': row['recipe_name'],
            'total_count': total,
            'matched_count': matched,
            'missing_count': total - matched,
            'match_rate': round(matched / total * 100, 1),
            'matched_ingredients': [],
            'missing_ingredients': [],
            'ingredient_details': [],
        }

    # 한 레시피에 같은 재료가 반복되어도 보유/부족 목록에는 한 번만 넣는다.
    seen_by_recipe = {recipe_id: set() for recipe_id in recipe_ids}
    for ing in detail_rows:
        recipe_id = ing['recipe_id']
        canonical = ing['canonical_name']
        is_owned = canonical in owned
        recipes[recipe_id]['ingredient_details'].append({
            'canonical_name': canonical,
            'original_name': ing['original_name'],
            'amount': ing['amount'],
            'section': ing['section'],
            'status': '보유' if is_owned else '부족',
        })

        if canonical not in seen_by_recipe[recipe_id]:
            key = 'matched_ingredients' if is_owned else 'missing_ingredients'
            recipes[recipe_id][key].append(canonical)
            seen_by_recipe[recipe_id].add(canonical)

    # ORDER BY로 정렬된 순서를 보존한다.
    return [recipes[recipe_id] for recipe_id in recipe_ids]


if __name__ == '__main__':
    # 콘솔에서 쉼표로 재료명을 입력받아 간단히 테스트한다.
    user_input = input('보유한 식재료를 쉼표로 구분해 입력하세요 (예: 계란, 연두부, 칵테일새우): ')
    names = [name.strip() for name in user_input.split(',')]

    results = recommend_recipes(names, limit=10)
    if not results:
        print('입력한 재료와 일치하는 레시피가 없습니다.')

    for index, recipe in enumerate(results, start=1):
        print(f"\n{index}. {recipe['recipe_name']} (일치율 {recipe['match_rate']}%)")
        print(f"   보유 {recipe['matched_count']}/{recipe['total_count']}개: {', '.join(recipe['matched_ingredients'])}")
        print(f"   부족 {recipe['missing_count']}개: {', '.join(recipe['missing_ingredients'])}")
