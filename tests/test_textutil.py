from tupase_mcp.textutil import fold


def test_fold_lowercases_and_strips_accents():
    assert fold("Cordón ÁÉ") == "cordon ae"
    assert fold("PÁDEL") == "padel"
    assert fold("") == ""
