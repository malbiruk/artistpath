# Build stage
FROM rust:1.87-slim as builder

# Install system dependencies for building
RUN apt-get update && apt-get install -y \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy workspace files
COPY core ./core
COPY web/backend ./web/backend

# Build the application
WORKDIR /app/web/backend
RUN cargo build --release

# Runtime stage
FROM debian:bookworm-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the compiled binary
COPY --from=builder /app/web/backend/target/release/artistpath-web /app/artistpath-web

# Create data directory
RUN mkdir -p /app/data

# Copy data files (will be mounted as volume in production)
# COPY ../../data/graph.bin /app/data/
# COPY ../../data/metadata.bin /app/data/

# Expose port
EXPOSE 3000

# Set environment variables
ENV RUST_LOG=info

# Run the application
CMD ["./artistpath-web"]