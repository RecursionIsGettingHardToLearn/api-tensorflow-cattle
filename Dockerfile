 # Usa una imagen oficial de Python como base
FROM python:3.11-slim

 # Define el directorio de trabajo
 WORKDIR /app
 
 # Copia y actualiza pip antes de instalar dependencias
 COPY requirements.txt .
 #RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt
 RUN pip install --upgrade pip && pip install --no-cache-dir --default-timeout=200 -r requirements.txt
 #RUN pip install --upgrade pip && pip install --no-cache-dir -i https://pypi.org/simple -r requirements.txt
 
 # Copia el código de la aplicación después de instalar dependencias
 COPY . .
 
 # Expone el puerto en el que se ejecutará la app
 EXPOSE 8080
 
 # Comando para ejecutar la aplicación
 CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]