import backend


def test_one_missing_frame_on_mov_counts_as_complete():
    # PUB002.mov: container says 374 frames, decoder returns 373.
    assert backend.decoded_all_frames(373, 374)
    assert backend.decoded_all_frames(374, 374)
    assert backend.decoded_all_frames(10, 0)


def test_real_truncation_is_still_partial():
    assert not backend.decoded_all_frames(300, 374)
    assert not backend.decoded_all_frames(7, 10)
    # 1% of 1000 = 10 frames allowed; 11 missing is partial.
    assert backend.decoded_all_frames(990, 1000)
    assert not backend.decoded_all_frames(989, 1000)
