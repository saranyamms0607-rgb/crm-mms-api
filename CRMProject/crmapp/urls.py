from django.urls import path
from .views import LeadDetailView, LeadGetView,LeadCountView, LeadCreateView

urlpatterns = [
    path("leads/", LeadDetailView.as_view(), name="lead-detail"),
    path("leads/<int:pk>/", LeadDetailView.as_view(), name="lead-detail"),
    path("leads/<int:pk>/tracking/", LeadDetailView.as_view(), name="lead-detail"),
    
    path("get/lead/", LeadGetView.as_view(), name="get-lead"),

    path("leads/count/", LeadCountView.as_view(), name="lead-count"),

     path("leads/create/", LeadCreateView.as_view(), name="create-lead"),

]
