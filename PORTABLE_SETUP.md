# Portable isolated setup

This project uses a local `.venv` so backend packages do not modify Conda base or the system Python environment.

## Requirements

- Windows 10 or 11
- Python 3.11 or 3.12
- Node.js with npm

## First setup on each device

Open Command Prompt or PowerShell in the project folder and run:

```cmd
setup.cmd
```

The script creates `.venv`, installs Python packages inside it, installs frontend packages, and creates local environment configuration files when missing.

The first installation downloads PyTorch and other AI packages. On a slow connection this can take 30 minutes or more. Leave the terminal open until `Setup complete` appears.

Do not copy `.venv` or `frontend/node_modules` between computers. Copy the project source, models and lock files, then run `setup.cmd` again on each device.

## Run

Start the backend:

```cmd
run-backend.cmd
```

Start the frontend in a second terminal:

```cmd
run-frontend.cmd
```

The backend launcher only uses `.venv\Scripts\python.exe`. It will stop with an error if the isolated environment is missing or setup did not finish successfully.

## Remove the environment

Close the backend first, then delete only the project `.venv` directory. This does not uninstall or change system Python, Conda base, or packages used by other projects.
