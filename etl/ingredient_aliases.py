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
    '후추가루': ('후추','spelling'),
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
    '가츠오부시': ('가다랑어포', 'synonym'),
    '가쯔오부시': ('가다랑어포', 'synonym'),
    '계란노른자': ('달걀노른자', 'synonym'),
    '건로즈메리': ('건로즈마리', 'spelling'),
    '갈은돼지고기': ('돼지고기', 'preparation'),
}
