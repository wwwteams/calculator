# -*- coding: utf-8 -*-
import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import coin_change as cc  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for p in (mock.patch.object(cc, "SETTINGS_PATH", self.root / "config" / "settings.json"),
                  mock.patch.object(cc, "BACKUP_DIR", self.root / "backups"),
                  mock.patch.object(cc, "DEFAULT_OUTPUT", self.root / "output.txt")):
            p.start()
            self.addCleanup(p.stop)
        self.settings = cc.SETTINGS_PATH
        self.backups = cc.BACKUP_DIR

    def run_cli(self, *argv, inputs=None):
        out, err = io.StringIO(), io.StringIO()
        feed = iter(inputs or [])

        def fake_input(prompt=""):
            try:
                return next(feed)
            except StopIteration:
                raise EOFError

        with redirect_stdout(out), redirect_stderr(err), \
                mock.patch("builtins.input", side_effect=fake_input):
            code = cc.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def set_coins(self, *coins):
        cc.save_settings(list(coins))


class ParseTests(Base):
    def test_parse_int_ok(self):
        self.assertEqual(cc.parse_int(" 78 ", "Сумма"), 78)
        self.assertEqual(cc.parse_int("-5", "Сумма"), -5)

    def test_parse_int_rejects_bad_values(self):
        for bad in ("abc", "1.5", "", "  ", "1_000", "1,5"):
            with self.subTest(bad=bad):
                with self.assertRaises(cc.AppError):
                    cc.parse_int(bad, "Сумма")

    def test_normalize_sorts_and_dedups(self):
        self.assertEqual(cc.normalize_coins([1, 5, 2, 10, 5]), [10, 5, 2, 1])

    def test_normalize_rejects_invalid(self):
        for bad in ([], [0], [-1, 5], [1.5], ["5"], [True]):
            with self.subTest(bad=bad):
                with self.assertRaises(cc.AppError):
                    cc.normalize_coins(bad)


class ChangeTests(Base):
    def test_classic_78(self):
        self.assertEqual(cc.compute_change(78, [10, 5, 2, 1]),
                         [(10, 7), (5, 1), (2, 1), (1, 1)])

    def test_zero_amount(self):
        self.assertEqual(cc.compute_change(0, [10, 5, 2, 1]), [])
        self.assertIn("монеты не нужны", cc.format_change(0, []))

    def test_exact_coin(self):
        self.assertEqual(cc.compute_change(5, [10, 5, 2, 1]), [(5, 1)])

    def test_sum_of_coins_equals_amount(self):
        for amount in range(0, 200):
            res = cc.compute_change(amount, [10, 5, 2, 1])
            self.assertEqual(sum(c * n for c, n in res), amount)

    def test_negative_amount_rejected(self):
        with self.assertRaises(cc.AppError):
            cc.compute_change(-1, [1])

    def test_impossible_without_unit_coin(self):
        with self.assertRaises(cc.AppError) as ctx:
            cc.compute_change(3, [5, 2])
        self.assertIn("остаток 1", str(ctx.exception))

    def test_greedy_not_optimal_for_noncanonical(self):
        # 6 при номиналах 4, 3, 1: жадный даёт 4+1+1 (3 монеты), оптимум 3+3 (2 монеты)
        res = cc.compute_change(6, [4, 3, 1])
        self.assertEqual(res, [(4, 1), (1, 2)])

    def test_huge_amount_is_fast(self):
        start = time.time()
        res = cc.compute_change(10 ** 30 + 7, [10, 5, 2, 1])
        self.assertLess(time.time() - start, 0.1)
        self.assertEqual(sum(c * n for c, n in res), 10 ** 30 + 7)

    def test_format_change(self):
        self.assertEqual(cc.format_change(78, cc.compute_change(78, [10, 5, 2, 1])),
                         "Сдача 78: 10 x 7, 5 x 1, 2 x 1, 1 x 1 (всего 10)")

    def test_calc_pair(self):
        self.assertEqual(cc.calc_pair("100", "22"), (100, 22, 78))
        self.assertEqual(cc.calc_pair("50", "50")[2], 0)

    def test_calc_pair_errors(self):
        for paid, price in (("10", "20"), ("-1", "0"), ("5", "-1"), ("a", "1"), ("1", "b")):
            with self.subTest(paid=paid, price=price):
                with self.assertRaises(cc.AppError):
                    cc.calc_pair(paid, price)

    def test_describe_line_variants(self):
        coins = [10, 5, 2, 1]
        self.assertTrue(cc.describe_line("78", coins).startswith("Сдача 78"))
        self.assertTrue(cc.describe_line("100 22", coins).startswith("Оплачено 100, цена 22."))
        with self.assertRaises(cc.AppError):
            cc.describe_line("1 2 3", coins)


class SettingsAndFileTests(Base):
    def test_defaults_when_missing(self):
        self.assertEqual(cc.load_settings(), [10, 5, 2, 1])

    def test_strict_missing(self):
        with self.assertRaises(cc.AppError):
            cc.load_settings(strict=True)

    def test_save_and_load(self):
        self.set_coins(1, 25, 10)
        self.assertEqual(cc.load_settings(), [25, 10, 1])

    def test_corrupted_settings(self):
        for text in ("{", "[]", '{"coins": 5}', '{"coins": []}', '{"coins": [0]}'):
            with self.subTest(text=text):
                self.write("config/settings.json", text)
                with self.assertRaises(cc.AppError):
                    cc.load_settings()

    def test_read_text_bom_and_crlf(self):
        path = self.root / "a.txt"
        path.write_bytes("\ufeff78\r\n9\r\n".encode("utf-8"))
        self.assertEqual(cc.read_text(path).splitlines(), ["78", "9"])

    def test_read_text_errors(self):
        bad = self.root / "bad.txt"
        bad.write_bytes(b"\xff\xfe\x00\x80")
        for target in (bad, self.root / "nope.txt", self.root):
            with self.subTest(target=str(target)):
                with self.assertRaises(cc.AppError):
                    cc.read_text(target)

    def test_atomic_write_no_tmp(self):
        path = self.root / "x" / "f.txt"
        cc.write_atomic(path, "данные\n")
        self.assertEqual(path.read_text(encoding="utf-8"), "данные\n")
        self.assertEqual([p.name for p in path.parent.iterdir()], ["f.txt"])

    def test_atomic_write_keeps_old_on_failure(self):
        path = self.write("f.txt", "старое")
        with mock.patch("os.replace", side_effect=OSError("boom")):
            with self.assertRaises(cc.AppError):
                cc.write_atomic(path, "новое")
        self.assertEqual(path.read_text(encoding="utf-8"), "старое")
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.endswith(".tmp")], [])


class BackupTests(Base):
    def setUp(self):
        super().setUp()
        self.set_coins(10, 5, 2, 1)

    def test_backup_structure_and_checksum(self):
        path = cc.make_backup()
        doc = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set(doc), {"created", "checksum", "data"})
        self.assertEqual(doc["data"], {"coins": [10, 5, 2, 1]})
        self.assertEqual(doc["checksum"], cc.checksum_of(doc["data"]))
        self.assertTrue(path.name.endswith("_manual.json"))

    def test_backup_requires_valid_settings(self):
        self.write("config/settings.json", "{")
        with self.assertRaises(cc.AppError):
            cc.make_backup()
        self.assertEqual(list(self.backups.glob("*.json")), [])

    def test_backup_requires_existing_settings(self):
        self.settings.unlink()
        with self.assertRaises(cc.AppError):
            cc.make_backup()

    def test_rotation_keeps_ten_newest(self):
        names = [cc.make_backup().name for _ in range(12)]
        left = sorted(p.name for p in self.backups.glob("*.json"))
        self.assertEqual(left, sorted(names)[-10:])

    def test_restore_latest(self):
        cc.make_backup()
        self.set_coins(1)
        path, pre = cc.restore_backup()
        self.assertEqual(cc.load_settings(), [10, 5, 2, 1])
        self.assertTrue(pre.name.endswith("_pre-restore.json"))

    def test_restore_twice_stays_on_manual(self):
        cc.make_backup()
        self.set_coins(1)
        cc.restore_backup()
        self.set_coins(7)
        cc.restore_backup()
        self.assertEqual(cc.load_settings(), [10, 5, 2, 1])

    def test_restore_by_name_and_undo(self):
        first = cc.make_backup()
        self.set_coins(25, 1)
        _, pre = cc.restore_backup(first.name)
        self.assertEqual(cc.load_settings(), [10, 5, 2, 1])
        cc.restore_backup(pre.name)
        self.assertEqual(cc.load_settings(), [25, 1])

    def test_tampered_backup_rejected_settings_unchanged(self):
        path = cc.make_backup()
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["data"]["coins"] = [999]
        path.write_text(json.dumps(doc), encoding="utf-8")
        self.set_coins(3, 1)
        with self.assertRaises(cc.AppError) as ctx:
            cc.restore_backup()
        self.assertIn("SHA-256", str(ctx.exception))
        self.assertEqual(cc.load_settings(), [3, 1])
        self.assertEqual(len(list(self.backups.glob("*pre-restore.json"))), 0)

    def test_broken_and_wrong_structure(self):
        self.backups.mkdir(exist_ok=True)
        for text in ("не json", "[]", '{"data": {}}', '{"checksum": "x", "data": {"coins": 1}}'):
            with self.subTest(text=text):
                p = self.backups / "20200101_000000_000000_manual.json"
                p.write_text(text, encoding="utf-8")
                with self.assertRaises(cc.AppError):
                    cc.restore_backup()
                p.unlink()

    def test_no_backups_and_unknown_name(self):
        with self.assertRaises(cc.AppError):
            cc.restore_backup()
        with self.assertRaises(cc.AppError):
            cc.restore_backup("nope.json")

    def test_name_cannot_escape_backup_dir(self):
        self.write("secret.json", "{}")
        with self.assertRaises(cc.AppError):
            cc.restore_backup("../secret.json")

    def test_restore_when_settings_missing_no_pre_restore(self):
        cc.make_backup()
        self.settings.unlink()
        _, pre = cc.restore_backup()
        self.assertIsNone(pre)
        self.assertEqual(cc.load_settings(), [10, 5, 2, 1])

    def test_restore_when_settings_corrupted_no_pre_restore(self):
        cc.make_backup()
        self.write("config/settings.json", "{")
        _, pre = cc.restore_backup()
        self.assertIsNone(pre)

    def test_restore_source_not_rotated_away(self):
        first = cc.make_backup()
        for _ in range(9):
            cc.make_backup()
        self.assertEqual(len(list(self.backups.glob("*.json"))), 10)
        cc.restore_backup(first.name)
        self.assertTrue(first.exists())
        self.assertLessEqual(len(list(self.backups.glob("*.json"))), 10)

    def test_list_marks_status(self):
        good = cc.make_backup()
        self.set_coins(2, 1)
        cc.restore_backup()
        bad = self.backups / "20200101_000000_000000_manual.json"
        bad.write_text("{}", encoding="utf-8")
        text = "\n".join(cc.list_backups())
        self.assertIn("[страховочная]", text)
        self.assertIn("ПОВРЕЖДЕНА", text)
        self.assertIn(good.name + "  OK", text)


class CliTests(Base):
    def test_change_amount(self):
        code, out, err = self.run_cli("change", "--amount", "78")
        self.assertEqual(code, 0)
        self.assertIn("Сдача 78: 10 x 7, 5 x 1, 2 x 1, 1 x 1 (всего 10)", out)

    def test_change_paid_price(self):
        code, out, _ = self.run_cli("change", "--paid", "100", "--price", "22")
        self.assertEqual(code, 0)
        self.assertIn("Оплачено 100, цена 22. Сдача 78", out)

    def test_change_uses_settings(self):
        self.set_coins(4, 3, 1)
        _, out, _ = self.run_cli("change", "--amount", "6")
        self.assertIn("4 x 1, 1 x 2", out)

    def test_error_cases_return_1_without_traceback(self):
        cases = [("--amount", "abc"), ("--amount", "-5"), ("--amount", "1.5"),
                 ("--paid", "10", "--price", "20"), ("--paid", "x", "--price", "1")]
        for extra in cases:
            with self.subTest(extra=extra):
                code, _, err = self.run_cli("change", *extra)
                self.assertEqual(code, 1)
                self.assertIn("ОШИБКА", err)
                self.assertNotIn("Traceback", err)

    def test_impossible_change_returns_1(self):
        self.set_coins(5, 2)
        code, _, err = self.run_cli("change", "--amount", "3")
        self.assertEqual(code, 1)
        self.assertIn("Невозможно", err)

    def test_conflicting_or_incomplete_options_return_2(self):
        self.assertEqual(self.run_cli("change", "--amount", "5", "--paid", "9", "--price", "1")[0], 2)
        self.assertEqual(self.run_cli("change", "--paid", "9")[0], 2)

    def test_interactive_change(self):
        code, out, _ = self.run_cli("change", inputs=["100", "22"])
        self.assertEqual(code, 0)
        self.assertIn("Сдача 78", out)

    def test_interactive_eof_is_error(self):
        code, _, err = self.run_cli("change", inputs=["100"])
        self.assertEqual(code, 1)
        self.assertIn("Ввод прерван", err)

    def test_input_file_default_output(self):
        src = self.write("in.txt", "# заголовок\n78\n\n100 22\n9\n")
        code, out, _ = self.run_cli("change", "--input", str(src))
        self.assertEqual(code, 0)
        text = cc.DEFAULT_OUTPUT.read_text(encoding="utf-8")
        self.assertEqual(text.count("\n"), 3)
        self.assertEqual(text, out)

    def test_input_file_custom_output(self):
        src = self.write("in.txt", "78\n")
        dst = self.root / "result.txt"
        code, _, _ = self.run_cli("change", "--input", str(src), "--output", str(dst))
        self.assertEqual(code, 0)
        self.assertIn("Сдача 78", dst.read_text(encoding="utf-8"))
        self.assertFalse(cc.DEFAULT_OUTPUT.exists())

    def test_input_file_bad_lines_continue_and_code_2(self):
        src = self.write("in.txt", "78\nabc\n10 20\n9\n")
        code, out, _ = self.run_cli("change", "--input", str(src))
        self.assertEqual(code, 2)
        self.assertIn("ОШИБКА (строка 2)", out)
        self.assertIn("ОШИБКА (строка 3)", out)
        self.assertIn("Сдача 9", out)

    def test_input_file_errors(self):
        empty = self.write("empty.txt", "# только комментарий\n\n")
        for path in (self.root / "nope.txt", empty):
            with self.subTest(path=path.name):
                code, _, err = self.run_cli("change", "--input", str(path))
                self.assertEqual(code, 1)
                self.assertNotIn("Traceback", err)

    def test_error_keeps_existing_output(self):
        out_file = self.write("output.txt", "старый результат\n")
        code, _, _ = self.run_cli("change", "--amount", "abc", "--output", str(out_file))
        self.assertEqual(code, 1)
        self.assertEqual(out_file.read_text(encoding="utf-8"), "старый результат\n")
        code, _, _ = self.run_cli("change", "--input", str(self.root / "nope.txt"))
        self.assertEqual(out_file.read_text(encoding="utf-8"), "старый результат\n")

    def test_set_coins(self):
        code, out, _ = self.run_cli("set-coins", "1", "5", "25", "10")
        self.assertEqual(code, 0)
        self.assertIn("25, 10, 5, 1", out)
        self.assertEqual(cc.load_settings(), [25, 10, 5, 1])

    def test_set_coins_invalid_keeps_settings(self):
        self.set_coins(10, 5, 1)
        for bad in (["10", "0"], ["abc"], ["-3"], ["1.5"]):
            with self.subTest(bad=bad):
                code, _, _ = self.run_cli("set-coins", *bad)
                self.assertEqual(code, 1)
                self.assertEqual(cc.load_settings(), [10, 5, 1])

    def test_backup_backups_restore_flow(self):
        self.set_coins(10, 5, 2, 1)
        code, out, _ = self.run_cli("backup")
        self.assertEqual((code, "создана" in out), (0, True))
        self.run_cli("set-coins", "3")
        code, out, _ = self.run_cli("restore")
        self.assertEqual(code, 0)
        self.assertIn("Текущие настройки сохранены", out)
        self.assertEqual(cc.load_settings(), [10, 5, 2, 1])
        code, out, _ = self.run_cli("backups")
        self.assertIn("OK, номиналов: 4", out)
        self.assertIn("[страховочная]", out)

    def test_backups_empty_and_restore_errors(self):
        self.assertIn("Резервных копий нет", self.run_cli("backups")[1])
        code, _, err = self.run_cli("restore")
        self.assertEqual(code, 1)
        self.assertIn("Резервных копий нет", err)
        code, _, err = self.run_cli("restore", "nope.json")
        self.assertEqual(code, 1)
        self.assertIn("не найдена", err)

    def test_backup_extra_argument_returns_2(self):
        code, _, err = self.run_cli("backup", "лишнее")
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", err)


class MenuTests(Base):
    def test_exit(self):
        code, out, _ = self.run_cli(inputs=["0"])
        self.assertEqual(code, 0)
        self.assertIn("Работа программы завершена", out)

    def test_calc_from_menu(self):
        code, out, _ = self.run_cli(inputs=["1", "100", "22", "0"])
        self.assertEqual(code, 0)
        self.assertIn("Сдача 78", out)

    def test_unknown_item(self):
        _, out, _ = self.run_cli(inputs=["99", "0"])
        self.assertIn("Нет такого пункта", out)

    def test_error_does_not_stop_menu(self):
        code, out, err = self.run_cli(inputs=["1", "abc", "5", "1", "100", "22", "0"])
        self.assertEqual(code, 0)
        self.assertIn("ОШИБКА", err)
        self.assertIn("Сдача 78", out)

    def test_eof_ends_program(self):
        code, out, _ = self.run_cli(inputs=[])
        self.assertEqual(code, 0)
        self.assertIn("Работа программы завершена", out)

    def test_change_coins_in_menu(self):
        code, out, _ = self.run_cli(inputs=["3", "25 10 5 1", "0"])
        self.assertEqual(code, 0)
        self.assertEqual(cc.load_settings(), [25, 10, 5, 1])

    def test_file_calc_in_menu(self):
        src = self.write("in.txt", "78\n")
        _, out, _ = self.run_cli(inputs=["2", str(src), "0"])
        self.assertIn("Сдача 78", out)
        self.assertTrue(cc.DEFAULT_OUTPUT.exists())

    def test_backup_and_restore_in_menu(self):
        self.set_coins(10, 5, 1)
        self.run_cli(inputs=["4", "0"])
        self.set_coins(3)
        _, out, _ = self.run_cli(inputs=["5", "", "0"])
        self.assertIn("Настройки восстановлены", out)
        self.assertEqual(cc.load_settings(), [10, 5, 1])


class PerformanceTests(Base):
    def test_hundred_thousand_lines(self):
        src = self.write("big.txt", "\n".join(str(i) for i in range(100000)) + "\n")
        start = time.time()
        code, _, _ = self.run_cli("change", "--input", str(src))
        self.assertEqual(code, 0)
        self.assertLess(time.time() - start, 2.0)


if __name__ == "__main__":
    unittest.main()
