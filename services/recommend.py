"""냉장고에 보유한 식재료로 레시피를 추천한다.

프로젝트 루트에서 실행:
    python -m services.recommend

사용 예시:
    from services.recommend import recommend_recipes
    recipes = recommend_recipes(['계란', '연두부', '칵테일새우'])
"""

import os
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv


# 프로젝트 폴더를 기준으로 .env와 표준화 코드를 찾는다.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / '.env'
from etl.normalize_ingredients import normalize


# 부분 일치 검색에서만 제외할 가공품 목록
SEARCH_EXCLUSIONS = {
    '두부': {'두부면', '두부과자'},
    '마늘': {'마늘기름', '마늘가루'},
    '고추': {'고추장', '고추기름', '고춧가루'},
}


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
    - 정확히 일치하거나 입력 이름이 포함된 DB 재료를 사용하는 레시피를 찾는다.
    - 부분 일치 재료는 실제 보유로 표기하지 않고 별도 표시한다.
    - category가 지정되면 해당 요리 종류만 추천한다.
    """
    names = normalize_user_ingredients(my_ingredients)
    if not names:
        return []
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError('limit은 1~100 사이의 정수여야 합니다.')

    # DB 데이터는 변경하지 않고 SQL LIKE로만 검색 범위를 넓힌다.
    # 예: '간장' 입력 → '진간장', '저염간장'도 검색 후보에 포함된다.
    # LIKE의 %, _, \ 문자가 검색 패턴으로 해석되지 않도록 이스케이프한다.
    def escape_like(value):
        return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')

    # 입력 재료마다 LIKE 조건과 제외 조건을 함께 생성한다.
    # 제외 대상이어도 사용자가 그 이름을 정확히 입력한 경우에는 정상 매칭된다.
    like_conditions = []
    like_params = []
    for name in names:
        excluded = sorted(SEARCH_EXCLUSIONS.get(name, set()))
        condition = 'i.canonical_name LIKE %s'
        like_params.append(f'%{escape_like(name)}%')
        if excluded:
            placeholders = ', '.join(['%s'] * len(excluded))
            condition += f' AND i.canonical_name NOT IN ({placeholders})'
            like_params.extend(excluded)
        like_conditions.append(f'({condition})')

    # 정확 일치는 1점, 이름에 입력한 단어가 포함된 부분 일치는 0.5점.
    # 정확 일치 재료가 부분 일치에도 중복 집계되지 않게 NOT IN 조건을 둔다.
    exact_placeholders = ', '.join(['%s'] * len(names))
    related_conditions = ' OR '.join(like_conditions)
    related_expression = f"""
        SUM(CASE
            WHEN i.canonical_name NOT IN ({exact_placeholders})
             AND ({related_conditions})
            THEN 1 ELSE 0
        END)
    """

    selected_category = None if category in (None, '', '전체') else category
    category_condition = 'WHERE r.category = %s' if selected_category else ''

    # 동일 레시피에서 같은 식재료는 한 번만 세도록 DISTINCT 적용
    # 부분 일치 재료를 실제로 '보유'한 것으로 간주하지 않는 것이 핵심이다.
    score_sql = f'''
        SELECT
            r.recipe_id,
            r.recipe_name,
            COUNT(*) AS total_count,
            SUM(CASE WHEN i.canonical_name IN ({exact_placeholders}) THEN 1 ELSE 0 END) AS exact_count,
            {related_expression} AS related_count
        FROM (
            SELECT DISTINCT recipe_id, ingredient_id
            FROM recipe_ingredients
        ) AS req
        JOIN recipes AS r ON r.recipe_id = req.recipe_id
        JOIN ingredients AS i ON i.ingredient_id = req.ingredient_id
        {category_condition}
        GROUP BY r.recipe_id, r.recipe_name
        HAVING exact_count + related_count > 0
        ORDER BY
            (exact_count + related_count * 0.5) / total_count DESC,
            exact_count DESC,
            related_count DESC,
            total_count ASC,
            r.recipe_id ASC
        LIMIT %s
    '''

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        score_params = list(names) + list(names) + like_params
        if selected_category:
            score_params.append(selected_category)
        score_params.append(limit)
        cursor.execute(score_sql, tuple(score_params))
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
    # 문자열 부분 일치 여부는 Python 상세 목록에서도 SQL과 동일하게 판정한다.
    def is_partial_match(canonical):
        return any(
            name in canonical and canonical not in SEARCH_EXCLUSIONS.get(name, set())
            for name in names
        )
    recipes = {}

    for row in scores:
        recipe_id = row['recipe_id']
        total = int(row['total_count'])
        exact = int(row['exact_count'])
        similar = int(row['related_count'])
        matched = exact + similar
        recipes[recipe_id] = {
            'recipe_id': recipe_id,
            'recipe_name': row['recipe_name'],
            'total_count': total,
            'matched_count': matched,  # 검색에 일치한 수(정확+유사)
            'exact_count': exact,  # 실제 보유한 수
            'related_count': similar,  # 부분 일치로만 찾은 재료 수
            'missing_count': total - matched,
            'match_rate': round((exact + similar * 0.5) / total * 100, 1),
            'matched_ingredients': [],
            'related_ingredients': [],
            'missing_ingredients': [],
            'ingredient_details': [],
        }

    # 한 레시피에 같은 재료가 반복되어도 보유/부족 목록에는 한 번만 넣는다.
    seen_by_recipe = {recipe_id: set() for recipe_id in recipe_ids}
    for ing in detail_rows:
        recipe_id = ing['recipe_id']
        canonical = ing['canonical_name']
        is_owned = canonical in owned
        is_related = not is_owned and is_partial_match(canonical)
        recipes[recipe_id]['ingredient_details'].append({
            'canonical_name': canonical,
            'original_name': ing['original_name'],
            'amount': ing['amount'],
            'section': ing['section'],
            'status': '보유' if is_owned else ('유사' if is_related else '부족'),
        })

        if canonical not in seen_by_recipe[recipe_id]:
            key = 'matched_ingredients' if is_owned else ('related_ingredients' if is_related else 'missing_ingredients')
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
        print(f"   보유 {recipe['exact_count']}/{recipe['total_count']}개: {', '.join(recipe['matched_ingredients'])}")
        print(f"   부분 일치 {recipe['related_count']}개: {', '.join(recipe['related_ingredients'])}")
        print(f"   부족 {recipe['missing_count']}개: {', '.join(recipe['missing_ingredients'])}")