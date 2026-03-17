from django.urls import path, re_path
from . import views

urlpatterns = [
    # Using re_path for more robust matching of export and print
    re_path(r'^export/?$', views.ExportReportsAPIView.as_view(), name='export-reports'),
    re_path(r'^print/?$', views.PrintReportAPIView.as_view(), name='print-reports'),
    
    path('overview/', views.ReportsOverviewAPIView.as_view(), name='reports-overview'),
    path('leads/', views.LeadReportsAPIView.as_view(), name='lead-reports'),
    path('agent-performance/', views.AgentPerformanceAPIView.as_view(), name='agent-performance'),
    path('disposition-wise/', views.DispositionWiseAPIView.as_view(), name='disposition-wise'),    
    path('asc-wise/', views.ASCWiseDetailedAPIView.as_view(), name='asc-wise'),
]