from django.urls import path

from .views import PrometheusDevicesView

urlpatterns = [
    path("prometheus-devices/", PrometheusDevicesView.as_view(), name="prometheus-devices"),
]
