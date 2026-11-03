from datetime import date

from emporio import config, tools


def test_now_sem_override_usa_data_real(monkeypatch):
    monkeypatch.delenv("EMPORIO_TODAY", raising=False)
    assert config.now().date() == config.today()


def test_now_com_override_tem_data_fixada_e_dia_da_semana_coerente(monkeypatch):
    monkeypatch.setenv("EMPORIO_TODAY", "2026-02-21")  # sábado
    n = config.now()
    assert n.date() == date(2026, 2, 21) and n.weekday() == 5
    assert n.tzinfo is not None
    assert tools.is_open(n)["dia"] == "sábado"
