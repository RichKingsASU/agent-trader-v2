
# Use a Python 3.12 slim image as the base
FROM python:3.12-slim-bookworm

# Set the working directory in the container to the root of the app
WORKDIR /app

# Copy the entire project into the container
COPY . .

# Set the working directory to the specific strategy folder
WORKDIR /app/functions/strategies/gamma_scalper

# Install any needed packages specified in requirements.txt for this specific strategy
RUN pip install --no-cache-dir -r requirements.txt

# Specify the command to run the application
CMD ["python", "gamma_scalper.py"]
