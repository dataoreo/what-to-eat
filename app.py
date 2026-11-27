"""'뭐해먹고살지?' Streamlit 웹 화면.

프로젝트 최상위 폴더에서 실행:
    streamlit run app.py

현재 구현 범위:
    - 식재료를 하나씩 추가하거나 삭제
    - 기존 services/recommend.py로 레시피 추천
    - 일치율 및 보유/부족 재료 표시
"""

import streamlit as st
from mysql.connector import Error as MySQLError

from services.recipe_search import get_recipe_detail, search_recipes
from services.recommend import (
    get_recipe_categories,
    normalize_user_ingredients,
    recommend_recipes,
)


# 브라우저 탭 이름과 화면 폭 설정
st.set_page_config(page_title='뭐해먹고살지?', page_icon='🍳', layout='centered')

# 사용자가 추가한 재료와 추천 결과를 화면 새로고침 사이에도 유지
if 'my_ingredients' not in st.session_state:
    st.session_state.my_ingredients = []
if 'recommended_recipes' not in st.session_state:
    st.session_state.recommended_recipes = None
if 'searched_recipes' not in st.session_state:
    st.session_state.searched_recipes = None
if 'open_recipe' not in st.session_state:
    st.session_state.open_recipe = None


# 새 재료가 추가되거나 삭제되면 이전 추천 결과는 초기화
# 재료를 바꾼 뒤에는 추천 버튼을 다시 눌러 최신 결과를 확인하도록 함
def reset_recommendations():
    st.session_state.recommended_recipes = None


st.title('🍳 뭐해먹고살지?')
st.write('냉장고에 있는 재료를 추가하면 만들 수 있는 레시피를 추천해 드려요.')

recommend_tab, search_tab = st.tabs(['🧊 냉장고 재료 추천', '🔎 레시피 이름 검색'])

with recommend_tab:
    st.subheader('🧊 내 냉장고')

    # form을 사용하면 입력하는 글자마다 화면이 다시 실행되지 않음
    # clear_on_submit=True: 추가 버튼을 누르면 입력창을 자동으로 비움
    with st.form('add_ingredient_form', clear_on_submit=True):
        input_col, button_col = st.columns([4, 1])
        with input_col:
            ingredient_input = st.text_input(
                '식재료 이름',
                placeholder='예: 계란, 양파, 감자',
                label_visibility='collapsed',
            )
        with button_col:
            add_clicked = st.form_submit_button('추가', use_container_width=True)

    # 사용자 입력은 기존 ETL 표준화 함수로 먼저 통일
    # 예: '계란' → '달걀', '다진 마늘' → '마늘'
    if add_clicked:
        raw_name = ingredient_input.strip()
        if not raw_name:
            st.warning('추가할 식재료 이름을 입력해 주세요.')
        else:
            canonical_names = normalize_user_ingredients([raw_name])
            if not canonical_names:
                st.warning('올바른 식재료 이름을 입력해 주세요.')
            elif canonical_names[0] in st.session_state.my_ingredients:
                st.info(f"'{canonical_names[0]}'은(는) 이미 추가한 재료예요.")
            else:
                st.session_state.my_ingredients.append(canonical_names[0])
                reset_recommendations()

    # 등록된 재료를 한 줄씩 보여주며 삭제 버튼 제공
    if st.session_state.my_ingredients:
        st.caption(f"보유 재료 {len(st.session_state.my_ingredients)}개")
        for index, name in enumerate(st.session_state.my_ingredients):
            name_col, remove_col = st.columns([5, 1])
            with name_col:
                st.write(f'🥬 {name}')
            with remove_col:
                if st.button('삭제', key=f'remove_{index}', use_container_width=True):
                    st.session_state.my_ingredients.pop(index)
                    reset_recommendations()
                    st.rerun()
    else:
        st.info('아직 추가한 재료가 없어요. 위 입력창에서 하나씩 추가해 주세요.')

    st.divider()

    # 레시피에 저장된 요리 분류를 DB에서 조회한다.
    # DB 값을 그대로 사용하므로 '국&찌개' 같은 실제 분류명과 정확히 일치한다.
    @st.cache_data(ttl=300)
    def load_categories():
        return ['전체'] + get_recipe_categories()


    try:
        categories = load_categories()
    except MySQLError:
        categories = ['전체']
        st.warning('요리 종류를 불러오지 못했어요. MySQL 연결을 확인해 주세요.')

    # 요리 종류가 변경되면 기존 추천 결과를 지운다.
    category = st.selectbox(
        '🍲 요리 종류',
        options=categories,
        index=0,
        on_change=reset_recommendations,
        key='selected_category',
    )

    # 추천 버튼을 누른 경우에만 DB를 조회함
    # 화면 위젯이 바뀔 때마다 불필요한 MySQL 조회가 발생하지 않도록 분리
    recommend_clicked = st.button(
        '🍽️ 이 재료로 레시피 추천받기',
        type='primary',
        use_container_width=True,
        disabled=not st.session_state.my_ingredients,
    )

    if recommend_clicked:
        try:
            with st.spinner('레시피를 찾고 있어요...'):
                st.session_state.recommended_recipes = recommend_recipes(
                    st.session_state.my_ingredients,
                    limit=20,
                    category=category,
                )
        except MySQLError:
            st.session_state.recommended_recipes = None
            st.error('MySQL 연결 또는 조회에 실패했어요. DB 서버와 .env 설정을 확인해 주세요.')
        except Exception as exc:
            st.session_state.recommended_recipes = None
            st.error(f'추천 기능 실행 중 오류가 발생했어요: {exc}')

    # 추천 전에는 결과 영역을 출력하지 않음
    results = st.session_state.recommended_recipes
    if results is not None:
        st.subheader('📖 추천 레시피')
        if not results:
            st.warning('현재 보유한 재료와 일치하는 레시피가 없어요. 다른 재료를 추가해 보세요.')
        else:
            st.caption(f'재료 일치율 기준 상위 {len(results)}개 레시피')
            for rank, recipe in enumerate(results, start=1):
                with st.container(border=True):
                    st.markdown(f"#### {rank}. {recipe['recipe_name']}")
                    st.progress(
                        recipe['match_rate'] / 100,
                        text=f"추천 점수(검색 일치율) {recipe['match_rate']}% · 보유 {recipe['exact_count']}개 · 부분 일치 {recipe['related_count']}개 / 전체 {recipe['total_count']}개",
                    )

                    have = ', '.join(recipe['matched_ingredients']) or '없음'
                    related = ', '.join(recipe['related_ingredients']) or '없음'
                    missing = ', '.join(recipe['missing_ingredients']) or '없음'
                    st.write(f'✅ **보유 재료:** {have}')
                    if recipe['related_ingredients']:
                        st.write(f'🔎 **유사 재료:** {related}')
                    st.write(f'🛒 **부족한 재료:** {missing}')

                    # 상세 보기에서는 보유 재료를 먼저 표시하고 부족한 재료를 뒤에 표시
                    # sorted는 안정 정렬이므로 같은 상태 안에서는 기존 재료 순서가 유지됨.
                    with st.expander('필요한 재료와 수량 자세히 보기'):
                        sorted_ingredients = sorted(
                            recipe['ingredient_details'],
                            key=lambda ing: {'보유': 0, '유사': 1, '부족': 2}.get(ing['status'], 3),
                        )
                        for ing in sorted_ingredients:
                            label = {'보유': '✅', '유사': '🔎', '부족': '🛒'}.get(ing['status'], '❔')
                            original = ing['original_name']
                            amount = ing['amount'] or '수량 정보 없음'
                            section = ing['section'] or '구분 없음'
                            st.write(f'{label} {original} — {amount} ({section})')

                # 추천받은 레시피에서도 조리 방법을 확인할 수 있다.
                if st.button('🍳 조리 순서 보기', key=f"recommended_detail_{recipe['recipe_id']}"):
                    st.session_state.open_recipe = ('recommend', recipe['recipe_id'])
                if st.session_state.open_recipe == ('recommend', recipe['recipe_id']):
                    try:
                        detail = get_recipe_detail(recipe['recipe_id'])
                        if detail is None:
                            st.warning('레시피 상세 정보를 찾지 못했어요.')
                        else:
                            if detail['image_url']:
                                st.image(detail['image_url'], use_container_width=True)
                            if detail['instructions']:
                                for step in detail['instructions']:
                                    st.write(step.get('text', ''))
                                    if step.get('image_url'):
                                        st.image(step['image_url'], use_container_width=True)
                            else:
                                st.info('등록된 조리 순서가 없어요.')
                    except MySQLError:
                        st.error('조리 순서를 불러오지 못했어요.')

    st.caption('부분 일치 재료는 검색 결과에만 포함되며 실제 보유로 판단하지 않아요. 예: 간장 → 저염간장, 두부 → 연두부·두부면. 이름이 비슷해도 실제로 다른 가공품일 수 있으니 재료를 확인해 주세요. 보유 수량은 아직 확인하지 않아요.')

# 레시피 이름으로 직접 검색하는 두 번째 화면
with search_tab:
    st.subheader('🔎 레시피 이름 검색')
    st.write('먹고 싶은 요리 이름을 검색하면 재료와 만드는 방법을 확인할 수 있어요.')

    # DB에 저장된 분류를 그대로 사용한다.
    try:
        search_categories = load_categories()
    except MySQLError:
        search_categories = ['전체']
        st.warning('요리 종류를 불러오지 못했어요. MySQL 연결을 확인해 주세요.')

    with st.form('recipe_search_form'):
        keyword = st.text_input('요리 이름', placeholder='예: 두부, 된장국, 샐러드')
        search_category = st.selectbox('요리 종류', search_categories, key='search_category')
        search_clicked = st.form_submit_button('🔎 레시피 검색', use_container_width=True)

    if search_clicked:
        if not keyword.strip():
            st.session_state.searched_recipes = None
            st.warning('검색할 요리 이름을 입력해 주세요.')
        else:
            try:
                st.session_state.searched_recipes = search_recipes(
                    keyword, category=search_category, limit=30
                )
            except MySQLError:
                st.session_state.searched_recipes = None
                st.error('MySQL 연결 또는 검색 중 오류가 발생했어요.')

    found = st.session_state.searched_recipes
    if found is not None:
        if not found:
            st.info('검색 결과가 없어요. 다른 이름으로 검색해 보세요.')
        else:
            st.caption(f'검색 결과 {len(found)}개 (최대 30개)')
            for recipe in found:
                with st.container(border=True):
                    st.markdown(f"#### {recipe['recipe_name']}")
                    st.caption(f"종류: {recipe['category'] or '미분류'} · 조리법: {recipe['cooking_method'] or '정보 없음'}")
                    if st.button('재료와 조리 순서 보기', key=f"search_detail_{recipe['recipe_id']}"):
                        st.session_state.open_recipe = ('search', recipe['recipe_id'])
                    if st.session_state.open_recipe == ('search', recipe['recipe_id']):
                        try:
                            detail = get_recipe_detail(recipe['recipe_id'])
                        except MySQLError:
                            st.error('레시피 상세 조회에 실패했어요.')
                            continue
                        if detail is None:
                            st.warning('레시피를 찾을 수 없어요.')
                            continue
                        if detail['image_url']:
                            st.image(detail['image_url'], use_container_width=True)
                        st.markdown('**필요한 재료**')
                        if detail['ingredients']:
                            for ing in detail['ingredients']:
                                amount = ing['amount'] or '수량 정보 없음'
                                section = ing['section'] or '구분 없음'
                                st.write(f"• {ing['original_name']} — {amount} ({section})")
                        else:
                            st.write('등록된 재료 정보가 없어요.')
                        st.markdown('**조리 순서**')
                        if detail['instructions']:
                            for step in detail['instructions']:
                                st.write(step.get('text', ''))
                                if step.get('image_url'):
                                    st.image(step['image_url'], use_container_width=True)
                        else:
                            st.info('등록된 조리 순서가 없어요.')
