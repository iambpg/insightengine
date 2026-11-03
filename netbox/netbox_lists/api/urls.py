from django.urls import path

from .views import PrometheusDevicesView, PrometheusServicesView, PrometheusVbsView

urlpatterns = [
    path("prometheus-devices/", PrometheusDevicesView.as_view(), name="prometheus-devices"),
    path("prometheus-services/", PrometheusServicesView.as_view(), name="prometheus-services"),
    path("prometheus-vbs/", PrometheusVbsView.as_view(), name="prometheus-vbs"),
]
