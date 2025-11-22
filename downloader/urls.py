from django.urls import path
from .views import DownloadDataView, index

urlpatterns = [
    path('', index, name='index'),
    path('api/download/', DownloadDataView.as_view(), name='download_data'),
]
