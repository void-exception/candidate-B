#!/usr/bin/env python3
"""
Отчёт по договорам: выплаты по работам и итог по договору.

Использование:
    python report.py [дата_отчёта]

Дата в формате ГГГГ-ММ-ДД (по умолчанию сегодня).
Результат выводится в консоль и сохраняется в report.csv.
"""

import csv
import sys
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
REPORT_DATE_FMT = "%Y-%m-%d"


def load_csv(filename: str) -> list[dict]:
    with open(DATA_DIR / filename, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_money(value: str) -> Decimal:
    return Decimal(value.strip())


def parse_date(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    return datetime.strptime(value.strip(), REPORT_DATE_FMT)


def get_status_on_date(work_row: dict, report_date: datetime) -> str:
    """Определяет статус работы на указанную дату."""
    cancelled_at = parse_date(work_row["cancelled_at"])
    if cancelled_at is not None and cancelled_at <= report_date:
        return "cancelled"
    completed_at = parse_date(work_row["completed_at"])
    if completed_at is not None and completed_at <= report_date:
        return "done"
    return "planned"


def is_payment_valid(p: dict, report_date: datetime) -> bool:
    """Определяет,应考虑 ли платёж на дату отчёта."""
    status = p["status"].strip()
    paid_at = parse_date(p["paid_at"])

    if status == "queued":
        return False

    if paid_at is None or paid_at > report_date:
        return False

    if status == "paid":
        return True

    if status == "refunded":
        # Если возврат ещё не произошёл на момент отчёта — считаем выплаченным
        refunded_at = parse_date(p["refunded_at"])
        if refunded_at is None or refunded_at > report_date:
            return True
        return False

    return False


def distribute_proportionally(
    amounts: list[Decimal], total: Decimal
) -> list[Decimal]:
    """
    Распределяет total пропорционально elements в amounts.
    Округление до копеек, последнему элементу — остаток.
    Возвращает список распределённых сумм.
    """
    if total == 0 or not amounts:
        return [Decimal("0")] * len(amounts)

    total_price = sum(amounts)
    if total_price == 0:
        return [Decimal("0")] * len(amounts)

    result = []
    distributed = Decimal("0")
    for i, price in enumerate(amounts):
        if i == len(amounts) - 1:
            share = total - distributed
        else:
            share = (total * price / total_price).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        result.append(share)
        distributed += share
    return result


def main():
    # Дата отчёта
    if len(sys.argv) > 1:
        try:
            report_date = datetime.strptime(sys.argv[1], REPORT_DATE_FMT)
        except ValueError:
            print(f"Ошибка: неверный формат даты. Используйте ГГГГ-ММ-ДД.", file=sys.stderr)
            sys.exit(1)
    else:
        report_date = datetime.now()

    # Загрузка данных
    contracts = {row["contract_id"]: row for row in load_csv("contracts.csv")}
    works = {}
    for row in load_csv("works.csv"):
        works[row["work_id"]] = row

    raw_payments = load_csv("payments.csv")

    # Классификация платежей
    target_payments: dict[str, list[dict]] = {}   # work_id -> список платежей
    general_payments: list[dict] = []  # платежи без привязки к работе

    for p in raw_payments:
        if not is_payment_valid(p, report_date):
            continue
        amount = parse_money(p["amount"])
        work_id = p["work_id"].strip() if p["work_id"] else None
        payment_info = {
            "payment_id": p["payment_id"],
            "amount": amount,
            "purpose": p["purpose"],
            "paid_at": parse_date(p["paid_at"]),
        }
        if work_id and work_id in works:
            target_payments.setdefault(work_id, []).append(payment_info)
        else:
            general_payments.append({
                **payment_info,
                "contract_id": p["contract_id"],
            })

    # Группируем общие платежи по договорам
    general_by_contract: dict[str, list[dict]] = {}
    for gp in general_payments:
        general_by_contract.setdefault(gp["contract_id"], []).append(gp)

    # Определяем статус каждой работы на дату отчёта
    for wid, w in works.items():
        w["_status"] = get_status_on_date(w, report_date)

    # Рассчитываем выплаты по каждой работе
    work_results = []

    for wid, w in works.items():
        price = parse_money(w["price"])
        status = w["_status"]
        contract_id = w["contract_id"]

        # Целевые платежи (привязаны к работе)
        targeted_paid = sum(tp["amount"] for tp in target_payments.get(wid, []))

        # Для отменённых работ целевые платежи не гасят стоимость, но остаются
        # и показываются отдельно
        work_results.append({
            "work_id": wid,
            "contract_id": contract_id,
            "title": w["title"],
            "price": price,
            "status": status,
            "targeted_paid": targeted_paid,
            "general_paid": Decimal("0"),
            "overpayment": Decimal("0"),
            "cancelled_at": parse_date(w["cancelled_at"]),
        })

    # Распределяем общие платежи между неотменёнными работами каждого договора
    for contract_id, gps in general_by_contract.items():
        total_general = sum(g["amount"] for g in gps)
        if total_general == 0:
            continue

        # Находим неотменённые работы этого договора
        active_works = [wr for wr in work_results
                        if wr["contract_id"] == contract_id and wr["status"] != "cancelled"]
        if not active_works:
            continue

        prices = [wr["price"] for wr in active_works]
        shares = distribute_proportionally(prices, total_general)

        for wr, share in zip(active_works, shares):
            wr["general_paid"] += share
            # Проверяем переплату
            total_paid = wr["targeted_paid"] + wr["general_paid"]
            if total_paid > wr["price"]:
                wr["overpayment"] = total_paid - wr["price"]
                # Уменьшаем general_paid чтобы общая выплата не превышала цену
                # НО правило 10 говорит НЕ СКРЫВАТЬ переплаты — показывать отдельно
                # Переплата остаётся как отдельная величина, general_paid не ограничиваем
                pass

    # Строим итоги по договорам
    contract_results = []
    for cid, c in contracts.items():
        contract_amount = parse_money(c["amount"])
        wrs = [wr for wr in work_results if wr["contract_id"] == cid]

        total_price = sum(wr["price"] for wr in wrs)
        total_targeted = sum(wr["targeted_paid"] for wr in wrs)
        total_general_dist = sum(wr["general_paid"] for wr in wrs)
        total_overpayment = sum(wr["overpayment"] for wr in wrs)
        total_paid = total_targeted + total_general_dist
        cancelled_price = sum(wr["price"] for wr in wrs if wr["status"] == "cancelled")

        # Остаток по действующим работам
        active_wrs = [wr for wr in wrs if wr["status"] != "cancelled"]
        active_price = sum(wr["price"] for wr in active_wrs)
        active_paid = sum(
            wr["targeted_paid"] + min(wr["general_paid"], wr["price"] - wr["targeted_paid"])
            for wr in active_wrs
        )
        remaining_active = active_price - active_paid

        contract_results.append({
            "contract_id": cid,
            "contractor": c["contractor"],
            "amount": contract_amount,
            "total_works_price": total_price,
            "total_paid": total_paid,
            "total_remaining": total_price - total_paid,
            "cancelled_works_price": cancelled_price,
            "active_works_price": active_price,
            "active_remaining": remaining_active,
            "overpayment": total_overpayment,
            "works": wrs,
        })

    # Вывод в консоль
    print(f"\nОтчёт на дату: {report_date.strftime(REPORT_DATE_FMT)}\n")

    for cr in contract_results:
        print(f"{'='*60}")
        print(f"Договор {cr['contract_id']} | Подрядчик: {cr['contractor']}")
        print(f"Сумма договора: {cr['amount']} руб.")
        print(f"{'-'*60}")
        print(f"{'Работа':<35} {'Цена':>10} {'Выплачено':>10} {'Осталось':>10} {'Переплата':>10} {'Статус':>10}")
        print(f"{'-'*60}")
        for wr in cr["works"]:
            total_p = wr["targeted_paid"] + wr["general_paid"]
            if wr["status"] == "cancelled":
                remaining = Decimal("0")
                overpay = max(Decimal("0"), total_p - wr["price"])
            else:
                remaining = max(Decimal("0"), wr["price"] - total_p)
                overpay = wr["overpayment"]
            print(f"{wr['title'][:34]:<35} {wr['price']:>10} {total_p:>10} {remaining:>10} {overpay:>10} {wr['status']:>10}")
        print(f"{'-'*60}")
        print(f"{'ИТОГО по договору (номинально)':<35} {cr['total_works_price']:>10} {cr['total_paid']:>10} {cr['total_remaining']:>10} {'—':>10}")
        if cr["cancelled_works_price"] > 0:
            print(f"{'  Отменённые работы (к уточнению)':<35} {cr['cancelled_works_price']:>10} {'0':>10} {cr['cancelled_works_price']:>10} {'—':>10}")
        print(f"{'  Действующие работы':<35} {cr['active_works_price']:>10} {cr['total_paid']:>10} {cr['active_remaining']:>10} {'—':>10}")
        if cr["overpayment"] > 0:
            print(f"{'  Переплата':<35} {'—':>10} {'—':>10} {'—':>10} {cr['overpayment']:>10}")
        print()

    # Сохранение в CSV
    output_path = Path(__file__).parent / "report.csv"
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "contract_id", "contractor", "contract_amount",
            "work_id", "title", "price", "paid", "remaining", "overpayment", "status"
        ])
        for cr in contract_results:
            for wr in cr["works"]:
                total_p = wr["targeted_paid"] + wr["general_paid"]
                if wr["status"] == "cancelled":
                    remaining = Decimal("0")
                    overpay = max(Decimal("0"), total_p - wr["price"])
                else:
                    remaining = max(Decimal("0"), wr["price"] - total_p)
                    overpay = wr["overpayment"]
                writer.writerow([
                    cr["contract_id"], cr["contractor"], cr["amount"],
                    wr["work_id"], wr["title"], wr["price"], total_p, remaining, overpay, wr["status"]
                ])
            writer.writerow([
                cr["contract_id"], cr["contractor"], cr["amount"],
                "", "", cr["total_works_price"], cr["total_paid"], cr["total_remaining"], "—", "ИТОГО"
            ])
    print(f"Отчёт сохранён в {output_path}")


if __name__ == "__main__":
    main()
