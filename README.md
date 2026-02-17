# Harness-Tag Data Downloader

A Django-based web application for collecting, storing, and exporting IoT sensor data from harness tags. The system listens to MQTT messages from IoT devices, stores them in MongoDB (time-series), and provides a web interface for data export and temperature variance analysis.

## Features

- **MQTT Data Ingestion**: Listens to MQTT broker for real-time sensor data from harness tags
- **MongoDB Time-Series Storage**: Stores IoT data in a MongoDB time-series collection for efficient querying
- **CSV Data Export**: Export sensor data to CSV with flexible date/time range and tag filtering
- **Temperature Variance Dashboard**: Visualize temperature statistics with interactive charts
- **Large Dataset Handling**: Streaming exports with warnings for large datasets
- **User Authentication**: Login-protected data access
- **Timezone Support**: Handles Bangladesh Standard Time (BST) to UTC conversion

## Technology Stack

- **Backend**: Django 5.2, Django REST Framework
- **Database**: MongoDB (time-series collection), SQLite (user auth)
- **Message Broker**: MQTT (Paho MQTT client)
- **Frontend**: HTML/CSS, Chart.js for visualizations
- **Static Files**: WhiteNoise for static file serving
- **Server**: Gunicorn (production)

## Project Structure

```
harness-tag-data-downloader/
├── downloader/                    # Main Django app
│   ├── management/commands/       # Custom management commands
│   │   └── run_mqtt_listener.py   # MQTT listener command
│   ├── templates/                 # HTML templates
│   │   ├── dashboard.html         # Temperature variance dashboard
│   │   ├── index.html             # Data export interface
│   │   └── registration/          # Login templates
│   ├── urls.py                    # URL routing
│   ├── views.py                   # API views and page renders
│   └── utils.py                   # Database utilities
├── harness_data_portal/           # Django project settings
├── staticfiles/                   # Collected static files
├── requirements.txt               # Python dependencies
└── manage.py                      # Django management script
```

## Installation

### Prerequisites

- Python 3.10+
- MongoDB (with time-series collection support)
- MQTT Broker access

### Setup

1. **Clone the repository**
   ```bash
   git clone https://gitlab.com/adorsho-pranisheba/ps-iot/harness-tag-data-downloader.git
   cd harness-tag-data-downloader
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   venv\Scripts\activate     # Windows
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**
   
   Create a `.env` file in the project root:
   ```env
   # Django Settings
   DEBUG=False
   ALLOWED_HOSTS=localhost,127.0.0.1,your-domain.com
   CSRF_TRUSTED_ORIGINS=https://your-domain.com

   # MongoDB
   MONGO_URI=mongodb+srv://username:password@cluster.mongodb.net/?retryWrites=true&w=majority

   # MQTT Configuration
   MQTT_BROKER=your-mqtt-broker.com
   MQTT_PORT=1883
   MQTT_TOPIC=your/mqtt/topic
   MQTT_USER=mqtt_username
   MQTT_PASS=mqtt_password

   # Export Settings (optional)
   LARGE_DATASET_THRESHOLD=100000
   EXPORT_CHUNK_SECONDS=3600
   ```

5. **Run database migrations**
   ```bash
   python manage.py migrate
   ```

6. **Create a superuser**
   ```bash
   python manage.py createsuperuser
   ```

7. **Collect static files**
   ```bash
   python manage.py collectstatic
   ```

## MongoDB Setup

Create a time-series collection named `iotdata` in the `harnesstag` database:

```javascript
db.createCollection("iotdata", {
   timeseries: {
      timeField: "\"time\"",
      metaField: "tagID",
      granularity: "seconds"
   }
})
```

## Usage

### Running the Development Server

```bash
python manage.py runserver
```

Access the application at `http://localhost:8000`

### Running the MQTT Listener

Start the MQTT listener to ingest data from IoT devices:

```bash
python manage.py run_mqtt_listener
```

### Production Deployment

Use Gunicorn for production:

```bash
gunicorn harness_data_portal.wsgi:application --bind 0.0.0.0:8000
```

Or use the provided script:

```bash
./start_server.sh
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Data export interface (index page) |
| `/dashboard/` | GET | Temperature variance dashboard |
| `/api/download/` | GET | Download data by date range |
| `/api/export/` | GET | Advanced export with tag filtering |
| `/api/temperature-variance/` | GET | Temperature statistics API |
| `/accounts/login/` | GET/POST | User login |
| `/admin/` | GET | Django admin interface |

### Export API Parameters

**`/api/export/`**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `start_date` | Yes | Start date (YYYY-MM-DD) |
| `end_date` | No | End date (YYYY-MM-DD), defaults to start_date |
| `start_time` | No | Start time (HH:MM:SS), defaults to 00:00:00 |
| `end_time` | No | End time (HH:MM:SS), defaults to 23:59:59 |
| `tag_ids` | No | Comma-separated tag IDs, empty for all |
| `confirm` | No | Set to `true` to bypass large dataset warning |

### Sensor Data Fields

The exported CSV includes the following sensor fields:

| Field | Description |
|-------|-------------|
| `ax`, `ay`, `az` | Accelerometer (X, Y, Z) |
| `gx`, `gy`, `gz` | Gyroscope (X, Y, Z) |
| `mx`, `my`, `mz` | Magnetometer (X, Y, Z) |
| `amb` | Ambient temperature |
| `obj` | Object temperature (used for variance analysis) |
| `soc` | State of charge (battery) |

## Environment Variables Reference

| Variable | Description | Default |
|----------|-------------|---------|
| `DEBUG` | Enable debug mode | `False` |
| `ALLOWED_HOSTS` | Comma-separated allowed hosts | `localhost,127.0.0.1` |
| `CSRF_TRUSTED_ORIGINS` | CSRF trusted origins | - |
| `MONGO_URI` | MongoDB connection string | - |
| `MQTT_BROKER` | MQTT broker hostname | - |
| `MQTT_PORT` | MQTT broker port | - |
| `MQTT_TOPIC` | MQTT topic to subscribe | - |
| `MQTT_USER` | MQTT username | - |
| `MQTT_PASS` | MQTT password | - |
| `LARGE_DATASET_THRESHOLD` | Warning threshold for large exports | `100000` |
| `EXPORT_CHUNK_SECONDS` | Time chunk for streaming exports | `3600` |

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Merge Request

## License

This project is proprietary software developed for Adorsho Pranisheba.