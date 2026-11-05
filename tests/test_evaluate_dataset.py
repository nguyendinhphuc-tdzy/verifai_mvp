"""Dataset evaluation tool: manifest, resume and one-row-per-video export logic."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import evaluate_dataset as ev  # noqa: E402


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'x')


@pytest.fixture
def dataset(tmp_path):
    self_dir, public = tmp_path / 'VIDEO TỰ TẠO', tmp_path / 'VIDEO CÔNG KHAI'
    _touch(self_dir / 'GỐC' / 'VID_GOC01.mp4')
    _touch(self_dir / 'LỖI' / 'Sai giá' / 'VID_LOI01.mp4')
    _touch(self_dir / 'LỖI' / 'Claim ngoài danh sách được duyệt' / 'VID_LOI22 (1).mp4')
    _touch(self_dir / 'LỖI' / 'Không nhất quán hình ảnh' / 'VID_LOI30_1.mp4')
    _touch(public / 'PUB002.mov')
    _touch(public / 'PUB010.mp4')
    _touch(public / 'notes.txt')
    return self_dir, public


def test_video_codes_ignore_copy_suffixes():
    assert ev.video_code('VID_LOI22 (1).mp4') == 'VID_LOI22'
    assert ev.video_code('VID_LOI30_1.mp4') == 'VID_LOI30'
    assert ev.video_code('PUB002.mov') == 'PUB002'
    assert ev.video_code('random.mp4') is None


def test_manifest_groups_categories_and_sku_sources(dataset):
    self_dir, public = dataset
    items = ev.build_manifest(self_dir, public, {'VID_GOC01': 'SKU001', 'PUB002': 'SKU008'},
                              duration=lambda p: 8.0)
    by = {i['code']: i for i in items}
    assert [i['code'] for i in items] == ['VID_GOC01', 'VID_LOI01', 'VID_LOI22', 'VID_LOI30',
                                          'PUB002', 'PUB010']
    assert by['VID_GOC01']['group'] == 'original' and by['VID_GOC01']['sku_source'] == 'mapped'
    assert by['VID_LOI01']['category'] == 'Sai giá'
    assert (by['VID_LOI22']['sku'], by['VID_LOI22']['sku_source']) == ('SKU004', 'assumed_rotation')
    assert (by['PUB010']['sku'], by['PUB010']['sku_source']) == ('NOREF', 'no_product_truth')
    assert by['PUB002']['sku'] == 'SKU008' and by['PUB002']['group'] == 'public'


def test_duplicate_video_code_is_rejected(dataset):
    self_dir, public = dataset
    _touch(self_dir / 'LỖI' / 'Sai giá' / 'VID_LOI01 (1).mp4')
    with pytest.raises(SystemExit, match='VID_LOI01'):
        ev.build_manifest(self_dir, public, {}, duration=lambda p: 1.0)


def test_run_priority_self_created_first_public_short_first():
    items = [{'code': 'PUB001', 'group': 'public', 'duration': 54},
             {'code': 'PUB012', 'group': 'public', 'duration': 5},
             {'code': 'VID_LOI02', 'group': 'controlled_error', 'duration': 8},
             {'code': 'VID_GOC06', 'group': 'original', 'duration': 8}]
    assert [i['code'] for i in sorted(items, key=ev.run_priority)] == \
        ['VID_GOC06', 'VID_LOI02', 'PUB012', 'PUB001']


def _shard(work, name, rows):
    path = work / name
    path.mkdir(parents=True)
    conn = sqlite3.connect(path / 'verifai.sqlite3')
    conn.execute('CREATE TABLE jobs(filename TEXT, status TEXT, details TEXT)')
    conn.executemany('INSERT INTO jobs VALUES(?,?,?)',
                     [(f, s, json.dumps({'coverage': {'vlm': v}})) for f, s, v in rows])
    conn.commit()
    conn.close()


def test_resume_skips_completed_but_reruns_transient_gemini_failures(tmp_path):
    _shard(tmp_path, 'shard0', [('VID_GOC01.mp4', 'completed', 'ok'),
                                ('VID_GOC06.mp4', 'completed', 'error'),
                                ('PUB003.mp4', 'processing', 'ok')])
    _shard(tmp_path, 'shard1', [('PUB001.mp4', 'completed', 'ok')])
    assert ev.finished_codes(tmp_path) == {'VID_GOC01', 'PUB001'}
    assert ev.next_shard_index(tmp_path) == 2


def test_one_row_per_video_completed_and_newest_wins():
    rows = {}
    ev.choose_latest(rows, 'A', {'status': 'completed', 'created_at': '2026-11-02T01', 'v': 1})
    ev.choose_latest(rows, 'A', {'status': 'processing', 'created_at': '2026-11-02T05', 'v': 2})
    assert rows['A']['v'] == 1
    ev.choose_latest(rows, 'A', {'status': 'completed', 'created_at': '2026-11-02T03', 'v': 3})
    assert rows['A']['v'] == 3
