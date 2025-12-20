from django.urls import path
from .views import DownloadDataView, DatasetExporterView, TemperatureVarianceView, index, dashboard

urlpatterns = [
    path("", index, name="index"),
    path("dashboard/", dashboard, name="dashboard"),
    path("api/download/", DownloadDataView.as_view(), name="download_data"),
    path("api/export/", DatasetExporterView.as_view(), name="export_dataset"),
    path("api/temperature-variance/", TemperatureVarianceView.as_view(), name="temperature_variance"),
]
