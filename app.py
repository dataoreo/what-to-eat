"""'뭐해먹지?' Streamlit 웹 화면.

프로젝트 최상위 폴더에서 실행:
    streamlit run app.py

현재 구현 범위:
    - 식재료를 하나씩 추가하거나 삭제
    - 기존 services/recommend.py로 레시피 추천
    - 일치율 및 보유/부족 재료 표시
"""

import streamlit as st
from mysql.connector import Error as MySQLError

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


# 새 재료가 추가되거나 삭제되면 이전 추천 결과는 초기화
# 재료를 바꾼 뒤에는 추천 버튼을 다시 눌러 최신 결과를 확인하도록 함
def reset_recommendations():
    st.session_state.recommended_recipes = None


st.title('🍳 뭐해먹고살지?')
st.write('냉장고에 있는 재료를 추가하면 만들 수 있는 레시피를 추천해 드려요.')

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
                    text=f"재료 일치율 {recipe['match_rate']}% · 보유 {recipe['matched_count']}/{recipe['total_count']}개",
                )

                have = ', '.join(recipe['matched_ingredients']) or '없음'
                missing = ', '.join(recipe['missing_ingredients']) or '없음'
                st.write(f'✅ **보유 재료:** {have}')
                st.write(f'🛒 **부족한 재료:** {missing}')

                # 재료별 원래 이름과 수량은 상세 정보에서 확인
                with st.expander('필요한 재료와 수량 자세히 보기'):
                    sorted_ingredients = sorted(
                        recipe['ingredient_details'],
                        key=lambda ing: 0 if ing['status'] == '보유' else 1
                    )

                    for ing in recipe['ingredient_details']:
                        label = '✅' if ing['status'] == '보유' else '🛒'
                        original = ing['original_name']
                        amount = ing['amount'] or '수량 정보 없음'
                        section = ing['section'] or '구분 없음'
                        st.write(f'{label} {original} — {amount} ({section})')

st.caption('현재 버전은 재료 이름의 일치 여부만 확인하며, 보유 수량과 대체 가능한 재료는 아직 반영하지 않아요.')
