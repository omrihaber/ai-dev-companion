def test_review_request_accepts_files_and_marked_camelcase():
    from adc_api.schemas import ReviewRequest

    req = ReviewRequest.model_validate({
        "files": [{"path": "a.py", "content": "x=1\n"}],
        "marked": ["a.py"],
    })
    assert req.files[0].path == "a.py"
    assert req.marked == ["a.py"]


def test_review_request_legacy_code_still_valid():
    from adc_api.schemas import ReviewRequest

    req = ReviewRequest.model_validate({"language": "python", "code": "x=1\n"})
    assert req.code == "x=1\n" and req.files == []
