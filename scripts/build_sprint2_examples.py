"""Convert Sprint-2 Sheet 2 into an auditable scenario-example library.

Use this as rule development/in-context example material, NOT as training
labels or evaluated Gemini accuracy. It never changes model weights.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import re
from verifai_core.dataset import _sheet_rows,_rows_named,_as_text,_val,MAX_XLSX_BYTES

CATEGORY_TO_TARGET={
    'Sai giá':['PRICE-01'],
    'Sai tên / thông tin sản phẩm':['SKU-01','VARIANT-01'],
    'Claim ngoài danh sách được duyệt':['CLAIM-01','CLAIM-02'],
    'Lỗi chữ / phụ đề':['TEXT-01','VIS-03'],
    'Không nhất quán hình ảnh':['VIS-01','VIS-02','VIS-SCREEN'],
    'Thiếu nhãn AI':['MANUAL_LABEL_VERIFICATION'],
}

def compile_examples(content:bytes) -> dict:
    if len(content)>MAX_XLSX_BYTES:
        raise ValueError('Workbook exceeds the 8MB parser limit')
    rows=_rows_named(_sheet_rows(content),'2. Kich ban loi')
    examples=[]
    for row in rows:
        code=_as_text(_val(row,0)).upper()
        if not re.fullmatch(r'VID_LOI\d{2}',code):
            continue
        category=_as_text(_val(row,2))
        if category not in CATEGORY_TO_TARGET:
            raise ValueError('Unrecognized error category in '+code+': '+category)
        example={
            'case_code':code, 'source_group':_as_text(_val(row,1)),
            'scenario_category':category,
            'target_candidate_rules':CATEGORY_TO_TARGET[category],
            'planned_edit_description':_as_text(_val(row,3)),
            'expected_reference':_as_text(_val(row,4)),
            'expected_modified_content':_as_text(_val(row,5)),
            'planned_location':_as_text(_val(row,6)),
            'video_review_status':_as_text(_val(row,10)),
            'video_review_notes':_as_text(_val(row,11)),
            'label_status':'scenario_only_unadjudicated',
        }
        examples.append(example)
    if len(examples)!=44 or len({x['case_code'] for x in examples})!=44:
        raise ValueError('Expected 44 unique controlled-error scenarios')
    return {
        'schema':'verifai-scenario-examples-v1',
        'source':'Sprint-2 Sheet 2: 44 described video manipulations',
        'trained_model_weights':False,
        'intended_use':'rule engineering, in-context instruction and future split-safe evaluation',
        'not_for':'ground truth replacement, unsupervised model performance claims',
        'group_split_required':True,
        'counts':dict(Counter(x['scenario_category'] for x in examples)),
        'examples':examples,
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--xlsx',type=Path,required=True)
    ap.add_argument('--out',type=Path,default=Path('reports/sprint2_scenario_examples.json'))
    a=ap.parse_args()
    result=compile_examples(a.xlsx.read_bytes())
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'examples':len(result['examples']),'counts':result['counts'],
                      'model_weights_trained':False,'output':str(a.out)},ensure_ascii=False))

if __name__=='__main__':
    main()
