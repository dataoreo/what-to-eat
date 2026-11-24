import argparse
import json     
import re
from collections import Counter, defaultdict
from pathlib import Path


# 식재료 표준화 사전 정의
# key: 원본 재료명에서 공백을 제거한 문자열
# value: (표준 재료명, 변환 이유)를 나타내는 튜플
# 변환 이유의 종류:
#   synonym     : 동의어(계란 → 달걀)
#   spelling    : 철자나 표기 교정(브로컬리 → 브로콜리)
#   preparation : 단순 손질 형태를 기본 식재료로 묶음(다진마늘 → 마늘)
#
# 아래에 없는 이름은 추측하여 변환하지 않음.
# 마늘가루·마늘기름 같은 가공품은 함부로 마늘로 합치지 않음.
# 주의: ALIASES는 한 번만 조회하므로 연쇄 규칙을 끝까지 따라가지는 않음.
# 예: 후추가루 → 후춧가루까지만 수행하며 자동으로 후추까지 가지 않음.
ALIASES = {
    '올리브오일': ('올리브유','synonym'),
    '브로컬리': ('브로콜리','spelling'),
    '컬리플라워': ('콜리플라워','spelling'),
    '래디쉬': ('레디쉬','spelling'),
    '로즈메리': ('로즈마리','spelling'),
    '쇠고기': ('소고기','synonym'),
    '계란': ('달걀','synonym'),
    '후추가루': ('후춧가루','spelling'),
    '후춧가루': ('후추','synonym'),
    '양송이': ('양송이버섯','synonym'),
    '새송이': ('새송이버섯','synonym'),
    '모차렐라치즈': ('모짜렐라치즈','spelling'),
    '셀러리': ('샐러리','spelling'),
    '가쓰오부시': ('가다랑어포','synonym'),
    '다진마늘': ('마늘','preparation'),
    '마늘다진것': ('마늘','preparation'),
    '통마늘': ('마늘','preparation'),
    '깐마늘': ('마늘','preparation'),
    '알마늘': ('마늘','preparation'),
    '편마늘': ('마늘','preparation'),
    '간마늘': ('마늘','preparation'),
    '납작썬마늘': ('마늘','preparation'),
    '다진양파': ('양파','preparation'),
    '양파다진것': ('양파','preparation'),
    '양파채썬것': ('양파','preparation'),
    '양파채친것': ('양파','preparation'),
    '양파작게자른것': ('양파','preparation'),
    '채썬양파': ('양파','preparation'),
    '간양파': ('양파','preparation'),
    '깐양파': ('양파','preparation'),
    '다진대파': ('대파','preparation'),
    '다진생강': ('생강','preparation'),
    '생강다진것': ('생강','preparation'),
    '다진소고기': ('소고기','preparation'),
    '다진쇠고기': ('소고기','preparation'),
    '쇠고기다진것': ('소고기','preparation'),
    '갈은소고기': ('소고기','preparation'),
    '소고기다짐육': ('소고기','preparation'),
    '소고기(다짐육)': ('소고기','preparation'),
    '다진돼지고기': ('돼지고기','preparation'),
    '다진파': ('파','preparation'),
    '파다진것': ('파','preparation'),
    '다진홍고추': ('홍고추','preparation'),
    '다진청양고추': ('청양고추','preparation'),
    '다진땅콩': ('땅콩','preparation'),
    '다진호두': ('호두','preparation'),
    '으깬두부': ('두부','preparation'),
    '삶은달걀': ('달걀','preparation'),
    '달걀삶은것': ('달걀','preparation'),
    '달걀물': ('달걀','preparation'),
}

# 검토 후보 추출 단계에서 'unchanged' 재료명을 검토 후보 파일에 넣는 용도로 사용함.
REVIEW_KEYWORDS = (
    '가루', '즙', '국물', '육수', '오일', '기름', '소스',
    '저염', '무염', '말린', '건', '다진', '채', '흰자', '노른자'
)


# 문자열 안의 공백을 전부 제거
def compact(value):
    return re.sub(r'\s+', '', value.strip())


# 재료명 하나를 표준 이름과 변환 유형으로 변환
def normalize(raw):
    # 사전 조회를 하기 전에 띄어쓰기부터 통일함.
    # 예) raw="다진 마늘", key="다진마늘"
    key = compact(raw)

    # 매핑 사전에 등록된 경우: 등록된 표준 이름과 변환 이유 반환
    if key in ALIASES:
        # 튜플 언패킹: ('마늘', 'preparation') → 두 변수에 나누어 담기
        canonical, reason = ALIASES[key]
        return canonical, reason

    # 별도 매핑 규칙은 없지만 공백 제거로 이름이 달라진 경우
    if key != raw:
        return key, 'spacing'

    # 변환 규칙도 없고 공백 차이도 없다면 원본 유지
    return key, 'unchanged'


def make_outputs(data, output_dir):
    rows = []
    normalized = []

    name_recipes = defaultdict(set)

    for recipe in data:  # 레시피 하나씩 탐색
        for ing in recipe.get('ingredients', []):
            # 비어 있거나 문자열이 아닌 이름은 집계에서 제외함.
            if isinstance(ing.get('original_name'), str) and ing['original_name'].strip():
                name_recipes[ing['original_name']].add(str(recipe['recipe_id']))

    # 고유 식재료명마다 표준화 함수(normalize)를 한 번씩 호출함.
    # dict comprehension: {원본 이름: (표준 이름, 변환 유형), ...} 구조
    mapping = {name: normalize(name) for name in name_recipes}

    # 원본명/표준명/변환유형/레시피 등장 횟수로 매핑 행을 구성함.
    for name in sorted(name_recipes):  # 결과를 일관된 순서로 저장하기 위한 정렬
        canonical, reason = mapping[name]
        rows.append({
            'original_name': name,
            'canonical_name': canonical,
            'mapping_type': reason,
            'recipe_count': len(name_recipes[name])  # 집합 길이 = 서로 다른 레시피 수
        })

    # 기존 레시피 데이터는 복사하고, 각 식재료에 표준 이름을 추가함.
    # 원본 이름/수량/섹션은 남겨 두어 화면 표시나 추후 검증에 사용할 수 있음.
    for recipe in data:
        r = dict(recipe)  # 레시피 딕셔너리를 얕게 복사
        r['ingredients'] = []  # 복사본의 재료 리스트를 새로 구성

        for ing in recipe.get('ingredients', []):
            new = dict(ing)  # 개별 재료 딕셔너리도 별도로 복사
            raw = ing.get('original_name')

            if isinstance(raw, str) and raw.strip():
                # 이미 계산한 결과를 재사용함. 재료마다 normalize를 재호출하지 않음.
                new['canonical_name'], new['mapping_type'] = mapping[raw]
            else:
                # 유효하지 않은 재료명은 임의로 바꾸지 않고 표시만 남김
                new['canonical_name'], new['mapping_type'] = None, 'invalid'

            r['ingredients'].append(new)

        normalized.append(r)

    # 검토 후보 파일에 넣을 식재료명을 찾습니다.
    candidates = []
    # 표준 이름 한 개에 연결되는 여러 원본 이름들을 모읍니다.
    # 예) '마늘' → ['마늘', '다진 마늘', '다진마늘']
    canon_to_orig = defaultdict(list)

    for row in rows:
        canon_to_orig[row['canonical_name']].append(row['original_name'])

        # 변환되지 않은 이름 중 가공·손질 관련 키워드가 하나라도 포함된 경우만 기록
        if row['mapping_type'] == 'unchanged' and any(
            k in row['original_name'] for k in REVIEW_KEYWORDS
        ):
            candidates.append({
                'original_name': row['original_name'],
                'recipe_count': row['recipe_count'],
                'note': '가공품/손질/수식어 여부 검토 (자동 병합하지 않음)'
            })

    output_dir.mkdir(parents=True, exist_ok=True)

    def write(name, content):
        with (output_dir / name).open('w', encoding='utf-8') as f:
            # ensure_ascii=False: 한글을 \uXXXX로 바꾸지 않고 그대로 저장
            # indent=2: 2칸 들여쓰기로 읽기 쉽게 저장
            json.dump(content, f, ensure_ascii=False, indent=2)

    # 원본명↔표준명 매핑 사전
    write('ingredient_mapping.json', rows)
    # 전체 레시피에 canonical_name/mapping_type이 추가된 JSON
    write('ingredients_normalized.json', normalized)
    # 검토 후보는 자주 등장하는 재료부터 볼 수 있도록 내림차순 정렬
    write('ingredient_review_candidates.json', sorted(candidates, key=lambda x: -x['recipe_count']))

    # 변환 유형별 고유 식재료명 개수를 세어 실행 결과로 출력함.
    counts = Counter(row['mapping_type'] for row in rows)
    print(f'Recipes: {len(data)}; distinct original names: {len(rows)}; distinct normalized names: {len(canon_to_orig)}')
    print('Mapping counts:', dict(counts))
    print('Review candidates:', len(candidates))
    print('Preserved original_name, amount, section and full original_text')


if __name__ == '__main__':
    # argparse를 이용하면 실행할 때 입력 파일 및 저장 폴더를 바꿀 수 있음.
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, default=Path('data/processed/ingredients_extracted.json'))
    parser.add_argument('--output-dir', type=Path, default=Path('data/processed'))
    args = parser.parse_args()

    with args.input.open(encoding='utf-8') as f:
        data = json.load(f)

    make_outputs(data, args.output_dir)