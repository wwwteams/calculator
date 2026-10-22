#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Coin Change — расчёт сдачи минимальным количеством монет (жадный алгоритм).

Ввод и вывод через консоль и файлы, резервное копирование и восстановление
кассовых настроек (номиналов монет) с контрольной суммой SHA-256.
Только стандартная библиотека Python 3.8+.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = BASE_DIR / "config" / "settings.json"
BACKUP_DIR = BASE_DIR / "backups"
DEFAULT_INPUT = BASE_DIR / "examples" / "input.txt"
DEFAULT_OUTPUT = BASE_DIR / "output.txt"
DEFAULT_COINS = [10, 5, 2, 1]
MAX_BACKUPS = 10
PRE_RESTORE = "pre-restore"
MANUAL = "manual"


class AppError(Exception):
    """Ожидаемая ошибка данных, файла или резервной копии."""


# ---------------------------------------------------------------- данные

def parse_int(text, name):
    """Преобразует текст в целое число или сообщает понятную ошибку."""
    s = str(text).strip()
    if not s or "_" in s:
        raise AppError("%s не является целым числом: «%s»" % (name, s))
    try:
        return int(s)
    except ValueError:
        raise AppError("%s не является целым числом: «%s»" % (name, s)) from None


def normalize_coins(values):
    """Проверяет номиналы; возвращает уникальные значения по убыванию."""
    if not values:
        raise AppError("Список номиналов пуст")
    result = set()
    for v in values:
        if isinstance(v, bool) or not isinstance(v, int):
            raise AppError("Номинал должен быть целым числом: %r" % (v,))
        if v <= 0:
            raise AppError("Номинал должен быть положительным: %d" % v)
        result.add(v)
    return sorted(result, reverse=True)


def compute_change(amount, coins):
    """Жадный алгоритм: список пар (номинал, количество)."""
    if amount < 0:
        raise AppError("Сумма сдачи не может быть отрицательной")
    rest = amount
    result = []
    for coin in coins:
        count, rest = divmod(rest, coin)
        if count:
            result.append((coin, count))
    if rest:
        raise AppError("Невозможно выдать сумму %d имеющимися номиналами "
                       "(остаток %d)" % (amount, rest))
    return result


def format_change(amount, result):
    if not result:
        return "Сдача %d: монеты не нужны (всего 0)" % amount
    parts = ", ".join("%d x %d" % (c, n) for c, n in result)
    return "Сдача %d: %s (всего %d)" % (amount, parts, sum(n for _, n in result))


def calc_pair(paid_text, price_text):
    """Оплачено и цена -> (оплачено, цена, сдача)."""
    paid = parse_int(paid_text, "Оплачено")
    price = parse_int(price_text, "Цена")
    if paid < 0 or price < 0:
        raise AppError("Оплачено и цена не могут быть отрицательными")
    if paid < price:
        raise AppError("Оплачено меньше цены: не хватает %d" % (price - paid))
    return paid, price, paid - price


def describe_line(text, coins):
    """Одна строка входного файла: «сумма» или «оплачено цена»."""
    parts = text.split()
    if len(parts) == 1:
        amount = parse_int(parts[0], "Сумма")
        return format_change(amount, compute_change(amount, coins))
    if len(parts) == 2:
        paid, price, amount = calc_pair(parts[0], parts[1])
        return "Оплачено %d, цена %d. %s" % (
            paid, price, format_change(amount, compute_change(amount, coins)))
    raise AppError("ожидается одно число (сумма) или два (оплачено цена)")


# ---------------------------------------------------------------- файлы

def read_text(path):
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        raise AppError("Файл не найден: %s" % path) from None
    except OSError as exc:
        raise AppError("Не удалось прочитать файл %s: %s" % (path, exc.strerror or exc)) from None
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise AppError("Файл %s не в кодировке UTF-8" % path) from None


def write_atomic(path, text):
    """Запись через временный файл: при сбое прежний файл не меняется."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(str(tmp), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp), str(path))
    except OSError as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise AppError("Не удалось записать файл %s: %s" % (path, exc.strerror or exc)) from None


# ---------------------------------------------------------------- настройки

def load_settings(strict=False):
    """Номиналы из config/settings.json. Нет файла: умолчание (или ошибка при strict)."""
    if not SETTINGS_PATH.exists():
        if strict:
            raise AppError("Файл настроек не найден: %s" % SETTINGS_PATH)
        return list(DEFAULT_COINS)
    text = read_text(SETTINGS_PATH)
    try:
        doc = json.loads(text)
    except ValueError:
        raise AppError("Файл настроек повреждён: это не JSON") from None
    if not isinstance(doc, dict) or "coins" not in doc or not isinstance(doc["coins"], list):
        raise AppError("Файл настроек повреждён: нет списка coins")
    return normalize_coins(doc["coins"])


def save_settings(coins):
    coins = normalize_coins(coins)
    write_atomic(SETTINGS_PATH, json.dumps({"coins": coins}, ensure_ascii=False, indent=2) + "\n")
    return coins


# ---------------------------------------------------------------- копии

def checksum_of(data):
    canon = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def rotate(protect=None):
    """Оставляет не более MAX_BACKUPS новых копий; protect не удаляется."""
    files = sorted(BACKUP_DIR.glob("*.json"))
    for path in files:
        if len(files) <= MAX_BACKUPS:
            break
        if protect is not None and path.name == Path(protect).name:
            continue
        try:
            path.unlink()
            files.remove(path)
        except OSError:
            pass


def make_backup(kind=MANUAL, coins=None, protect=None):
    if coins is None:
        coins = load_settings(strict=True)
    data = {"coins": normalize_coins(coins)}
    now = datetime.now()
    doc = {"created": now.isoformat(timespec="seconds"),
           "checksum": checksum_of(data), "data": data}
    path = BACKUP_DIR / ("%s_%s.json" % (now.strftime("%Y%m%d_%H%M%S_%f"), kind))
    write_atomic(path, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    rotate(protect=protect)
    return path


def load_backup(path):
    """Читает копию, проверяет SHA-256 и структуру; возвращает номиналы."""
    text = read_text(path)
    try:
        doc = json.loads(text)
    except ValueError:
        raise AppError("Файл копии повреждён: это не JSON") from None
    if (not isinstance(doc, dict) or not isinstance(doc.get("data"), dict)
            or not isinstance(doc.get("checksum"), str)
            or not isinstance(doc["data"].get("coins"), list)):
        raise AppError("Неверная структура копии")
    if checksum_of(doc["data"]) != doc["checksum"]:
        raise AppError("Контрольная сумма SHA-256 не совпала: копия повреждена")
    return normalize_coins(doc["data"]["coins"])


def find_backup(name=None):
    if name:
        path = BACKUP_DIR / Path(name).name
        if not path.is_file():
            raise AppError("Резервная копия не найдена: %s" % name)
        return path
    manual = sorted(BACKUP_DIR.glob("*_%s.json" % MANUAL))
    if not manual:
        raise AppError("Резервных копий нет")
    return manual[-1]


def restore_backup(name=None):
    """Возвращает (копия-источник, страховочная копия или None)."""
    path = find_backup(name)
    coins = load_backup(path)
    pre = None
    if SETTINGS_PATH.exists():
        try:
            pre = make_backup(PRE_RESTORE, load_settings(strict=True), protect=path)
        except AppError:
            pre = None  # текущие настройки некорректны — страховочная копия не нужна
    save_settings(coins)
    return path, pre


def list_backups():
    lines = []
    for path in sorted(BACKUP_DIR.glob("*.json"), reverse=True):
        mark = " [страховочная]" if path.stem.endswith("_" + PRE_RESTORE) else ""
        try:
            status = "OK, номиналов: %d" % len(load_backup(path))
        except AppError as exc:
            status = "ПОВРЕЖДЕНА (%s)" % exc
        lines.append("%s  %s%s" % (path.name, status, mark))
    return lines


# ---------------------------------------------------------------- команды

def emit(text, output=None):
    print(text)
    if output:
        write_atomic(output, text + "\n")


def cmd_change_file(input_path, output_path):
    coins = load_settings()
    out, errors = [], 0
    for no, line in enumerate(read_text(input_path).splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        try:
            out.append(describe_line(s, coins))
        except AppError as exc:
            errors += 1
            out.append("ОШИБКА (строка %d): %s" % (no, exc))
    if not out:
        raise AppError("Во входном файле нет данных")
    emit("\n".join(out), output_path)
    return 2 if errors else 0


def cmd_change_pair(paid_text, price_text, output=None):
    paid, price, amount = calc_pair(paid_text, price_text)
    coins = load_settings()
    emit("Оплачено %d, цена %d. %s" % (
        paid, price, format_change(amount, compute_change(amount, coins))), output)
    return 0


def cmd_change_amount(text, output=None):
    amount = parse_int(text, "Сумма")
    emit(format_change(amount, compute_change(amount, load_settings())), output)
    return 0


def ask(prompt):
    try:
        return input(prompt)
    except EOFError:
        raise AppError("Ввод прерван") from None


def cmd_change_interactive():
    paid = ask("Оплачено клиентом: ")
    price = ask("Цена: ")
    return cmd_change_pair(paid, price)


def cmd_set_coins(values):
    coins = save_settings([parse_int(v, "Номинал") for v in values])
    print("Номиналы сохранены: %s" % ", ".join(str(c) for c in coins))
    return 0


def cmd_backup():
    path = make_backup()
    print("Резервная копия создана: %s" % path.name)
    return 0


def cmd_backups():
    lines = list_backups()
    print("\n".join(lines) if lines else "Резервных копий нет")
    return 0


def cmd_restore(name=None):
    path, pre = restore_backup(name)
    if pre:
        print("Текущие настройки сохранены: %s" % pre.name)
    print("Настройки восстановлены из %s" % path.name)
    return 0


# ---------------------------------------------------------------- меню

MENU = """
=== Coin Change: расчёт сдачи ===
1. Рассчитать сдачу (ввести оплачено и цену)
2. Рассчитать сдачи из файла
3. Показать / изменить номиналы
4. Создать резервную копию
5. Восстановить из резервной копии
0. Выход"""


def menu_action(choice):
    if choice == "1":
        cmd_change_interactive()
    elif choice == "2":
        path = ask("Путь к файлу (Enter — examples/input.txt): ").strip() or str(DEFAULT_INPUT)
        cmd_change_file(path, DEFAULT_OUTPUT)
    elif choice == "3":
        print("Номиналы: %s" % ", ".join(str(c) for c in load_settings()))
        new = ask("Новые номиналы через пробел (Enter — оставить): ").split()
        if new:
            cmd_set_coins(new)
    elif choice == "4":
        cmd_backup()
    elif choice == "5":
        cmd_backups()
        cmd_restore(ask("Имя копии (Enter — последняя): ").strip() or None)
    else:
        print("Нет такого пункта меню")


def run_menu():
    while True:
        print(MENU)
        try:
            choice = input("Пункт меню: ").strip()
        except EOFError:
            print("\nРабота программы завершена")
            return 0
        if choice == "0":
            print("Работа программы завершена")
            return 0
        try:
            menu_action(choice)
        except AppError as exc:
            print("ОШИБКА: %s" % exc, file=sys.stderr)


# ---------------------------------------------------------------- CLI

def build_parser():
    p = argparse.ArgumentParser(prog="coin_change.py",
                                description="Расчёт сдачи минимальным количеством монет")
    sub = p.add_subparsers(dest="command")

    c = sub.add_parser("change", help="рассчитать сдачу")
    c.add_argument("--amount", help="сумма сдачи")
    c.add_argument("--paid", help="оплачено клиентом")
    c.add_argument("--price", help="цена")
    c.add_argument("--input", help="файл с суммами (по одной строке)")
    c.add_argument("--output", help="файл для результата (для --input по умолчанию output.txt)")

    s = sub.add_parser("set-coins", help="задать номиналы")
    s.add_argument("coins", nargs="+", help="номиналы монет")

    sub.add_parser("backup", help="создать резервную копию настроек")
    sub.add_parser("backups", help="список резервных копий")
    r = sub.add_parser("restore", help="восстановить настройки из копии")
    r.add_argument("name", nargs="?", help="имя файла копии (по умолчанию последняя)")
    return p


def dispatch(args, parser):
    if args.command is None:
        return run_menu()
    if args.command == "change":
        modes = [args.amount is not None, args.input is not None,
                 args.paid is not None or args.price is not None]
        if sum(modes) > 1:
            parser.error("укажите только один вариант: --amount, --paid/--price или --input")
        if args.input is not None:
            return cmd_change_file(args.input, args.output or DEFAULT_OUTPUT)
        if args.amount is not None:
            return cmd_change_amount(args.amount, args.output)
        if modes[2]:
            if args.paid is None or args.price is None:
                parser.error("--paid и --price нужно указывать вместе")
            return cmd_change_pair(args.paid, args.price, args.output)
        return cmd_change_interactive()
    if args.command == "set-coins":
        return cmd_set_coins(args.coins)
    if args.command == "backup":
        return cmd_backup()
    if args.command == "backups":
        return cmd_backups()
    return cmd_restore(args.name)


def main(argv=None):
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        return dispatch(args, parser)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    except AppError as exc:
        print("ОШИБКА: %s" % exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nПрервано пользователем", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
