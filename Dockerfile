FROM python:3.12-slim

WORKDIR /app

# Dependências primeiro (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código
COPY server/ ./server/
COPY dcs/ ./dcs/

# Portas
# 8000 = HTTP/WebSocket  |  7778/udp = DCS Export.lua
EXPOSE 8000
EXPOSE 7778/udp

# Variáveis de ambiente (override na hora do run se precisar)
ENV UDP_HOST=0.0.0.0
ENV UDP_PORT=7778
ENV API_HOST=0.0.0.0
ENV API_PORT=8000

CMD ["python", "-m", "server.main"]
