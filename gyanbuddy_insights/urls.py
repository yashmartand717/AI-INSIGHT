from django.urls import path
from . import views

app_name = "gyanbuddy_insights"
urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("config/", views.dashboard_config, name="dashboard-config"),
    path("batches/", views.batches, name="batches"),
    path("marks-uploaded/", views.marks_uploaded, name="marks-uploaded"),
    path("email-all-reports/", views.email_all_reports, name="email-all-reports"),
    path("batches/<uuid:batch_id>/", views.batch_status, name="batch-status"),
    path("batches/<uuid:batch_id>/reports/", views.reports, name="reports"),
    path("batches/<uuid:batch_id>/emails/", views.emails, name="emails"),
]
