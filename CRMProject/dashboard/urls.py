from django.urls import path
from .views import LeadAnalyticsAPIView

urlpatterns = [
    path("details/", LeadAnalyticsAPIView.as_view()),

]
