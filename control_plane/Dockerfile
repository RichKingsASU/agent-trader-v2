# --- Stage 1: Build Frontend ---
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend

# Copy frontend source
COPY control_plane/frontend/package.json ./
# Initial installation
RUN npm install

COPY control_plane/frontend/ .
# Build
RUN npm run build


# --- Stage 2: Runtime ---
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy backend code (needed for imports)
COPY backend/ /app/backend/
COPY scripts/ /app/scripts/

# Copy control plane code
COPY control_plane/ /app/control_plane/

# Copy built frontend from Stage 1
COPY --from=frontend-builder /app/frontend/dist /app/control_plane/frontend/dist

# Install backend dependencies
COPY control_plane/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Install core backend dependencies (for execution paths)
COPY backend/requirements.txt /app/backend_requirements.txt
RUN pip install --no-cache-dir -r backend_requirements.txt

# Set Python path
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8080

# Run the application
CMD ["uvicorn", "control_plane.app:app", "--host", "0.0.0.0", "--port", "8080"]
