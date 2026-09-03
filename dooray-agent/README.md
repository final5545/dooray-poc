# dooray_agent

A simple echo agent using Dooray SDK

## Setup

1. Create virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# or
.venv\Scripts\activate  # Windows
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure environment:

```bash
cp .env.example .env
# Edit .env and set your DOORAY_AGENT_TOKEN
```

## Run

```bash
python main.py
```

## How it works

This agent echoes back any message it receives:

- User sends: "Hello"
- Agent replies: "Echo: Hello"

## Author

wonseokjeong
