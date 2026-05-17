# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Dot2Coma is a pair of complementary Python CLI utilities for converting decimal separators in CSV files — useful when moving data between European (comma as decimal separator) and US (dot as decimal separator) formats.

- **Dot2Coma.py** — replaces every `.` with `,` in the input CSV, outputs `<filename>_wComa.csv`
- **Coma2Dot.py** — replaces every `,` with `.` in the input CSV, outputs `<filename>_wDot.csv`

Both scripts use only the Python standard library (`sys`). No `requirements.txt` or external dependencies exist.

## Running the Scripts

```bash
python Dot2Coma.py <archivo.csv>
python Coma2Dot.py <archivo.csv>
```

Each script takes exactly one argument (the path to the input CSV). The output file is written in the same directory with the appropriate suffix.

## Building Standalone Executables

PyInstaller is used to produce single-file Windows EXEs:

```bash
pyinstaller Dot2Coma.spec   # produces dist/Dot2Coma.exe
pyinstaller Coma2Dot.spec   # produces dist/Coma2Dot.exe
```

The spec files bundle the script with UPX compression, a custom `.ico` icon, and `console=True`. Python 3.11 is the configured interpreter.

## Known Code Quirk

`Coma2Dot.py` contains a function named `replace_dots_with_commas` but it actually performs the inverse operation (replaces commas with dots). The name is a copy-paste artifact from `Dot2Coma.py`.

## No Test or Lint Infrastructure

There is no test suite, no linting configuration, and no CI/CD setup in this repository.
