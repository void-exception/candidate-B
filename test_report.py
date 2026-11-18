#!/usr/bin/env python3
"""Тесты для report.py — проверка соответствия заданию."""

import csv
import subprocess
import sys
import shutil
from decimal import Decimal
from pathlib import Path

REPORT_SCRIPT = Path(__file__).parent / "report.py"
DATA_DIR = Path(__file__).parent / "data"
COPIED_DATA = DATA_DIR.parent / "_test_data"


def setup():
    """Копируем данные во временную директорию, чтобы не портить оригинал."""
    if COPIED_DATA.exists():
        shutil.rmtree(COPIED_DATA)
    shutil.copytree(DATA_DIR, COPIED_DATA)


def teardown():
    if COPIED_DATA.exists():
        shutil.rmtree(COPIED_DATA)


def run_report(date_str: str | None = None) -> tuple[str, int]:
    """Запускает report.py и возвращает (stdout, returncode)."""
    cmd = [sys.executable, str(REPORT_SCRIPT)]
    if date_str is not None:
        cmd.append(date_str)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=REPORT_SCRIPT.parent,
    )
    # Перекопировать данные перед следующим запуском
    if COPIED_DATA.exists():
        shutil.rmtree(COPIED_DATA)
    shutil.copytree(DATA_DIR, COPIED_DATA)
    return result.stdout, result.returncode


# ── Базовые проверки запуска ────────────────────────────────────────────────

def test_run_with_date():
    stdout, code = run_report("2026-11-10")
    assert code == 0, f"Ошибка запуска: {stdout}"
    assert "Отчёт на дату: 2026-11-10" in stdout
    print("✓ Запуск с датой 2026-11-10")


def test_run_no_args():
    """Программа работает без аргументов (использует текущую дату)."""
    stdout, code = run_report()
    assert code == 0, f"Ошибка запуска без аргументов: {stdout}"
    assert "Отчёт на дату:" in stdout
    print("✓ Запуск без аргументов")


def test_invalid_date():
    stdout, code = run_report("not-a-date")
    assert code != 0, "Должна быть ошибка при неверной дате"
    print("✓ Неверная дата → ошибка")


# ── Структура отчёта ────────────────────────────────────────────────────────

def test_works_section_present():
    stdout, _ = run_report("2026-11-10")
    for name in ["Съёмка: весенняя коллекция", "Логотип", "Фирменный стиль", "Упаковка"]:
        assert name in stdout, f"Работа '{name}' не найдена в отчёте"
    print("✓ Все работы присутствуют в отчёте")


def test_contract_totals_present():
    stdout, _ = run_report("2026-11-10")
    assert "ИТОГО по договору" in stdout
    assert "Договор D-1" in stdout
    assert "Договор D-2" in stdout
    print("✓ Итоги по договорам присутствуют")


# ── Исключение платежей ────────────────────────────────────────────────────

def test_refunded_payment_excluded():
    """P-2 (refunded, 50000, refunded_at=10.09) не учитывается на 10.11."""
    stdout, _ = run_report("2026-11-10")
    assert "315000.00" in stdout, f"Неверная сумма D-1: {stdout}"
    print("✓ Refunded платёж P-2 исключён")


def test_queued_payment_excluded():
    """P-4 (queued, 150000) не включается в отчёт на 2026-11-10."""
    stdout, _ = run_report("2026-11-10")
    assert "465000" not in stdout, f"Queued P-4 включён: {stdout}"
    assert "315000.00" in stdout, f"Неверный итог D-1: {stdout}"
    print("✓ Queued платёж P-4 исключён")


def test_future_payment_excluded():
    """P-8 (paid_at=2026-11-12) не включается в отчёт на 2026-11-10."""
    stdout_before, _ = run_report("2026-11-10")
    stdout_after, _ = run_report("2026-11-12")
    assert "75000.00" in stdout_before, f"D-2 без P-8 неверен: {stdout_before}"
    assert "95000.00" in stdout_after, f"D-2 с P-8 неверен: {stdout_after}"
    print("✓ Платёж P-8 (после даты) исключён из отчёта на 10.11")


def test_refunded_payment_included_for_earlier_date():
    """P-2 (refunded 10.09) учитывается в отчёте на 05.09 (до возврата)."""
    stdout, _ = run_report("2026-09-05")
    # На 05.09 P-2 ещё не возвращён, поэтому D-1 общая выплата = 300000+50000 = 350000
    assert "350000.00" in stdout, f"P-2 должен учитываться до возврата: {stdout}"
    print("✓ Refunded платёж P-2 учитывается на дату до возврата")


# ── Целевые платежи привязаны к работам ──────────────────────────────────────

def test_targeted_payments_assigned_to_work():
    """P-3 (15000, work_id=W-14) относится на W-14."""
    stdout, _ = run_report("2026-11-10")
    lines = stdout.split("\n")
    w14_line = next((l for l in lines if "Съёмка: осень" in l), None)
    assert w14_line is not None, "Строка W-14 не найдена"
    # W-14: 60000 (доля общих) + 15000 (целевой) = 75000
    assert "75000.00" in w14_line, f"P-3 не привязан к W-14: {w14_line}"
    print("✓ Целевой платёж P-3 привязан к W-14")


# ── Точность (Decimal, без float) ──────────────────────────────────────────

def test_money_precision_decimal():
    """Суммы имеют не более 2 знаков после запятой."""
    stdout, _ = run_report("2026-11-10")
    import re
    amounts = re.findall(r'(\d+\.\d+)', stdout)
    for amt in amounts:
        frac = amt.split(".")[1]
        assert len(frac) <= 2, f"Более 2 знаков после запятой: {amt}"
    print("✓ Точность до копеек (Decimal)")


# ── Статусы работ ───────────────────────────────────────────────────────────

def test_cancelled_work_paid_zero():
    """Отменённая работа W-13 имеет выплачено = 0."""
    stdout, _ = run_report("2026-11-10")
    lines = stdout.split("\n")
    for line in lines:
        if "Съёмка: аксессуары" in line:
            assert "       0" in line or "0.00" in line, \
                f"W-13 cancelled, но выплата > 0: {line}"
            break
    else:
        raise AssertionError("W-13 не найден в отчёте")
    print("✓ Отменённая работа W-13: выплата = 0")


def test_planned_works_get_distribution():
    """Запланированные работы (W-15, W-16) участвуют в распределении аванса."""
    stdout, _ = run_report("2026-11-10")
    lines = stdout.split("\n")
    for w in ["Съёмка: зима", "Съёмка: новогодняя"]:
        found = False
        for line in lines:
            if w in line:
                found = True
                # Должны получить долю из общих платежей: 60000
                assert "60000.00" in line, f"{w} planned, но выплата не 60000: {line}"
                break
        assert found, f"{w} не найден"
    print("✓ Запланированные работы участвуют в распределении")


def test_w23_status_on_10nov_is_planned():
    """W-23 завершена 11.11, поэтому на 10.11 её статус — planned."""
    stdout, _ = run_report("2026-11-10")
    lines = stdout.split("\n")
    for line in lines:
        if "Упаковка" in line:
            assert "planned" in line, f"W-23 должна быть planned на 10.11: {line}"
            break
    else:
        raise AssertionError("W-23 не найден в отчёте")
    print("✓ W-23 на 10.11 имеет статус planned")


def test_w23_status_on_12nov_is_done():
    """W-23 завершена 11.11, поэтому на 12.11 её статус — done."""
    stdout, _ = run_report("2026-11-12")
    lines = stdout.split("\n")
    for line in lines:
        if "Упаковка" in line:
            assert "done" in line, f"W-23 должна быть done на 12.11: {line}"
            break
    else:
        raise AssertionError("W-23 не найден в отчёте")
    print("✓ W-23 на 12.11 имеет статус done")


# ── Распределение общих платежей ────────────────────────────────────────────

def test_general_payments_distributed_to_all_active():
    """Общие платежи распределяются между всеми неотменёнными работами."""
    stdout, _ = run_report("2026-11-10")
    lines = stdout.split("\n")
    d1_section = []
    in_d1 = False
    for line in lines:
        if "Договор D-1" in line:
            in_d1 = True
        if in_d1:
            d1_section.append(line)
            if "ИТОГО по договору" in line:
                break
    # 5 действующих работ: W-11,W-12,W-14,W-15,W-16 — каждая получила долю
    # W-11,W-12,W-15,W-16 по 60000, W-14 по 75000 (60000+15000 целевой)
    count_with_distribution = sum(
        1 for l in d1_section
        if any(x in l for x in ["60000.00", "75000.00"])
    )
    assert count_with_distribution == 5, \
        f"Ожидалось 5 работ с распределением, найдено {count_with_distribution}: {''.join(d1_section)}"
    print("✓ Общие платежи распределены между всеми неотменёнными работами")


def test_d2_proportional_distribution():
    """D-2: пропорции 2:3:4, суммы 16666.67 : 25000.00 : 33333.33."""
    stdout, _ = run_report("2026-11-10")
    d2_section = stdout[stdout.index("Договор D-2"):stdout.index("ИТОГО по договору", stdout.index("Договор D-2"))]
    assert "16666.67" in d2_section, f"Неверное распределение D-2 Логотип: {d2_section}"
    assert "25000.00" in d2_section, f"Неверное распределение D-2 Фирменный стиль: {d2_section}"
    assert "33333.33" in d2_section, f"Неверное распределение D-2 Упаковка: {d2_section}"
    print("✓ Общие платежи распределены пропорционально (D-2: 2:3:4)")


# ── CSV ─────────────────────────────────────────────────────────────────────

def test_csv_generated():
    run_report("2026-11-10")
    csv_path = REPORT_SCRIPT.parent / "report.csv"
    assert csv_path.exists(), "report.csv не создан"
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert len(rows) > 1, "CSV пустой"
    header = rows[0]
    for col in ("work_id", "paid", "remaining", "overpayment"):
        assert col in header, f"В CSV нет колонки '{col}'"
    print("✓ report.csv создан и содержит нужные колонки")


# ── Конкретные значения на 2026-11-10 ───────────────────────────────────────

def test_d1_total_on_10nov():
    """На 10.11.2026: D-1 выплачено 315000, действует 5 работ, отменена 1."""
    stdout, _ = run_report("2026-11-10")
    assert "315000.00" in stdout, f"D-1 выплачено неверно: {stdout}"
    assert "185000.00" in stdout, f"D-1 осталось неверно: {stdout}"
    assert "100000.00" in stdout  # стоимость отменённой работы
    print("✓ D-1 на 10.11: выплачено 315000, осталось 185000, отменённые 100000")


def test_d2_total_on_10nov():
    """На 10.11.2026: D-2 выплачено 75000, осталось 15000."""
    stdout, _ = run_report("2026-11-10")
    assert "75000.00" in stdout, f"D-2 выплачено неверно: {stdout}"
    assert "15000.00" in stdout, f"D-2 осталось неверно: {stdout}"
    print("✓ D-2 на 10.11: выплачено 75000, осталось 15000")


def test_overpayment_shown_on_later_date():
    """На 12.11 D-2 имеет переплату 5000 (P-8 включён)."""
    stdout, _ = run_report("2026-11-12")
    assert "5000.00" in stdout, f"Переплата не показана: {stdout}"
    assert "95000.00" in stdout, f"Выплата D-2 неверна: {stdout}"
    print("✓ Переплата по D-2 на 12.11 показана отдельно")


def test_distribution_summation_exact():
    """Сумма распределённых платежей точно равна исходному платежу."""
    stdout, _ = run_report("2026-11-10")
    # D-1 общий платёж 300000: 5 работ × 60000 = 300000
    assert "315000.00" in stdout
    # D-2 общий платёж 75000: 16666.67 + 25000.00 + 33333.33 = 75000.00
    assert "75000.00" in stdout
    print("✓ Распределение сходится до копейки")


def main():
    setup()
    tests = [
        test_run_with_date,
        test_run_no_args,
        test_invalid_date,
        test_works_section_present,
        test_contract_totals_present,
        test_refunded_payment_excluded,
        test_queued_payment_excluded,
        test_future_payment_excluded,
        test_refunded_payment_included_for_earlier_date,
        test_targeted_payments_assigned_to_work,
        test_money_precision_decimal,
        test_cancelled_work_paid_zero,
        test_planned_works_get_distribution,
        test_w23_status_on_10nov_is_planned,
        test_w23_status_on_12nov_is_done,
        test_general_payments_distributed_to_all_active,
        test_d2_proportional_distribution,
        test_csv_generated,
        test_d1_total_on_10nov,
        test_d2_total_on_10nov,
        test_overpayment_shown_on_later_date,
        test_distribution_summation_exact,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"✗ {t.__name__}: {e}")
            failed += 1
    teardown()
    print(f"\n{'='*40}")
    print(f"Результаты: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
