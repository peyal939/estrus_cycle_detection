from django.urls import path
from .views import DownloadDataView, DatasetExporterView, index

urlpatterns = [
    path("", index, name="index"),
    path("api/download/", DownloadDataView.as_view(), name="download_data"),
    path("api/export/", DatasetExporterView.as_view(), name="export_dataset"),
]
