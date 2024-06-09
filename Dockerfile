FROM python:3.10-slim-bullseye
WORKDIR /app

# Install necessary dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    tesseract-ocr \
    libtesseract-dev \
    libleptonica-dev \
    pkg-config \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Python and Poetry
RUN pip3 install --upgrade pip && \
    pip3 install poetry

# Copy necessary files for Poetry
COPY pyproject.toml poetry.lock README.md ./

# Install Python dependencies
RUN poetry config virtualenvs.create false && \
    poetry install

# Copy the rest of the application code
COPY . /app

# Check Tesseract installation
RUN tesseract --version

EXPOSE 8501

ENTRYPOINT ["streamlit", "run"]

CMD ["app.py"]