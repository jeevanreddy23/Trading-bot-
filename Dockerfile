FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Paper mode by default. For live you must pass env keys + LIVE_TRADING_ACK
# and change config mode — see docs/GOING_LIVE.md.
CMD ["python", "run.py"]
