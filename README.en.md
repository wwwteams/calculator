# Coin Change — minimum number of coins for change

[🇷🇺 Русский](README.md) · 🇬🇧 English

A Python console program that finds the minimum number of coins of given denominations needed to give change (**greedy algorithm**). It works through the console and through files, and can back up and restore cash register settings.

## About

- Calculates change using denominations from `config/settings.json` (default: 10, 5, 2, 1).
- Input: interactive menu, command-line arguments, or a text file.
- Output: console or a text file.
- Backup and restore of cash register settings (SHA-256 checksum).
- Python standard library only, no external packages.

> ⚠️ The greedy algorithm is optimal for "canonical" coin systems (e.g. 1, 2, 5, 10). For arbitrary sets (e.g. 1, 3, 4 and amount 6) the result may not be optimal.

## Installation

**Requirements:** Python 3.8+ and Git.

1. Check Python:
   ```bash
   python --version
   ```
   On Linux/macOS you may need `python3`.
2. Get the project:
   ```bash
   git clone https://github.com/<your-username>/<repository-name>.git
   cd <repository-name>
   ```
   Or click **Code → Download ZIP** on the repository page and unpack it.
3. Run:
   ```bash
   python coin_change.py
   ```

## Usage

### 1. Interactive menu
```bash
python coin_change.py
```
| Item | Action |
|---|---|
| 1 | Calculate change: enter the amount paid and the price |
| 2 | Calculate change from a file |
| 3 | Show / edit denominations |
| 4 | Create a backup |
| 5 | Restore from a backup |
| 0 | Exit |

### 2. Command line

| Command | Description |
|---|---|
| `python coin_change.py change --amount 78` | Change for 78 |
| `python coin_change.py change --input examples/input.txt --output output.txt` | File to file |
| `python coin_change.py set-coins 10 5 2 1` | Set denominations |
| `python coin_change.py backup` | Create a backup |
| `python coin_change.py backups` | List backups |
| `python coin_change.py restore` | Restore from the latest backup |
| `python coin_change.py restore <file_name>` | Restore from a chosen backup |

Example:
```
$ python coin_change.py change --amount 78
Сдача 78: 10 x 7, 5 x 1, 2 x 1, 1 x 1 (всего 10)
```
(The program's output is in Russian: "Сдача" = change, "всего" = total coins.)

### 3. Input file format
Each line is either one number (the change amount) or two numbers separated by a space (`paid price`). Empty lines and lines starting with `#` are skipped.
```
# comment
78
100 22
```
An invalid line does not stop processing: the output gets `ОШИБКА (строка N): …` ("ERROR (line N)") and the exit code is 2.

### 4. Backups
Backups are stored in `backups/` (the 10 most recent are kept). Before a restore, the program saves the current settings as `*_pre-restore.json`. If a backup file was edited by hand, the restore is rejected because the checksum no longer matches.

## Tests
```bash
python -m unittest discover -s tests -v
```
Manual test cases: [docs/TEST_CASES.md](docs/TEST_CASES.md) (in Russian).

## Project structure
```
.
├── coin_change.py        # the program
├── config/settings.json  # cash register settings
├── examples/input.txt    # sample input file
├── tests/                # automated tests
├── docs/
│   ├── TZ.md             # technical specification (RU)
│   ├── MAINTENANCE.md    # maintenance regulations (RU)
│   └── TEST_CASES.md     # test cases (RU)
├── README.md             # user guide (RU)
└── README.en.md          # user guide (EN)
```

## Author
_Full name, group_
