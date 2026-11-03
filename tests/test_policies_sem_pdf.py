import pytest

from emporio import policies


def test_mensagem_clara_quando_o_pdf_nao_existe(tmp_path):
    """Roda sempre, inclusive em clones sem o PDF (que não é versionado)."""
    with pytest.raises(FileNotFoundError, match="políticas_da_loja.pdf"):
        policies.find_pdf(tmp_path)
    assert policies.pdf_available(tmp_path) is False
