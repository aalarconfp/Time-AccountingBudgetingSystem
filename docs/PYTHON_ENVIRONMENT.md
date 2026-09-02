# System Tracker Python Environment

## Purpose

The System Tracker uses the same Python application code on the laptop and desktop.

The Python environment itself is machine-local.

Do not synchronize `.venv` through Google Drive or Git.

## Python baseline

Each machine has its own Python installation and project-local `.venv`.

The Python version and base interpreter may differ between machines. The `.venv` must always be created from a valid Python installation available on the machine where the pipeline is being executed.

The current Desktop environment uses:

```text
Python 3.14.x
C:\Users\User\AppData\Local\Python\pythoncore-3.14-64\python.exe