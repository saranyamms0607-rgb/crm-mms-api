from django.urls import path
from .views import LeadCSVImportView, LeadCSVExportView,LoginUserListView,ASCFilterListView, AgentCSVUpdateView

urlpatterns = [
    path("leads/import-csv/", LeadCSVImportView.as_view()),
    path("leads/export-csv/", LeadCSVExportView.as_view()),

    path("users/", LoginUserListView.as_view()),
    path("users/<int:pk>/", LoginUserListView.as_view()),
    path("leads/agent-csv-update/", AgentCSVUpdateView.as_view()),

    path("asc-filters/", ASCFilterListView.as_view()),
]
