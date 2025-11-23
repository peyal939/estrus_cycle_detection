#!/bin/bash

# Start Gunicorn
# Workers: 3 (Adjust based on CPU cores: 2 * cores + 1)
# Bind: 0.0.0.0:8000
echo "Starting Gunicorn..."
exec gunicorn harness_data_portal.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --log-level=info \
    --access-logfile - \
    --error-logfile -