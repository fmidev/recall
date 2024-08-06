FROM python:3-slim

# Set the working directory
WORKDIR /app

# Install dependencies
COPY . /app
RUN pip install -U pip && pip install -r requirements.txt

RUN chmod +x run.sh
CMD ["./run.sh"]
