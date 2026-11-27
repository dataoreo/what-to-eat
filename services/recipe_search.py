"""레시피 이름 검색 및 상세 조회 서비스.

services/recipe_search.py 위치에 저장한다.
MySQL 연결은 기존 recommend.py의 설정을 재사용한다.
"""

import json
from services.recommend import get_connection

def search_recipes(keyword, category=None, limit=30):
    """이름에 검색어가 포함되는 레시피를 조회한다."""
    keyword = keyword.strip()
    if not keyword:
        return []
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError('limit은 1~100 사이의 정수여야 합니다.')

    # LIKE의 %, _, \\ 문자를 문자 그대로 검색하도록 이스케이프한다.
    escaped = keyword.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    pattern = f'%{escaped}%'
    sql = '''
        SELECT recipe_id, recipe_name, category, cooking_method, image_url
        FROM recipes
        WHERE recipe_name LIKE %s
    '''
    params = [pattern]
    if category not in (None, '', '전체'):
        sql += ' AND category = %s'
        params.append(category)
    sql += ' ORDER BY recipe_name ASC, recipe_id ASC LIMIT %s'
    params.append(limit)

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(sql, tuple(params))
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

def get_recipe_detail(recipe_id):
    """레시피 1개의 기본 정보, 조리 순서, 필요 재료를 반환한다."""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute('''
            SELECT recipe_id, recipe_name, category, cooking_method,
                   image_url, instructions, original_text
            FROM recipes
            WHERE recipe_id = %s
        ''', (recipe_id,))
        recipe = cursor.fetchone()
        if recipe is None:
            return None

        # MySQL Connector 설정에 따라 JSON이 문자열로 반환될 수 있다.
        instructions = recipe.get('instructions')
        if isinstance(instructions, str):
            recipe['instructions'] = json.loads(instructions) if instructions else []
        elif instructions is None:
            recipe['instructions'] = []

        cursor.execute('''
            SELECT ri.original_name, i.canonical_name, ri.amount, ri.section
            FROM recipe_ingredients AS ri
            JOIN ingredients AS i ON i.ingredient_id = ri.ingredient_id
            WHERE ri.recipe_id = %s
            ORDER BY ri.id
        ''', (recipe_id,))
        recipe['ingredients'] = cursor.fetchall()
        return recipe
    finally:
        cursor.close()
        conn.close()