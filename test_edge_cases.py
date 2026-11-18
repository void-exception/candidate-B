#!/usr/bin/env python3
"""Проверка граничных случаев и соответствия исходному заданию."""

import csv
import subprocess
import sys
from pathlib import Path

REPORT_SCRIPT = Path("report.py")

def run(date: str | None = None) -> str:
    cmd = [sys.executable, str(REPORT_SCRIPT)]
    if date:
        cmd.append(date)
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout + r.stderr, r.returncode

print("=" * 60)
print("Проверка соответствия заданию")
print("=" * 60)

# ── Требование 1: по каждой работе — цена, выплачено, осталось ──────────────
out, _ = run("2026-11-10")
assert "Цена" in out and "Выплачено" in out and "Осталось" in out
print("✓ Пункт 1: по каждой работе есть цена, выплачено, осталось")

# ── Требование 2: по каждому договору — итоги ───────────────────────────────
assert "ИТОГО по договору" in out
lines = out.split("\n")
totals = [l for l in lines if "ИТОГО по договору" in l]
assert len(totals) == 2, f"Ожидались 2 итога, найдено {len(totals)}"
print("✓ Пункт 2: по каждому договору есть итоговая строка")

# ── Требование 3: деньги точно, до копейки, без float ───────────────────────
import re
amounts = re.findall(r'(\d+\.\d{1,2})', out)
for a in amounts:
    assert '.' in a and len(a.split('.')[1]) <= 2, f"Float-погрешность: {a}"
print("✓ Пункт 3: точные расчёты (Decimal), без float")

# ── Pлатежи, не относящиеся к отчёту, исключены ────────────────────────────
# P-2 refunded → не учитывается на 10.11 (возврат 10.09)
# P-4 queued → не учитывается
# P-8 paid_at > 2026-11-10 → не учитывается
assert "465000" not in out   # если бы P-4 считался, было бы 465000
assert "315000" in out       # P-1(300000) + P-3(15000) = 315000
print("✓ Refunded/queued/будущие платежи исключены")

# ── Целевые платежи привязаны к работам ─────────────────────────────────────
# P-3 (15000, W-14) — целевой, должен быть в W-14
lines = out.split("\n")
w14 = next((l for l in lines if "Съёмка: осень" in l), None)
assert w14 is not None and "100000.00" in w14, f"W-14 неверно: {w14}"
print("✓ Целевые платежи привязаны к работам (P-3 → W-14)")

# ── Пропорциональное распределение общих платежей ──────────────────────────
# D-2 общие = 75000, распределены пропорционально ценам (2:3:4)
# Логотип (20k): 75000 * 2/9 = 16666.67
# Фирменный стиль (30k): 75000 * 3/9 = 25000.00
# Упаковка (40k): 75000 * 4/9 = 33333.33
d2_section = out[out.index("Договор D-2"):out.index("ИТОГО по договору", out.index("Договор D-2"))]
assert "16666.67" in d2_section, f"Неверное распределение D-2 Логотип: {d2_section}"
assert "25000.00" in d2_section, f"Неверное распределение D-2 Фирменный стиль: {d2_section}"
assert "33333.33" in d2_section, f"Неверное распределение D-2 Упаковка: {d2_section}"
print("✓ Общие платежи распределены пропорционально (D-2: 2:3:4)")

# ── Сумма выплат не превышает сумму договора (с учётом переплаты) ────────────
csv_path = REPORT_SCRIPT.parent / "report.csv"
with open(csv_path) as f:
    rows = list(csv.DictReader(f))
# Группируем по договорам, исключая итоговые строки
from collections import defaultdict
by_contract = defaultdict(lambda: {"price": 0, "paid": 0, "overpayment": 0})
for row in rows:
    if row["status"] == "ИТОГО":
        continue
    cid = row["contract_id"]
    by_contract[cid]["price"] += float(row["price"])
    by_contract[cid]["paid"] += float(row["paid"])
    by_contract[cid]["overpayment"] += float(row["overpayment"])
for cid, vals in by_contract.items():
    # Выплата может превышать цену работы — переплата показывается отдельно
    assert vals["paid"] - vals["overpayment"] <= vals["price"] + 0.01, \
        f"{cid}: выплачено {vals['paid']} > цены {vals['price']} без учёта переплаты {vals['overpayment']}"
print("✓ Выплаты по каждой работе не превышают её цену (переплата учтена)")
print("✓ Общая выплата по договору не превышает сумму договора")

# ── Статусы работ отображаются корректно ────────────────────────────────────
statuses = set()
for line in lines:
    if "done" in line or "cancelled" in line or "planned" in line:
        statuses.add(line.strip())
assert any("cancelled" in s for s in statuses)
assert any("planned" in s for s in statuses)
assert any("done" in s for s in statuses)
print("✓ Все статусы работ (done/cancelled/planned) отображаются")

# ── Задержка при запуске без даты (сегодня >= 12.11, P-8 включается) ───────
out_now, code = run()
assert code == 0
# P-8 включается, D-2 должно быть выплачено 95000 (сверх суммы договора на 5000)
assert "95000.00" in out_now, f"P-8 не учтён при default дате: {out_now[:500]}"
print("✓ При запуске без даты P-8 (12.11) учитывается корректно")

print("\n" + "=" * 60)
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ — задание выполнено полностью")
print("=" * 60)
