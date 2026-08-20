# System Tracker Python Environment

## Purpose

The System Tracker uses the same Python application code on the laptop and desktop.

The Python environment itself is machine-local.

Do not synchronize `.venv` through Google Drive or Git.

## Python baseline

Both machines use:

- Python 3.13.x
- Anaconda as the base Python installation
- A project-local `.venv`

Expected base interpreter:

```text
C:\ProgramData\anaconda3\python.exe

## One-command machine setup

The project includes:

```text
scripts/setup_machine.ps1