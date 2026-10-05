from django.urls import path
from . import views

app_name = "gyanbuddy_insights"
urlpatterns = [
    path("marks-uploaded/", views.marks_uploaded, name="marks-uploaded"),
    path("batches/<uuid:batch_id>/", views.batch_status, name="batch-status"),
    path("batches/<uuid:batch_id>/reports/", views.reports, name="reports"),
    path("batches/<uuid:batch_id>/emails/", views.emails, name="emails"),
]
