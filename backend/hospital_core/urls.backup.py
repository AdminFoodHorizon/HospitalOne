from django.urls import path
from . import views
from . import reception_views
from . import announcement_views

urlpatterns = [
    path('csrf/', views.csrf, name='hospital-csrf'),
    path('<slug:slug>/login/', views.password_login, name='hospital-login'),
    path('<slug:slug>/2fa/enroll/', views.enroll_start, name='hospital-2fa-enroll'),
    path('<slug:slug>/2fa/confirm/', views.enroll_confirm, name='hospital-2fa-confirm'),
    path('<slug:slug>/2fa/verify/', views.verify_login, name='hospital-2fa-verify'),
    path('<slug:slug>/2fa/recovery-login/', views.recovery_login, name='hospital-2fa-recovery'),
    path('<slug:slug>/me/', views.me, name='hospital-me'),
    path('<slug:slug>/logout/', views.staff_logout, name='hospital-logout'),
    path('<slug:slug>/reception/doctors/', reception_views.doctors, name='hospital-reception-doctors'),
    path('<slug:slug>/reception/visits/', reception_views.visits, name='hospital-reception-visits'),
    path('<slug:slug>/reception/register/', reception_views.register_visit, name='hospital-reception-register'),
    path('<slug:slug>/reception/patients/search/', reception_views.search_patients, name='reception_patient_search'),
    path('<slug:slug>/announcement/queue/', announcement_views.queue_board, name='hospital-announcement-queue'),
]
