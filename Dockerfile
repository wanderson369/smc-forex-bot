FROM python:3.11-slim
WORKDIR /app
COPY requirements_forex.txt .
RUN pip install --no-cache-dir -r requirements_forex.txt
COPY smc_forex_bot.py .
CMD ["python", "-u", "smc_forex_bot.py"]
